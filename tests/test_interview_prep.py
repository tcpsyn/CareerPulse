import json
import pytest
from unittest.mock import AsyncMock, patch

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
        title="Senior Engineer", company="TestCo", location="Remote",
        description="Build scalable systems with Python and Kubernetes",
        url="https://example.com/test",
        salary_min=None, salary_max=None, posted_date=None,
        application_method=None, contact_email=None,
    )


SAMPLE_PREP = {
    "behavioral_questions": [
        "Tell me about a time you led a technical initiative",
        "Describe a conflict with a teammate",
    ],
    "technical_questions": [
        "Explain Kubernetes pod scheduling",
        "How would you design a rate limiter?",
    ],
    "star_stories": [
        "Led migration from monolith to microservices — reduced deploy time 80%",
    ],
    "talking_points": [
        "Deep Python expertise with FastAPI",
        "Experience scaling distributed systems",
    ],
}


@pytest.mark.asyncio
async def test_save_and_get_interview_prep(db, job_id):
    await db.save_interview_prep(job_id, SAMPLE_PREP)
    prep = await db.get_interview_prep(job_id)
    assert prep is not None
    assert prep["behavioral_questions"] == SAMPLE_PREP["behavioral_questions"]
    assert prep["technical_questions"] == SAMPLE_PREP["technical_questions"]
    assert prep["star_stories"] == SAMPLE_PREP["star_stories"]
    assert prep["talking_points"] == SAMPLE_PREP["talking_points"]


@pytest.mark.asyncio
async def test_get_interview_prep_not_found(db, job_id):
    prep = await db.get_interview_prep(job_id)
    assert prep is None


@pytest.mark.asyncio
async def test_save_interview_prep_upsert(db, job_id):
    await db.save_interview_prep(job_id, SAMPLE_PREP)
    updated = {**SAMPLE_PREP, "talking_points": ["Updated point"]}
    await db.save_interview_prep(job_id, updated)
    prep = await db.get_interview_prep(job_id)
    assert prep["talking_points"] == ["Updated point"]
    assert prep["behavioral_questions"] == SAMPLE_PREP["behavioral_questions"]


@pytest.mark.asyncio
async def test_interview_prep_api(db, job_id):
    """Test the API endpoint returns prep data."""
    await db.save_interview_prep(job_id, SAMPLE_PREP)
    prep = await db.get_interview_prep(job_id)
    assert len(prep["behavioral_questions"]) == 2
    assert len(prep["technical_questions"]) == 2
    assert len(prep["star_stories"]) == 1
    assert len(prep["talking_points"]) == 2
