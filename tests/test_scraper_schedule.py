import pytest
from datetime import datetime, timedelta, timezone
from app.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_default_schedule_should_run(db):
    """A scraper with no schedule record should always run."""
    should_run = await db.should_scraper_run("dice")
    assert should_run is True


@pytest.mark.asyncio
async def test_recently_run_scraper_skips(db):
    await db.update_scraper_schedule("hackernews", interval_hours=24)
    await db.mark_scraper_ran("hackernews")
    should_run = await db.should_scraper_run("hackernews")
    assert should_run is False


@pytest.mark.asyncio
async def test_overdue_scraper_runs(db):
    await db.update_scraper_schedule("dice", interval_hours=1)
    # Mark as ran 2 hours ago
    old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    await db.db.execute(
        "UPDATE scraper_schedule SET last_scraped_at = ? WHERE source_name = ?",
        (old_time, "dice"),
    )
    await db.db.commit()
    should_run = await db.should_scraper_run("dice")
    assert should_run is True


@pytest.mark.asyncio
async def test_get_all_schedules(db):
    await db.update_scraper_schedule("dice", interval_hours=4)
    await db.update_scraper_schedule("hackernews", interval_hours=168)
    schedules = await db.get_all_scraper_schedules()
    assert len(schedules) == 2
    names = {s["source_name"] for s in schedules}
    assert "dice" in names
    assert "hackernews" in names
