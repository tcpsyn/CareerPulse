import pytest
from app.scrapers.base import JobListing
from app.scrapers.remoteok import RemoteOKScraper

MOCK_RESPONSE = [
    {"legal": "https://remoteok.com"},
    {
        "id": "123",
        "epoch": "1709312400",
        "position": "Senior DevOps Engineer",
        "company": "TechCorp",
        "location": "Remote",
        "salary_min": 160000,
        "salary_max": 200000,
        "description": "We need a senior devops engineer with AWS and K8s experience.",
        "url": "https://remoteok.com/remote-jobs/123",
        "tags": ["devops", "aws", "kubernetes"],
        "date": "2026-03-01T00:00:00+00:00",
        "apply_url": "https://techcorp.com/apply",
    },
    {
        "id": "124",
        "epoch": "1709312400",
        "position": "Junior Frontend Dev",
        "company": "SmallCo",
        "location": "Remote",
        "description": "Entry level react role",
        "url": "https://remoteok.com/remote-jobs/124",
        "tags": ["react", "frontend"],
        "date": "2026-03-01T00:00:00+00:00",
    },
]


@pytest.mark.asyncio
async def test_remoteok_parse(httpx_mock):
    httpx_mock.add_response(url="https://remoteok.com/api", json=MOCK_RESPONSE)
    scraper = RemoteOKScraper()
    jobs = await scraper.scrape()
    assert len(jobs) == 2
    assert isinstance(jobs[0], JobListing)
    assert jobs[0].title == "Senior DevOps Engineer"
    assert jobs[0].company == "TechCorp"
    assert jobs[0].salary_min == 160000
    assert jobs[0].source == "remoteok"


@pytest.mark.asyncio
async def test_remoteok_handles_empty(httpx_mock):
    httpx_mock.add_response(url="https://remoteok.com/api", json=[{"legal": "ok"}])
    scraper = RemoteOKScraper()
    jobs = await scraper.scrape()
    assert jobs == []


@pytest.mark.asyncio
async def test_remoteok_handles_error(httpx_mock):
    httpx_mock.add_response(url="https://remoteok.com/api", status_code=500)
    scraper = RemoteOKScraper()
    jobs = await scraper.scrape()
    assert jobs == []
