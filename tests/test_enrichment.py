import re
from unittest.mock import AsyncMock, patch

import pytest
from app.enrichment import enrich_job_description, extract_linkedin_job_id, fetch_linkedin_guest_api

MOCK_LINKEDIN_DETAIL = """
<html><body>
<div class="show-more-less-html__markup">
  <p>We are looking for a Senior DevOps Engineer to join our team.</p>
  <ul><li>5+ years Kubernetes experience</li><li>AWS certified</li></ul>
</div>
</body></html>
"""

MOCK_DICE_DETAIL = """
<html><body>
<div data-testid="jobDescriptionHtml">
  <p>Platform Engineer needed for cloud-native infrastructure.</p>
  <p>Requirements: Terraform, Kubernetes, CI/CD pipelines.</p>
</div>
</body></html>
"""


@pytest.mark.asyncio
async def test_enrich_linkedin(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://www\.linkedin\.com/jobs/view/.*"),
        text=MOCK_LINKEDIN_DETAIL,
    )
    result = await enrich_job_description("https://www.linkedin.com/jobs/view/test-123", "linkedin")
    assert "Senior DevOps Engineer" in result
    assert "Kubernetes" in result


@pytest.mark.asyncio
async def test_enrich_dice(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://www\.dice\.com/job-detail/.*"),
        text=MOCK_DICE_DETAIL,
    )
    result = await enrich_job_description("https://www.dice.com/job-detail/abc-123", "dice")
    assert "Platform Engineer" in result
    assert "Terraform" in result


@pytest.mark.asyncio
async def test_enrich_handles_http_error(httpx_mock):
    httpx_mock.add_response(url=re.compile(r"https://example\.com/.*"), status_code=404)
    result = await enrich_job_description("https://example.com/job", "unknown")
    assert result is None


@pytest.mark.asyncio
async def test_enrich_generic_fallback(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://example\.com/.*"),
        text="<html><body><main><p>" + "Job details here. " * 20 + "</p></main></body></html>",
    )
    result = await enrich_job_description("https://example.com/job", "unknown")
    assert result is not None
    assert "Job details here" in result


# Database integration tests

from app.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_get_jobs_needing_enrichment(db):
    job_id = await db.insert_job(
        title="Short Desc Job", company="Co", location="Remote",
        salary_min=None, salary_max=None, description="tiny",
        url="https://example.com/1", posted_date=None,
        application_method="url", contact_email=None,
    )
    await db.insert_source(job_id, "linkedin", "https://example.com/1")
    jobs = await db.get_jobs_needing_enrichment()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id


@pytest.mark.asyncio
async def test_update_job_description(db):
    job_id = await db.insert_job(
        title="Test", company="Co", location="Remote",
        salary_min=None, salary_max=None, description="short",
        url="https://example.com/2", posted_date=None,
        application_method="url", contact_email=None,
    )
    await db.insert_source(job_id, "test", "https://example.com/2")
    await db.update_job_description(job_id, "Full detailed description " * 20)
    jobs = await db.get_jobs_needing_enrichment()
    assert all(j["id"] != job_id for j in jobs)


# LinkedIn job ID extraction and guest API tests


def test_extract_job_id_from_standard_url():
    url = "https://www.linkedin.com/jobs/view/4567890123"
    assert extract_linkedin_job_id(url) == "4567890123"


def test_extract_job_id_from_url_with_slug():
    url = "https://www.linkedin.com/jobs/view/senior-engineer-at-acme-4567890123"
    assert extract_linkedin_job_id(url) == "4567890123"


def test_extract_job_id_returns_none_for_non_linkedin():
    assert extract_linkedin_job_id("https://dice.com/job/123") is None


MOCK_GUEST_API_RESPONSE = """
<html><body>
<div class="description__text">
  <p>We need a Platform Engineer with strong Kubernetes skills.</p>
  <p>Requirements: 5+ years infrastructure experience, Terraform, AWS.</p>
</div>
</body></html>
"""


@pytest.mark.asyncio
async def test_fetch_linkedin_guest_api_success(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://www\.linkedin\.com/jobs-guest/jobs/api/jobPosting/.*"),
        text=MOCK_GUEST_API_RESPONSE,
    )
    result = await fetch_linkedin_guest_api("4567890123")
    assert result is not None
    assert "Platform Engineer" in result
    assert "Kubernetes" in result


@pytest.mark.asyncio
async def test_fetch_linkedin_guest_api_returns_none_on_error(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://www\.linkedin\.com/jobs-guest/jobs/api/jobPosting/.*"),
        status_code=429,
    )
    result = await fetch_linkedin_guest_api("4567890123")
    assert result is None


# Playwright fallback tests


@pytest.mark.asyncio
async def test_fetch_linkedin_playwright_success():
    """Test Playwright fetcher with mocked browser."""
    from app.enrichment import fetch_linkedin_playwright

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.query_selector = AsyncMock()

    mock_element = AsyncMock()
    mock_element.inner_text = AsyncMock(return_value="Full job description from Playwright with enough content to pass the length check easily")
    mock_page.query_selector.return_value = mock_element

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.__aenter__ = AsyncMock(return_value=mock_context)
    mock_context.__aexit__ = AsyncMock(return_value=False)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_pw_instance = AsyncMock()
    mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw = AsyncMock()
    mock_pw.__aenter__ = AsyncMock(return_value=mock_pw_instance)
    mock_pw.__aexit__ = AsyncMock(return_value=False)

    with patch("app.enrichment.async_playwright", return_value=mock_pw):
        result = await fetch_linkedin_playwright("https://www.linkedin.com/jobs/view/123456789")

    assert result is not None
    assert "Full job description" in result


@pytest.mark.asyncio
async def test_fetch_linkedin_playwright_not_installed():
    """Returns None when playwright is not installed."""
    from app.enrichment import fetch_linkedin_playwright

    with patch("app.enrichment.PLAYWRIGHT_AVAILABLE", False):
        result = await fetch_linkedin_playwright("https://www.linkedin.com/jobs/view/123456789")
    assert result is None
