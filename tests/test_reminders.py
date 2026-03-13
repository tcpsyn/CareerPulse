import pytest
from datetime import datetime, timezone, timedelta

from app.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    yield database
    await database.close()


@pytest.fixture
async def job_id(db):
    return await db.insert_job(
        title="Test Engineer", company="TestCo", location="Remote",
        description="A test job", url="https://example.com/test",
        salary_min=None, salary_max=None, posted_date=None,
        application_method=None, contact_email=None,
    )


@pytest.mark.asyncio
async def test_create_and_get_reminder(db, job_id):
    remind_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    rid = await db.create_reminder(job_id, remind_at)
    reminders = await db.get_reminders_for_job(job_id)
    assert len(reminders) == 1
    assert reminders[0]["id"] == rid
    assert reminders[0]["status"] == "pending"
    assert reminders[0]["reminder_type"] == "follow_up"


@pytest.mark.asyncio
async def test_get_due_reminders(db, job_id):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    await db.create_reminder(job_id, past)
    await db.create_reminder(job_id, future)
    due = await db.get_due_reminders()
    assert len(due) == 1
    assert due[0]["title"] == "Test Engineer"


@pytest.mark.asyncio
async def test_complete_reminder(db, job_id):
    remind_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    rid = await db.create_reminder(job_id, remind_at)
    await db.complete_reminder(rid)
    reminders = await db.get_reminders_for_job(job_id)
    assert reminders[0]["status"] == "completed"
    assert reminders[0]["completed_at"] is not None


@pytest.mark.asyncio
async def test_dismiss_reminder(db, job_id):
    remind_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    rid = await db.create_reminder(job_id, remind_at)
    await db.dismiss_reminder(rid)
    reminders = await db.get_reminders_for_job(job_id)
    assert reminders[0]["status"] == "dismissed"


@pytest.mark.asyncio
async def test_get_reminders_with_status_filter(db, job_id):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    rid = await db.create_reminder(job_id, past)
    await db.complete_reminder(rid)
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    await db.create_reminder(job_id, future)

    pending = await db.get_reminders(status="pending")
    assert len(pending) == 1
    completed = await db.get_reminders(status="completed")
    assert len(completed) == 1
    all_reminders = await db.get_reminders()
    assert len(all_reminders) == 2


@pytest.mark.asyncio
async def test_get_reminders_include_job(db, job_id):
    remind_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    await db.create_reminder(job_id, remind_at)
    reminders = await db.get_reminders(include_job=True)
    assert len(reminders) == 1
    assert reminders[0]["title"] == "Test Engineer"
    assert reminders[0]["company"] == "TestCo"
