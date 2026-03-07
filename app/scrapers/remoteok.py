import logging

from app.scrapers.base import BaseScraper, JobListing

logger = logging.getLogger(__name__)


class RemoteOKScraper(BaseScraper):
    source_name = "remoteok"
    API_URL = "https://remoteok.com/api"

    async def scrape(self) -> list[JobListing]:
        try:
            async with self.get_client() as client:
                resp = await client.get(self.API_URL)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"RemoteOK scrape failed: {e}")
            return []

        jobs = []
        for item in data:
            if "position" not in item:
                continue
            jobs.append(
                JobListing(
                    title=item.get("position", ""),
                    company=item.get("company", ""),
                    location=item.get("location", "Remote"),
                    description=item.get("description", ""),
                    url=item.get("url", ""),
                    source=self.source_name,
                    salary_min=item.get("salary_min"),
                    salary_max=item.get("salary_max"),
                    posted_date=item.get("date"),
                    tags=item.get("tags", []),
                )
            )
        return jobs
