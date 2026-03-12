import logging

from app.database import Database, make_dedup_hash

logger = logging.getLogger(__name__)


async def run_scrape_cycle(db: Database, scrapers: list, search_terms: list[str] | None = None, progress: dict | None = None, scraper_keys: dict | None = None) -> int:
    total_new = 0
    total_scrapers = len(scrapers)
    for i, scraper_instance in enumerate(scrapers):
        if isinstance(scraper_instance, type):
            scraper_instance = scraper_instance(search_terms=search_terms, scraper_keys=scraper_keys or {})
        source_name = scraper_instance.source_name
        logger.info(f"Scraping {source_name}...")
        if progress is not None:
            progress.update({"completed": i, "total": total_scrapers, "current": source_name, "new_jobs": total_new, "active": True})
        try:
            listings = await scraper_instance.scrape()
        except Exception as e:
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

    # Enrich jobs with short/missing descriptions
    from app.enrichment import enrich_job_description
    jobs_to_enrich = await db.get_jobs_needing_enrichment(limit=30)
    enriched_count = 0
    for job in jobs_to_enrich:
        sources = await db.get_sources(job["id"])
        source = sources[0]["source_name"] if sources else "unknown"
        desc = await enrich_job_description(job["url"], source)
        if desc and len(desc) > len(job.get("description") or ""):
            await db.update_job_description(job["id"], desc)
            enriched_count += 1
    if enriched_count:
        logger.info(f"Enriched {enriched_count}/{len(jobs_to_enrich)} job descriptions")

    dismissed = await db.auto_dismiss_stale()
    if dismissed:
        logger.info(f"Auto-dismissed {dismissed} stale jobs")

    if progress is not None:
        progress.update({"completed": total_scrapers, "total": total_scrapers, "current": None, "new_jobs": total_new, "active": False})
    logger.info(f"Scrape cycle complete. {total_new} new jobs added.")
    return total_new
