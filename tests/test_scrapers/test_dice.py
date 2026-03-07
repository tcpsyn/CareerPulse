import re

import pytest
from app.scrapers.base import JobListing
from app.scrapers.dice import DiceScraper

MOCK_GOOGLE_HTML = """
<html>
<body>
  <div class="g">
    <a href="https://www.dice.com/job-detail/devops-engineer-abc123">
      <h3>DevOps Engineer - Remote | Dice.com</h3>
    </a>
    <div class="VwiC3b">DevOps role with CI/CD and cloud experience.</div>
  </div>
  <div class="g">
    <a href="https://www.dice.com/job-detail/sre-def456">
      <h3>SRE Engineer - Fully Remote | Dice.com</h3>
    </a>
    <div class="VwiC3b">Site reliability engineering position.</div>
  </div>
  <div class="g">
    <a href="https://www.example.com/not-dice">
      <h3>Unrelated Result</h3>
    </a>
    <div class="VwiC3b">Not a Dice job.</div>
  </div>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_dice_parse(httpx_mock, monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    httpx_mock.add_response(
        url=re.compile(r"https://www\.google\.com/search\?.*"),
        text=MOCK_GOOGLE_HTML,
    )
    scraper = DiceScraper()
    jobs = await scraper.scrape()
    assert len(jobs) == 2
    assert isinstance(jobs[0], JobListing)
    assert "DevOps Engineer" in jobs[0].title
    assert "dice.com/job-detail" in jobs[0].url
    assert jobs[0].source == "dice"


@pytest.mark.asyncio
async def test_dice_handles_empty(httpx_mock, monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    httpx_mock.add_response(
        url=re.compile(r"https://www\.google\.com/search\?.*"),
        text="<html><body></body></html>",
    )
    scraper = DiceScraper()
    jobs = await scraper.scrape()
    assert jobs == []


@pytest.mark.asyncio
async def test_dice_handles_error(httpx_mock, monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    httpx_mock.add_response(
        url=re.compile(r"https://www\.google\.com/search\?.*"),
        status_code=429,
    )
    scraper = DiceScraper()
    jobs = await scraper.scrape()
    assert jobs == []
