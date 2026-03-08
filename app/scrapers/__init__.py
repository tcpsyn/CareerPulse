from app.scrapers.indeed import IndeedScraper
from app.scrapers.weworkremotely import WeWorkRemotelyScraper
from app.scrapers.hackernews import HackerNewsScraper
from app.scrapers.remotive import RemotiveScraper
from app.scrapers.usajobs import USAJobsScraper
from app.scrapers.linkedin import LinkedInScraper
from app.scrapers.dice import DiceScraper

ALL_SCRAPERS = [
    IndeedScraper, WeWorkRemotelyScraper,
    HackerNewsScraper, RemotiveScraper, USAJobsScraper,
    LinkedInScraper, DiceScraper,
]
