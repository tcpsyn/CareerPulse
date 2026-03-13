import pytest
from app.database import Database


@pytest.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    await database.init()
    yield database
    await database.close()


async def _insert_job(db, title="Test Job", company="TestCo"):
    job_id = await db.insert_job(
        title=title, company=company, location="Remote",
        salary_min=None, salary_max=None, description="A test job",
        url="https://example.com/job/1", posted_date=None,
        application_method="url", contact_email=None,
    )
    return job_id


@pytest.mark.asyncio
async def test_insert_notification(db):
    job_id = await _insert_job(db)
    notif_id = await db.insert_notification(job_id, "high_score", "High score!", "Score 95")
    assert notif_id is not None


@pytest.mark.asyncio
async def test_get_notifications(db):
    job_id = await _insert_job(db)
    await db.insert_notification(job_id, "high_score", "Alert 1", "Msg 1")
    await db.insert_notification(job_id, "high_score", "Alert 2", "Msg 2")
    notifs = await db.get_notifications()
    assert len(notifs) == 2
    assert notifs[0]["title"] == "Alert 2"  # newest first


@pytest.mark.asyncio
async def test_get_notifications_unread_only(db):
    job_id = await _insert_job(db)
    n1 = await db.insert_notification(job_id, "high_score", "Unread", "Msg")
    n2 = await db.insert_notification(job_id, "high_score", "Read", "Msg")
    await db.mark_notification_read(n2)

    unread = await db.get_notifications(unread_only=True)
    assert len(unread) == 1
    assert unread[0]["id"] == n1


@pytest.mark.asyncio
async def test_unread_count(db):
    job_id = await _insert_job(db)
    await db.insert_notification(job_id, "high_score", "A", "B")
    await db.insert_notification(job_id, "high_score", "C", "D")
    assert await db.get_unread_notification_count() == 2


@pytest.mark.asyncio
async def test_mark_notification_read(db):
    job_id = await _insert_job(db)
    nid = await db.insert_notification(job_id, "high_score", "A", "B")
    await db.mark_notification_read(nid)
    assert await db.get_unread_notification_count() == 0


@pytest.mark.asyncio
async def test_mark_all_read(db):
    job_id = await _insert_job(db)
    await db.insert_notification(job_id, "high_score", "A", "B")
    await db.insert_notification(job_id, "high_score", "C", "D")
    await db.insert_notification(job_id, "high_score", "E", "F")
    await db.mark_all_notifications_read()
    assert await db.get_unread_notification_count() == 0


@pytest.mark.asyncio
async def test_notification_defaults(db):
    job_id = await _insert_job(db)
    await db.insert_notification(job_id, "high_score", "Title", "Message")
    notifs = await db.get_notifications()
    assert notifs[0]["read"] == 0
    assert notifs[0]["type"] == "high_score"
    assert notifs[0]["job_id"] == job_id
