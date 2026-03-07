import logging
import os
import random
import asyncio
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, JobListing

logger = logging.getLogger(__name__)

SEARCH_QUERY = 'site:linkedin.com/jobs "senior devops" OR "SRE" OR "infrastructure engineer" remote'


class LinkedInScraper(BaseScraper):
    source_name = "linkedin"

    async def scrape(self) -> list[JobListing]:
        is_test = os.environ.get("TESTING", "")
        encoded = quote_plus(SEARCH_QUERY)
        url = f"https://www.google.com/search?q={encoded}&num=20"

        try:
            async with self.get_client() as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
        except Exception as e:
            logger.error(f"LinkedIn/Google scrape failed: {e}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        jobs = []

        for result in soup.select("div.g"):
            link_el = result.select_one("a[href]")
            if not link_el:
                continue

            href = link_el.get("href", "")
            if "linkedin.com/jobs" not in href:
                continue

            title_el = result.select_one("h3")
            title = title_el.get_text(strip=True) if title_el else ""

            snippet_el = result.select_one("div.VwiC3b")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            jobs.append(
                JobListing(
                    title=title,
                    company="",
                    location="Remote",
                    description=snippet,
                    url=href,
                    source=self.source_name,
                )
            )

        if not is_test and jobs:
            delay = random.uniform(30, 90)
            logger.info(f"LinkedIn scraper sleeping {delay:.0f}s to avoid rate limiting")
            await asyncio.sleep(delay)

        return jobs
