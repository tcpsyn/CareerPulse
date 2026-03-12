from app.scrapers.hackernews import HackerNewsScraper
from app.scrapers.remotive import RemotiveScraper
from app.scrapers.usajobs import USAJobsScraper
from app.scrapers.linkedin import LinkedInScraper
from app.scrapers.dice import DiceScraper
from app.scrapers.arbeitnow import ArbeitnowScraper
from app.scrapers.jobicy import JobicyScraper

ALL_SCRAPERS = [
    HackerNewsScraper, RemotiveScraper, USAJobsScraper,
    LinkedInScraper, DiceScraper,
    ArbeitnowScraper, JobicyScraper,
]
