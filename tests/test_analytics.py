import pytest
from httpx import AsyncClient, ASGITransport

from app.database import Database


@pytest.fixture
async def app(tmp_path):
    from app.main import create_app
    application = create_app(db_path=str(tmp_path / "test.db"), testing=True)
    db = Database(str(tmp_path / "test.db"))
    await db.init()
    application.state.db = db
    yield application
    await db.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db(app):
    return app.state.db


@pytest.mark.asyncio
async def test_analytics_empty(db):
    result = await db.get_analytics()
    assert result["funnel"]["interested"] == 0
    assert result["funnel"]["applied"] == 0
    assert result["score_calibration"]["interested"] is None
    assert result["sources"] == []
    assert result["weekly_velocity"] == [] or isinstance(result["weekly_velocity"], list)


@pytest.mark.asyncio
async def test_analytics_endpoint(client):
    resp = await client.get("/api/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert "funnel" in data
    assert "score_calibration" in data
    assert "sources" in data
    assert "weekly_velocity" in data


@pytest.mark.asyncio
async def test_analytics_funnel_counts(db):
    # Insert jobs and applications at different statuses
    for i, status in enumerate(["interested", "interested", "applied", "interviewing"]):
        job_id = await db.insert_job(
            title=f"Job {i}", company="TestCo",
            location="Remote", salary_min=None, salary_max=None,
            description="", url=f"https://example.com/{i}",
            posted_date=None, application_method=None, contact_email=None,
        )
        await db.insert_score(job_id, 75, ["Good"], ["Minor gap"], ["Python"])
        await db.db.execute(
            "INSERT INTO applications (job_id, status) VALUES (?, ?)",
            (job_id, status))
    await db.db.commit()

    result = await db.get_analytics()
    assert result["funnel"]["interested"] == 2
    assert result["funnel"]["applied"] == 1
    assert result["funnel"]["interviewing"] == 1
    assert result["funnel"]["offered"] == 0


@pytest.mark.asyncio
async def test_analytics_score_calibration(db):
    # Create jobs with different scores for different statuses
    for score, status in [(80, "applied"), (70, "applied"), (60, "rejected")]:
        job_id = await db.insert_job(
            title="Dev", company="Co",
            location="Remote", salary_min=None, salary_max=None,
            description="", url=f"https://example.com/{score}-{status}",
            posted_date=None, application_method=None, contact_email=None,
        )
        await db.insert_score(job_id, score, ["OK"], ["Gap"], ["Skill"])
        await db.db.execute(
            "INSERT INTO applications (job_id, status) VALUES (?, ?)",
            (job_id, status))
    await db.db.commit()

    result = await db.get_analytics()
    assert result["score_calibration"]["applied"] == 75.0
    assert result["score_calibration"]["rejected"] == 60.0
    assert result["score_calibration"]["interested"] is None
