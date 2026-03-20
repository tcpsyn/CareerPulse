import pytest
from datetime import datetime, timedelta, timezone
from app.database import _normalize_posted_date


async def _backdate_last_seen(db, job_id, days_ago=10):
    """Set last_seen_at to an old date so auto_dismiss_stale can act on it."""
    old = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    await db.db.execute("UPDATE jobs SET last_seen_at = ? WHERE id = ?", (old, job_id))
    await db.db.commit()


@pytest.mark.asyncio
async def test_dismiss_old_posted_date(db):
    old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    jid = await db.insert_job(
        title="Old Job", company="Co", location="Remote",
        salary_min=None, salary_max=None, description="d",
        url="https://example.com/old", posted_date=old_date,
        application_method="url", contact_email=None,
    )
    await _backdate_last_seen(db, jid)
    # Debug: verify state before dismiss
    job = await db.get_job(jid)
    assert job is not None, f"Job {jid} not found after insert"
    assert job["dismissed"] == 0, f"Job already dismissed before auto_dismiss_stale"
    assert job.get("last_seen_at") is not None, f"last_seen_at is None — column may not exist"
    dismissed = await db.auto_dismiss_stale(max_age_days=30, no_date_max_days=14)
    assert dismissed >= 1, f"Expected >=1 dismissed, got {dismissed}. Job state: posted_date={job['posted_date']}, last_seen_at={job.get('last_seen_at')}, created_at={job['created_at']}"
    job = await db.get_job(jid)
    assert job["dismissed"] == 1


@pytest.mark.asyncio
async def test_dismiss_no_date_old_created(db):
    jid = await db.insert_job(
        title="No Date Job", company="Co", location="Remote",
        salary_min=None, salary_max=None, description="d",
        url="https://example.com/nodate", posted_date=None,
        application_method="url", contact_email=None,
    )
    old_created = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    await db.db.execute(
        "UPDATE jobs SET created_at = ?, last_seen_at = ? WHERE id = ?",
        (old_created, old_created, jid),
    )
    await db.db.commit()
    dismissed = await db.auto_dismiss_stale(max_age_days=30, no_date_max_days=14)
    assert dismissed >= 1


@pytest.mark.asyncio
async def test_keeps_fresh_jobs(db):
    jid = await db.insert_job(
        title="Fresh Job", company="Co", location="Remote",
        salary_min=None, salary_max=None, description="d",
        url="https://example.com/fresh",
        posted_date=datetime.now(timezone.utc).isoformat(),
        application_method="url", contact_email=None,
    )
    await db.auto_dismiss_stale(max_age_days=30, no_date_max_days=14)
    job = await db.get_job(jid)
    assert job["dismissed"] == 0


@pytest.mark.asyncio
async def test_skips_applied_jobs(db):
    old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    jid = await db.insert_job(
        title="Applied Old Job", company="Co", location="Remote",
        salary_min=None, salary_max=None, description="d",
        url="https://example.com/applied", posted_date=old_date,
        application_method="url", contact_email=None,
    )
    await _backdate_last_seen(db, jid)
    await db.insert_application(jid, status="applied")
    await db.auto_dismiss_stale(max_age_days=30, no_date_max_days=14)
    job = await db.get_job(jid)
    assert job["dismissed"] == 0


@pytest.mark.asyncio
async def test_unix_timestamp_posted_date_not_dismissed(db):
    """Jobs with Unix timestamp posted_dates for recent dates should NOT be dismissed."""
    recent_ts = str(int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp()))
    jid = await db.insert_job(
        title="Unix TS Job", company="Co", location="Remote",
        salary_min=None, salary_max=None, description="d",
        url="https://example.com/unix-ts", posted_date=recent_ts,
        application_method="url", contact_email=None,
    )
    job = await db.get_job(jid)
    assert job["posted_date"].startswith("20"), f"Expected ISO date, got {job['posted_date']}"
    await db.auto_dismiss_stale(max_age_days=30, no_date_max_days=14)
    job = await db.get_job(jid)
    assert job["dismissed"] == 0


@pytest.mark.asyncio
async def test_old_unix_timestamp_dismissed(db):
    """Jobs with Unix timestamp posted_dates for old dates should be dismissed."""
    old_ts = str(int((datetime.now(timezone.utc) - timedelta(days=45)).timestamp()))
    jid = await db.insert_job(
        title="Old Unix TS Job", company="Co", location="Remote",
        salary_min=None, salary_max=None, description="d",
        url="https://example.com/old-unix-ts", posted_date=old_ts,
        application_method="url", contact_email=None,
    )
    await _backdate_last_seen(db, jid)
    await db.auto_dismiss_stale(max_age_days=30, no_date_max_days=14)
    job = await db.get_job(jid)
    assert job["dismissed"] == 1


@pytest.mark.asyncio
async def test_recently_seen_job_not_dismissed(db):
    """Jobs seen recently by a scraper should NOT be dismissed even with old posted_date."""
    old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    jid = await db.insert_job(
        title="Still Active Job", company="Co", location="Remote",
        salary_min=None, salary_max=None, description="d",
        url="https://example.com/still-active", posted_date=old_date,
        application_method="url", contact_email=None,
    )
    # last_seen_at is set to now by insert_job, so it's recent
    await db.auto_dismiss_stale(max_age_days=30, no_date_max_days=14)
    job = await db.get_job(jid)
    assert job["dismissed"] == 0


@pytest.mark.asyncio
async def test_update_last_seen(db):
    jid = await db.insert_job(
        title="Seen Job", company="Co", location="Remote",
        salary_min=None, salary_max=None, description="d",
        url="https://example.com/seen", posted_date=None,
        application_method="url", contact_email=None,
    )
    await _backdate_last_seen(db, jid, days_ago=20)
    await db.update_last_seen(jid)
    job = await db.get_job(jid)
    # last_seen_at should be updated to approximately now
    last_seen = datetime.fromisoformat(job["last_seen_at"])
    assert (datetime.now(timezone.utc) - last_seen).total_seconds() < 5


@pytest.mark.asyncio
async def test_insert_job_sets_last_seen_at(db):
    jid = await db.insert_job(
        title="New Job", company="Co", location="Remote",
        salary_min=None, salary_max=None, description="d",
        url="https://example.com/new-job", posted_date=None,
        application_method="url", contact_email=None,
    )
    job = await db.get_job(jid)
    assert job["last_seen_at"] is not None
    last_seen = datetime.fromisoformat(job["last_seen_at"])
    assert (datetime.now(timezone.utc) - last_seen).total_seconds() < 5


def test_normalize_posted_date_unix():
    result = _normalize_posted_date("1773906979")
    assert result is not None
    assert result.startswith("2026-")


def test_normalize_posted_date_iso_passthrough():
    iso = "2026-03-19T07:56:19+00:00"
    assert _normalize_posted_date(iso) == iso


def test_normalize_posted_date_none():
    assert _normalize_posted_date(None) is None
    assert _normalize_posted_date("") is None
