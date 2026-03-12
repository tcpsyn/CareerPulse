import re

import pytest
from app.scrapers.base import JobListing
from app.scrapers.himalayas import HimalayasScraper

MOCK_RESPONSE = {
    "jobs": [
        {
            "title": "Platform Engineer",
            "companyName": "InfraCo",
            "description": "Build and maintain cloud platform.",
            "applicationLink": "https://infraco.com/apply",
            "minSalary": 130000,
            "maxSalary": 170000,
            "categories": ["devops", "infrastructure"],
            "pubDate": "2026-03-01",
            "locationRestrictions": ["US", "Canada"],
        },
        {
            "title": "Data Scientist",
            "companyName": "DataCo",
            "description": "Analyze large datasets.",
            "applicationLink": "https://dataco.com/apply",
            "categories": ["data", "machine-learning"],
            "pubDate": "2026-02-28",
            "locationRestrictions": [],
        },
    ]
}


@pytest.mark.asyncio
async def test_himalayas_parse(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://himalayas\.app/jobs/api\?.*"), json=MOCK_RESPONSE
    )
    httpx_mock.add_response(
        url=re.compile(r"https://himalayas\.app/jobs/api\?.*"), json={"jobs": []}
    )
    scraper = HimalayasScraper()
    jobs = await scraper.scrape()
    assert len(jobs) == 2
    assert isinstance(jobs[0], JobListing)
    assert jobs[0].title == "Platform Engineer"
    assert jobs[0].company == "InfraCo"
    assert jobs[0].source == "himalayas"
    assert jobs[0].salary_min == 130000
    assert jobs[0].location == "US, Canada"
    # Empty locationRestrictions defaults to Remote
    assert jobs[1].location == "Remote"


@pytest.mark.asyncio
async def test_himalayas_search_terms_filter(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://himalayas\.app/jobs/api\?.*"), json=MOCK_RESPONSE
    )
    httpx_mock.add_response(
        url=re.compile(r"https://himalayas\.app/jobs/api\?.*"), json={"jobs": []}
    )
    scraper = HimalayasScraper(search_terms=["devops"])
    jobs = await scraper.scrape()
    assert len(jobs) == 1
    assert jobs[0].title == "Platform Engineer"


@pytest.mark.asyncio
async def test_himalayas_handles_empty(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://himalayas\.app/jobs/api\?.*"), json={"jobs": []}
    )
    scraper = HimalayasScraper()
    jobs = await scraper.scrape()
    assert jobs == []


@pytest.mark.asyncio
async def test_himalayas_handles_error(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://himalayas\.app/jobs/api\?.*"), status_code=500
    )
    scraper = HimalayasScraper()
    jobs = await scraper.scrape()
    assert jobs == []
