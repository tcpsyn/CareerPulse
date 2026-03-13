import json

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
async def test_skill_gap_data_empty(db):
    result = await db.get_skill_gap_data(50, 80)
    assert result["job_count"] == 0
    assert result["top_concerns"] == []
    assert result["top_keywords"] == []


@pytest.mark.asyncio
async def test_skill_gap_data_aggregation(db):
    # Insert some jobs and scores in the 50-80 range
    for i in range(3):
        job_id = await db.insert_job(
            title=f"Engineer {i}", company="TestCo",
            location="Remote", salary_min=None, salary_max=None,
            description="", url=f"https://example.com/{i}",
            posted_date=None, application_method=None, contact_email=None,
        )
        concerns = ["No Python experience", "Missing Docker"] if i < 2 else ["No Python experience"]
        keywords = ["Python", "Docker"] if i < 2 else ["Python", "Kubernetes"]
        await db.insert_score(job_id, 65, ["Good match"], concerns, keywords)

    result = await db.get_skill_gap_data(50, 80)
    assert result["job_count"] == 3

    # Python concern appears in all 3
    concern_dict = dict(result["top_concerns"])
    assert concern_dict["no python experience"] == 3
    assert concern_dict["missing docker"] == 2

    # Python keyword appears in all 3
    keyword_dict = dict(result["top_keywords"])
    assert keyword_dict["python"] == 3
    assert keyword_dict["docker"] == 2
    assert keyword_dict["kubernetes"] == 1


@pytest.mark.asyncio
async def test_skill_gap_data_excludes_out_of_range(db):
    # Job scoring 90 should be excluded
    job_id = await db.insert_job(
        title="Senior Dev", company="BigCo",
        location="Remote", salary_min=None, salary_max=None,
        description="", url="https://example.com/high",
        posted_date=None, application_method=None, contact_email=None,
    )
    await db.insert_score(job_id, 90, ["Perfect"], ["None"], ["Python"])

    # Job scoring 30 should be excluded
    job_id2 = await db.insert_job(
        title="Junior Dev", company="SmallCo",
        location="Remote", salary_min=None, salary_max=None,
        description="", url="https://example.com/low",
        posted_date=None, application_method=None, contact_email=None,
    )
    await db.insert_score(job_id2, 30, ["Partial"], ["No experience"], ["Java"])

    result = await db.get_skill_gap_data(50, 80)
    assert result["job_count"] == 0


@pytest.mark.asyncio
async def test_skill_gaps_endpoint(client):
    resp = await client.get("/api/skill-gaps")
    assert resp.status_code == 200
    data = resp.json()
    assert "job_count" in data
    assert "top_concerns" in data
    assert "top_keywords" in data
    assert "user_skills" in data


@pytest.mark.asyncio
async def test_skill_gaps_analyze_no_ai(client):
    resp = await client.post("/api/skill-gaps/analyze")
    assert resp.status_code == 503  # AI not configured in test
