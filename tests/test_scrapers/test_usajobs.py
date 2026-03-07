import re

import pytest
from app.scrapers.base import JobListing
from app.scrapers.usajobs import USAJobsScraper

MOCK_RESPONSE = {
    "SearchResult": {
        "SearchResultCount": 2,
        "SearchResultItems": [
            {
                "MatchedObjectDescriptor": {
                    "PositionTitle": "IT Specialist (SYSADMIN)",
                    "OrganizationName": "Department of Defense",
                    "PositionURI": "https://www.usajobs.gov/job/123456",
                    "PositionLocation": [
                        {"LocationName": "Anywhere in the U.S. (remote job)"}
                    ],
                    "PositionRemuneration": [
                        {"MinimumRange": "100000", "MaximumRange": "140000", "RateIntervalCode": "PA"}
                    ],
                    "PublicationStartDate": "2026-03-01",
                    "UserArea": {
                        "Details": {
                            "MajorDuties": ["Manage IT infrastructure and cloud services."]
                        }
                    },
                }
            },
            {
                "MatchedObjectDescriptor": {
                    "PositionTitle": "Supervisory IT Specialist",
                    "OrganizationName": "Department of Veterans Affairs",
                    "PositionURI": "https://www.usajobs.gov/job/789012",
                    "PositionLocation": [
                        {"LocationName": "Washington, DC"}
                    ],
                    "PositionRemuneration": [
                        {"MinimumRange": "120000", "MaximumRange": "160000", "RateIntervalCode": "PA"}
                    ],
                    "PublicationStartDate": "2026-02-28",
                    "UserArea": {
                        "Details": {
                            "MajorDuties": ["Lead a team of IT specialists."]
                        }
                    },
                }
            },
        ],
    }
}


@pytest.mark.asyncio
async def test_usajobs_parse(httpx_mock, monkeypatch):
    monkeypatch.setenv("USAJOBS_API_KEY", "test-key")
    monkeypatch.setenv("USAJOBS_EMAIL", "test@example.com")
    httpx_mock.add_response(
        url=re.compile(r"https://data\.usajobs\.gov/api/search\?.*"),
        json=MOCK_RESPONSE,
    )
    scraper = USAJobsScraper()
    jobs = await scraper.scrape()
    assert len(jobs) == 2
    assert isinstance(jobs[0], JobListing)
    assert jobs[0].title == "IT Specialist (SYSADMIN)"
    assert jobs[0].company == "Department of Defense"
    assert jobs[0].salary_min == 100000
    assert jobs[0].source == "usajobs"


@pytest.mark.asyncio
async def test_usajobs_no_api_key(httpx_mock):
    scraper = USAJobsScraper()
    jobs = await scraper.scrape()
    assert jobs == []


@pytest.mark.asyncio
async def test_usajobs_handles_error(httpx_mock, monkeypatch):
    monkeypatch.setenv("USAJOBS_API_KEY", "test-key")
    monkeypatch.setenv("USAJOBS_EMAIL", "test@example.com")
    httpx_mock.add_response(
        url=re.compile(r"https://data\.usajobs\.gov/api/search\?.*"),
        status_code=500,
    )
    scraper = USAJobsScraper()
    jobs = await scraper.scrape()
    assert jobs == []
