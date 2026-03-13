import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.database import Database
from app.scrapers.base import JobListing
from app.scheduler import run_scrape_cycle, run_enrichment_cycle, run_maintenance_cycle


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    yield database
    await database.close()


def make_mock_scraper(source_name, jobs):
    scraper = MagicMock()
    scraper.source_name = source_name
    scraper.scrape = AsyncMock(return_value=jobs)
    return scraper


@pytest.mark.asyncio
async def test_scrape_cycle_stores_jobs(db):
    scraper = make_mock_scraper("test", [
        JobListing(
            title="Test Job", company="TestCo", location="Remote",
            description="A test job", url="https://example.com/test",
            source="test", salary_min=160000, salary_max=200000,
        )
    ])
    new_count = await run_scrape_cycle(db, scrapers=[scraper])
    assert new_count == 1
    jobs = await db.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Test Job"
    sources = await db.get_sources(jobs[0]["id"])
    assert sources[0]["source_name"] == "test"


@pytest.mark.asyncio
async def test_scrape_cycle_deduplicates(db):
    job = JobListing(
        title="Test Job", company="TestCo", location="Remote",
        description="A test job", url="https://example.com/test",
        source="test",
    )
    scraper = make_mock_scraper("test", [job])
    await run_scrape_cycle(db, scrapers=[scraper])
    await run_scrape_cycle(db, scrapers=[scraper])
    jobs = await db.list_jobs()
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_scrape_cycle_multiple_sources(db):
    job1 = JobListing(
        title="Same Job", company="SameCo", location="Remote",
        description="desc", url="https://example.com/same",
        source="source1",
    )
    job2 = JobListing(
        title="Same Job", company="SameCo", location="Remote",
        description="desc", url="https://example.com/same",
        source="source2",
    )
    s1 = make_mock_scraper("source1", [job1])
    s2 = make_mock_scraper("source2", [job2])
    await run_scrape_cycle(db, scrapers=[s1, s2])
    jobs = await db.list_jobs()
    assert len(jobs) == 1
    sources = await db.get_sources(jobs[0]["id"])
    assert len(sources) == 2


@pytest.mark.asyncio
async def test_scrape_cycle_handles_scraper_error(db):
    bad_scraper = MagicMock()
    bad_scraper.source_name = "bad"
    bad_scraper.scrape = AsyncMock(side_effect=Exception("boom"))

    good_scraper = make_mock_scraper("good", [
        JobListing(
            title="Good Job", company="GoodCo", location="Remote",
            description="good", url="https://example.com/good",
            source="good",
        )
    ])
    new_count = await run_scrape_cycle(db, scrapers=[bad_scraper, good_scraper])
    assert new_count == 1
    jobs = await db.list_jobs()
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_scrape_cycle_does_not_enrich(db):
    """Scrape cycle should NOT run enrichment (decoupled)."""
    scraper = make_mock_scraper("test", [
        JobListing(
            title="Job", company="Co", location="Remote",
            description="short", url="https://example.com/j",
            source="test",
        )
    ])
    with patch("app.scheduler.run_enrichment_cycle", new_callable=AsyncMock) as mock_enrich:
        await run_scrape_cycle(db, scrapers=[scraper])
        mock_enrich.assert_not_called()


@pytest.mark.asyncio
async def test_enrichment_cycle(db):
    """Enrichment cycle processes jobs independently."""
    job_id = await db.insert_job(
        title="Enrich Me", company="Co", location="Remote",
        description="x", url="https://example.com/enrich",
        salary_min=None, salary_max=None, posted_date=None,
        application_method=None, contact_email=None,
    )
    await db.insert_source(job_id, "test", "https://example.com/enrich")
    with patch("app.enrichment.enrich_job_description", new_callable=AsyncMock, return_value="Full description " * 20):
        count = await run_enrichment_cycle(db, limit=10)
    assert count == 1


@pytest.mark.asyncio
async def test_maintenance_cycle(db):
    """Maintenance cycle auto-dismisses stale jobs."""
    dismissed = await run_maintenance_cycle(db)
    assert dismissed == 0  # no stale jobs in empty db


@pytest.mark.asyncio
async def test_scrape_cycle_tracks_progress(db):
    """Progress dict is updated during scrape."""
    scraper = make_mock_scraper("test", [
        JobListing(
            title="Job", company="Co", location="Remote",
            description="desc", url="https://example.com/j",
            source="test",
        )
    ])
    progress = {"completed": 0, "total": 0, "current": None, "new_jobs": 0, "active": True}
    await run_scrape_cycle(db, scrapers=[scraper], progress=progress)
    assert progress["active"] is False
    assert progress["completed"] == 1
    assert progress["new_jobs"] == 1
