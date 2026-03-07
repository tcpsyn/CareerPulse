import re

import pytest
from app.scrapers.base import JobListing
from app.scrapers.linkedin import LinkedInScraper

MOCK_GOOGLE_HTML = """
<html>
<body>
  <div class="g">
    <a href="https://www.linkedin.com/jobs/view/senior-devops-engineer-12345">
      <h3>Senior DevOps Engineer - TechCorp | LinkedIn</h3>
    </a>
    <div class="VwiC3b">Remote position requiring AWS and Terraform experience.</div>
  </div>
  <div class="g">
    <a href="https://www.linkedin.com/jobs/view/sre-67890">
      <h3>Site Reliability Engineer - CloudInc | LinkedIn</h3>
    </a>
    <div class="VwiC3b">SRE role with Kubernetes and observability focus.</div>
  </div>
  <div class="g">
    <a href="https://www.example.com/not-linkedin">
      <h3>Some Other Result</h3>
    </a>
    <div class="VwiC3b">Not a LinkedIn job.</div>
  </div>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_linkedin_parse(httpx_mock, monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    httpx_mock.add_response(
        url=re.compile(r"https://www\.google\.com/search\?.*"),
        text=MOCK_GOOGLE_HTML,
    )
    scraper = LinkedInScraper()
    jobs = await scraper.scrape()
    assert len(jobs) == 2
    assert isinstance(jobs[0], JobListing)
    assert "Senior DevOps Engineer" in jobs[0].title
    assert "linkedin.com/jobs" in jobs[0].url
    assert jobs[0].source == "linkedin"


@pytest.mark.asyncio
async def test_linkedin_handles_empty(httpx_mock, monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    httpx_mock.add_response(
        url=re.compile(r"https://www\.google\.com/search\?.*"),
        text="<html><body></body></html>",
    )
    scraper = LinkedInScraper()
    jobs = await scraper.scrape()
    assert jobs == []


@pytest.mark.asyncio
async def test_linkedin_handles_error(httpx_mock, monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    httpx_mock.add_response(
        url=re.compile(r"https://www\.google\.com/search\?.*"),
        status_code=429,
    )
    scraper = LinkedInScraper()
    jobs = await scraper.scrape()
    assert jobs == []
