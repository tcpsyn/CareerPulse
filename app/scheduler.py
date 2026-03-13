import asyncio
import logging

from app.circuit_breaker import CircuitBreaker
from app.database import Database, make_dedup_hash

logger = logging.getLogger(__name__)

_scraper_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=300.0)
_enrichment_semaphore = asyncio.Semaphore(3)


async def run_scrape_cycle(db: Database, scrapers: list, search_terms: list[str] | None = None, progress: dict | None = None, scraper_keys: dict | None = None) -> int:
    """Scrape job boards and insert new listings. Scrape-only — no enrichment or scoring."""
    total_new = 0
    total_scrapers = len(scrapers)
    for i, scraper_instance in enumerate(scrapers):
        if isinstance(scraper_instance, type):
            scraper_instance = scraper_instance(search_terms=search_terms, scraper_keys=scraper_keys or {})
        source_name = scraper_instance.source_name
        # Check per-source schedule
        if not await db.should_scraper_run(source_name):
            logger.info(f"Skipping {source_name} — not yet due")
            if progress is not None:
                progress.update({"completed": i + 1, "total": total_scrapers, "current": source_name, "new_jobs": total_new, "active": True})
            continue
        if _scraper_breaker.is_open(f"scraper:{source_name}"):
            logger.info(f"Circuit breaker open for {source_name}, skipping")
            if progress is not None:
                progress.update({"completed": i + 1, "total": total_scrapers, "current": source_name, "new_jobs": total_new, "active": True})
            continue
        logger.info(f"Scraping {source_name}...")
        if progress is not None:
            progress.update({"completed": i, "total": total_scrapers, "current": source_name, "new_jobs": total_new, "active": True})
        try:
            listings = await scraper_instance.scrape()
            _scraper_breaker.record_success(f"scraper:{source_name}")
        except Exception as e:
            _scraper_breaker.record_failure(f"scraper:{source_name}")
            logger.error(f"Scraper {source_name} failed: {e}")
            continue

        for listing in listings:
            dedup = make_dedup_hash(listing.title, listing.company, listing.url)
            existing = await db.find_job_by_hash(dedup)
            if existing:
                await db.insert_source(existing["id"], source_name, listing.url)
            else:
                job_id = await db.insert_job(
                    title=listing.title,
                    company=listing.company,
                    location=listing.location,
                    salary_min=listing.salary_min,
                    salary_max=listing.salary_max,
                    description=listing.description,
                    url=listing.url,
                    posted_date=listing.posted_date,
                    application_method=listing.application_method,
                    contact_email=listing.contact_email,
                )
                if job_id:
                    # Check for cross-source duplicates
                    dupes = await db.find_cross_source_dupes(job_id, listing.title, listing.company)
                    if dupes:
                        # Merge: add source to oldest existing job, dismiss this new one
                        oldest = dupes[0]
                        await db.insert_source(oldest["id"], source_name, listing.url)
                        await db.dismiss_job(job_id)
                        logger.debug(f"Dedup: merged '{listing.title}' @ {listing.company} into job {oldest['id']}")
                    else:
                        await db.insert_source(job_id, source_name, listing.url)
                        total_new += 1

        logger.info(f"{source_name}: found {len(listings)} listings")
        await db.mark_scraper_ran(source_name)

    if progress is not None:
        progress.update({"completed": total_scrapers, "total": total_scrapers, "current": None, "new_jobs": total_new, "active": False})
    logger.info(f"Scrape cycle complete. {total_new} new jobs added.")
    return total_new


async def run_enrichment_cycle(db: Database, limit: int = 30) -> int:
    """Enrich jobs with short/missing descriptions. Runs independently of scraping."""
    from app.enrichment import enrich_job_description

    async with _enrichment_semaphore:
        jobs_to_enrich = await db.get_jobs_needing_enrichment(limit=limit)
        enriched_count = 0
        for job in jobs_to_enrich:
            sources = await db.get_sources(job["id"])
            source = sources[0]["source_name"] if sources else "unknown"
            attempts = (job.get("enrichment_attempts") or 0) + 1
            desc = await enrich_job_description(job["url"], source)
            if desc and len(desc) > len(job.get("description") or ""):
                await db.update_job_description(job["id"], desc)
                await db.update_enrichment_status(job["id"], "enriched", attempts)
                enriched_count += 1
            else:
                await db.update_enrichment_status(job["id"], "failed", attempts)
        if enriched_count:
            logger.info(f"Enriched {enriched_count}/{len(jobs_to_enrich)} job descriptions")
        return enriched_count


async def run_maintenance_cycle(db: Database) -> int:
    """Auto-dismiss stale jobs. Runs independently on a daily schedule."""
    dismissed = await db.auto_dismiss_stale()
    if dismissed:
        logger.info(f"Auto-dismissed {dismissed} stale jobs")
    return dismissed


async def run_reminder_check(db: Database) -> list[dict]:
    """Check for due follow-up reminders. Returns list of due reminders."""
    due = await db.get_due_reminders()
    if due:
        logger.info(f"Found {len(due)} due follow-up reminders")
    return due


async def run_digest_cycle(db: Database) -> bool:
    """Check if digest is enabled and send it. Called by APScheduler."""
    from app.digest import send_digest
    try:
        return await send_digest(db)
    except Exception as e:
        logger.error(f"Digest cycle failed: {e}")
        return False
