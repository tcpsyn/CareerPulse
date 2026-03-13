import logging
import re

import httpx
from bs4 import BeautifulSoup

from app.circuit_breaker import CircuitBreaker
from app.rate_limiter import get_limiter, get_limiter_for_url

_enrichment_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=300.0)

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    async_playwright = None
    PLAYWRIGHT_AVAILABLE = False

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def extract_linkedin_job_id(url: str) -> str | None:
    """Extract the numeric job ID from a LinkedIn job URL."""
    match = re.search(r"linkedin\.com/jobs/view/(?:.*?[-/])?(\d{8,})", url)
    return match.group(1) if match else None


async def fetch_linkedin_guest_api(job_id: str) -> str | None:
    """Fetch job description from LinkedIn's guest jobs API."""
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    try:
        await get_limiter("www.linkedin.com").acquire()
        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"LinkedIn guest API failed for job {job_id}: {e}")
        return None

    soup = BeautifulSoup(resp.content, "html.parser")
    el = soup.select_one(".description__text, .show-more-less-html__markup")
    if el:
        text = el.get_text(separator="\n", strip=True)
        return text if len(text) > 50 else None
    return None


async def fetch_linkedin_playwright(url: str) -> str | None:
    """Fetch LinkedIn job description using headless browser."""
    if not PLAYWRIGHT_AVAILABLE:
        logger.debug("Playwright not installed, skipping browser fallback")
        return None

    try:
        await get_limiter("www.linkedin.com").acquire()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_selector(
                    ".show-more-less-html__markup, .description__text, .jobs-description__content",
                    timeout=10000,
                )
                el = await page.query_selector(
                    ".show-more-less-html__markup, .description__text, .jobs-description__content"
                )
                if el:
                    text = await el.inner_text()
                    return text.strip() if len(text.strip()) > 50 else None
            finally:
                await browser.close()
    except Exception as e:
        logger.warning(f"Playwright enrichment failed for {url}: {e}")
    return None


async def enrich_job_description(url: str, source: str) -> str | None:
    """Fetch a job detail page and extract the full description text.

    For LinkedIn, tries strategies in order:
    1. Guest jobs API (lightweight, no JS)
    2. Playwright headless browser (if installed)
    3. Direct page fetch (original behavior)
    """
    service = f"enrich:{source}"
    if _enrichment_breaker.is_open(service):
        logger.debug(f"Circuit breaker open for '{service}', skipping enrichment")
        return None

    if source == "linkedin":
        result = await _enrich_linkedin(url)
    else:
        result = await _fetch_and_extract(url, source)

    if result:
        _enrichment_breaker.record_success(service)
    else:
        _enrichment_breaker.record_failure(service)
    return result


async def _enrich_linkedin(url: str) -> str | None:
    """Try multiple strategies to get LinkedIn job description."""
    # Strategy 1: Guest API
    job_id = extract_linkedin_job_id(url)
    if job_id:
        desc = await fetch_linkedin_guest_api(job_id)
        if desc:
            logger.debug(f"LinkedIn enrichment via guest API for job {job_id}")
            return desc

    # Strategy 2: Playwright
    desc = await fetch_linkedin_playwright(url)
    if desc:
        logger.debug(f"LinkedIn enrichment via Playwright for {url}")
        return desc

    # Strategy 3: Direct fetch (original)
    return await _fetch_and_extract(url, "linkedin")


async def _fetch_and_extract(url: str, source: str) -> str | None:
    """Original direct-fetch enrichment logic."""
    try:
        await get_limiter_for_url(url).acquire()
        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Enrichment fetch failed for {url}: {e}")
        return None

    soup = BeautifulSoup(resp.content, "html.parser")
    extractors = {
        "linkedin": _extract_linkedin,
        "dice": _extract_dice,
    }
    extractor = extractors.get(source, _extract_generic)
    return extractor(soup)


def _extract_linkedin(soup: BeautifulSoup) -> str | None:
    el = soup.select_one(".show-more-less-html__markup, .description__text")
    return el.get_text(separator="\n", strip=True) if el else _extract_generic(soup)


def _extract_dice(soup: BeautifulSoup) -> str | None:
    el = soup.select_one('[data-testid="jobDescriptionHtml"], .job-description, #jobDescription')
    if el:
        return el.get_text(separator="\n", strip=True)
    return _extract_generic(soup)


def _extract_generic(soup: BeautifulSoup) -> str | None:
    """Fallback: find the largest text block that looks like a job description."""
    candidates = soup.select("article, main, [class*='description'], [class*='content'], [class*='detail']")
    best = ""
    for el in candidates:
        text = el.get_text(separator="\n", strip=True)
        if len(text) > len(best):
            best = text
    return best if len(best) > 100 else None
