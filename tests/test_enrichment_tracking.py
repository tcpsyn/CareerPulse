import pytest
from app.database import Database


@pytest.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    await database.init()
    yield database
    await database.close()


async def _insert_job(db, url="https://example.com/job/1", description=None):
    job_id = await db.insert_job(
        title="Test Job", company="TestCo", location="Remote",
        salary_min=None, salary_max=None, description=description,
        url=url, posted_date=None,
        application_method="url", contact_email=None,
    )
    await db.insert_source(job_id, "test_source", url)
    return job_id


@pytest.mark.asyncio
async def test_new_job_has_pending_status(db):
    job_id = await _insert_job(db)
    job = await db.get_job(job_id)
    assert job["enrichment_status"] == "pending"
    assert job["enrichment_attempts"] == 0


@pytest.mark.asyncio
async def test_update_enrichment_status(db):
    job_id = await _insert_job(db)
    await db.update_enrichment_status(job_id, "failed", 1)
    job = await db.get_job(job_id)
    assert job["enrichment_status"] == "failed"
    assert job["enrichment_attempts"] == 1


@pytest.mark.asyncio
async def test_failed_under_3_attempts_still_returned(db):
    job_id = await _insert_job(db)
    await db.update_enrichment_status(job_id, "failed", 2)
    jobs = await db.get_jobs_needing_enrichment()
    ids = [j["id"] for j in jobs]
    assert job_id in ids


@pytest.mark.asyncio
async def test_failed_at_3_attempts_excluded(db):
    job_id = await _insert_job(db)
    await db.update_enrichment_status(job_id, "failed", 3)
    jobs = await db.get_jobs_needing_enrichment()
    ids = [j["id"] for j in jobs]
    assert job_id not in ids


@pytest.mark.asyncio
async def test_failed_over_3_attempts_excluded(db):
    job_id = await _insert_job(db)
    await db.update_enrichment_status(job_id, "failed", 5)
    jobs = await db.get_jobs_needing_enrichment()
    ids = [j["id"] for j in jobs]
    assert job_id not in ids


@pytest.mark.asyncio
async def test_enriched_status_excluded(db):
    job_id = await _insert_job(db)
    await db.update_job_description(job_id, "A" * 300)
    job = await db.get_job(job_id)
    assert job["enrichment_status"] == "enriched"
    assert job["description_enriched"] == 1
    jobs = await db.get_jobs_needing_enrichment()
    ids = [j["id"] for j in jobs]
    assert job_id not in ids


@pytest.mark.asyncio
async def test_pending_job_returned_for_enrichment(db):
    job_id = await _insert_job(db)
    jobs = await db.get_jobs_needing_enrichment()
    ids = [j["id"] for j in jobs]
    assert job_id in ids


@pytest.mark.asyncio
async def test_enrichment_attempts_in_query_result(db):
    job_id = await _insert_job(db)
    await db.update_enrichment_status(job_id, "failed", 2)
    jobs = await db.get_jobs_needing_enrichment()
    job = next(j for j in jobs if j["id"] == job_id)
    assert job["enrichment_attempts"] == 2
