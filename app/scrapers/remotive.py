import logging

from app.scrapers.base import BaseScraper, JobListing

logger = logging.getLogger(__name__)

API_URL = "https://remotive.com/api/remote-jobs"
CATEGORIES = ["devops", "software-dev"]


class RemotiveScraper(BaseScraper):
    source_name = "remotive"

    async def scrape(self) -> list[JobListing]:
        jobs = []
        async with self.get_client() as client:
            for category in CATEGORIES:
                try:
                    resp = await client.get(API_URL, params={"category": category, "limit": 50})
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.error(f"Remotive scrape failed for {category}: {e}")
                    continue

                for item in data.get("jobs", []):
                    jobs.append(
                        JobListing(
                            title=item.get("title", ""),
                            company=item.get("company_name", ""),
                            location=item.get("candidate_required_location", "Remote"),
                            description=item.get("description", ""),
                            url=item.get("url", ""),
                            source=self.source_name,
                            salary_min=item.get("salary_min"),
                            salary_max=item.get("salary_max"),
                            posted_date=item.get("publication_date", None),
                            tags=item.get("tags", []),
                        )
                    )
        return jobs
