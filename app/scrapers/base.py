import html as _html
from dataclasses import dataclass, field
from typing import Optional

import httpx


def clean_text(text: str) -> str:
    """Decode HTML entities and fix mojibake in scraped text."""
    if not text:
        return text
    # Decode HTML entities (may be double-encoded, so run twice)
    text = _html.unescape(_html.unescape(text))
    # Fix UTF-8 text decoded as Latin-1/CP1252
    try:
        text = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return text


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    posted_date: Optional[str] = None
    application_method: str = "url"
    contact_email: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.title = clean_text(self.title)
        self.description = clean_text(self.description)
        self.company = clean_text(self.company)
        self.location = clean_text(self.location)


class BaseScraper:
    source_name: str = "base"

    def __init__(self, search_terms: list[str] | None = None, scraper_keys: dict | None = None):
        self.search_terms = search_terms or []
        self.scraper_keys = scraper_keys or {}

    def get_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            },
            timeout=30.0,
            follow_redirects=True,
        )

    async def scrape(self) -> list[JobListing]:
        raise NotImplementedError
