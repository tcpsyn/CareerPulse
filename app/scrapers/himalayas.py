import logging

from app.scrapers.base import BaseScraper, JobListing

logger = logging.getLogger(__name__)

API_URL = "https://himalayas.app/jobs/api"
MAX_PAGES = 3
PAGE_SIZE = 20


class HimalayasScraper(BaseScraper):
    source_name = "himalayas"

    async def scrape(self) -> list[JobListing]:
        jobs = []
        async with self.get_client() as client:
            for page in range(MAX_PAGES):
                try:
                    resp = await client.get(
                        API_URL, params={"limit": PAGE_SIZE, "offset": page * PAGE_SIZE}
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.error(f"Himalayas scrape failed page {page}: {e}")
                    break

                listings = data.get("jobs", [])
                if not listings:
                    break

                for item in listings:
                    title = item.get("title", "")
                    description = item.get("description", "")
                    categories = item.get("categories", [])
                    searchable = f"{title} {description} {' '.join(categories)}".lower()

                    if self.search_terms and not any(
                        term.lower() in searchable for term in self.search_terms
                    ):
                        continue

                    location_restrictions = item.get("locationRestrictions", [])
                    location = ", ".join(location_restrictions) if location_restrictions else "Remote"

                    jobs.append(
                        JobListing(
                            title=title,
                            company=item.get("companyName", ""),
                            location=location,
                            description=description,
                            url=item.get("applicationLink", ""),
                            source=self.source_name,
                            salary_min=item.get("minSalary"),
                            salary_max=item.get("maxSalary"),
                            posted_date=item.get("pubDate", None),
                            tags=categories,
                        )
                    )
        return jobs
