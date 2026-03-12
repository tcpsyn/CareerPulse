import pytest
from app.database import Database, _normalize_company, _title_similarity


def test_normalize_company():
    assert _normalize_company("TechCorp Inc.") == "techcorp"
    assert _normalize_company("TechCorp") == "techcorp"
    assert _normalize_company("  Google LLC ") == "google"
    assert _normalize_company("Acme Corporation") == "acme"
    assert _normalize_company("Smith & Co.") == "smith"


def test_title_similarity():
    assert _title_similarity("Senior DevOps Engineer", "Senior DevOps Engineer") == 1.0
    assert _title_similarity("Senior DevOps Engineer", "DevOps Engineer") >= 0.6
    assert _title_similarity("Backend Engineer", "Frontend Designer") < 0.5


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_find_cross_source_dupes(db):
    id1 = await db.insert_job(
        title="Senior DevOps Engineer", company="TechCorp",
        location="Remote", salary_min=None, salary_max=None,
        description="desc", url="https://linkedin.com/jobs/view/123",
        posted_date=None, application_method="url", contact_email=None,
    )
    id2 = await db.insert_job(
        title="Senior DevOps Engineer", company="TechCorp Inc",
        location="Remote", salary_min=None, salary_max=None,
        description="desc2", url="https://dice.com/job-detail/456",
        posted_date=None, application_method="url", contact_email=None,
    )
    dupes = await db.find_cross_source_dupes(id2, "Senior DevOps Engineer", "TechCorp Inc")
    assert len(dupes) >= 1
    assert dupes[0]["id"] == id1


@pytest.mark.asyncio
async def test_no_false_positive_dedup(db):
    await db.insert_job(
        title="DevOps Engineer", company="Google",
        location="Remote", salary_min=None, salary_max=None,
        description="d", url="https://example.com/1",
        posted_date=None, application_method="url", contact_email=None,
    )
    id2 = await db.insert_job(
        title="Backend Engineer", company="Meta",
        location="Remote", salary_min=None, salary_max=None,
        description="d", url="https://example.com/2",
        posted_date=None, application_method="url", contact_email=None,
    )
    dupes = await db.find_cross_source_dupes(id2, "Backend Engineer", "Meta")
    assert len(dupes) == 0
