import asyncio
import json
import logging
import re

logger = logging.getLogger(__name__)

# Known non-US countries and cities (lowercase)
_NON_US_COUNTRIES = {
    "india": "India", "bengaluru": "India", "bangalore": "India", "mumbai": "India",
    "hyderabad": "India", "pune": "India", "chennai": "India", "delhi": "India",
    "new delhi": "India", "noida": "India", "gurgaon": "India", "gurugram": "India",
    "kolkata": "India", "ahmedabad": "India",
    "united kingdom": "UK", "uk": "UK", "london": "UK", "manchester": "UK",
    "edinburgh": "UK", "bristol": "UK", "cambridge": "UK", "oxford": "UK",
    "england": "UK", "scotland": "UK", "wales": "UK",
    "germany": "Germany", "berlin": "Germany", "munich": "Germany", "frankfurt": "Germany",
    "hamburg": "Germany",
    "france": "France", "paris": "France", "lyon": "France",
    "netherlands": "Netherlands", "amsterdam": "Netherlands",
    "ireland": "Ireland", "dublin": "Ireland",
    "canada": "Canada", "toronto": "Canada", "vancouver": "Canada", "montreal": "Canada",
    "ottawa": "Canada", "calgary": "Canada",
    "australia": "Australia", "sydney": "Australia", "melbourne": "Australia",
    "singapore": "Singapore",
    "japan": "Japan", "tokyo": "Japan",
    "china": "China", "beijing": "China", "shanghai": "China", "shenzhen": "China",
    "brazil": "Brazil", "sao paulo": "Brazil", "são paulo": "Brazil",
    "israel": "Israel", "tel aviv": "Israel",
    "spain": "Spain", "madrid": "Spain", "barcelona": "Spain",
    "italy": "Italy", "milan": "Italy", "rome": "Italy",
    "sweden": "Sweden", "stockholm": "Sweden",
    "switzerland": "Switzerland", "zurich": "Switzerland", "zürich": "Switzerland",
    "poland": "Poland", "warsaw": "Poland", "krakow": "Poland", "kraków": "Poland",
    "portugal": "Portugal", "lisbon": "Portugal",
    "czech republic": "Czech Republic", "czechia": "Czech Republic", "prague": "Czech Republic",
    "romania": "Romania", "bucharest": "Romania",
    "philippines": "Philippines", "manila": "Philippines",
    "mexico": "Mexico", "mexico city": "Mexico",
    "south korea": "South Korea", "seoul": "South Korea",
    "argentina": "Argentina", "buenos aires": "Argentina",
    "colombia": "Colombia", "bogota": "Colombia", "bogotá": "Colombia",
    "costa rica": "Costa Rica",
    "ukraine": "Ukraine", "kyiv": "Ukraine",
    "vietnam": "Vietnam", "ho chi minh": "Vietnam",
    "thailand": "Thailand", "bangkok": "Thailand",
    "indonesia": "Indonesia", "jakarta": "Indonesia",
    "malaysia": "Malaysia", "kuala lumpur": "Malaysia",
    "nigeria": "Nigeria", "lagos": "Nigeria",
    "south africa": "South Africa", "cape town": "South Africa", "johannesburg": "South Africa",
    "kenya": "Kenya", "nairobi": "Kenya",
    "egypt": "Egypt", "cairo": "Egypt",
    "pakistan": "Pakistan", "karachi": "Pakistan", "lahore": "Pakistan",
    "bangladesh": "Bangladesh", "dhaka": "Bangladesh",
    "austria": "Austria", "vienna": "Austria",
    "belgium": "Belgium", "brussels": "Belgium",
    "denmark": "Denmark", "copenhagen": "Denmark",
    "finland": "Finland", "helsinki": "Finland",
    "norway": "Norway", "oslo": "Norway",
    "new zealand": "New Zealand", "auckland": "New Zealand",
    "taiwan": "Taiwan", "taipei": "Taiwan",
}

# Canadian provinces (to avoid false US matches)
_CANADIAN_PROVINCES = {
    "ab", "bc", "mb", "nb", "nl", "ns", "nt", "nu", "on", "pe", "qc", "sk", "yt",
    "alberta", "british columbia", "manitoba", "new brunswick", "newfoundland",
    "nova scotia", "northwest territories", "nunavut", "ontario",
    "prince edward island", "quebec", "saskatchewan", "yukon",
}

_REMOTE_KEYWORDS = {
    "remote", "anywhere", "global", "distributed", "work from home", "wfh",
    "fully remote", "100% remote", "remote-first", "worldwide",
}

_ONSITE_KEYWORDS = {"on-site", "onsite", "on site", "in-office", "in office", "office-based"}
_HYBRID_KEYWORDS = {"hybrid"}

# US state abbreviations (from database.py _US_STATES)
from app.database import _US_STATES

_US_ABBREVS = set(_US_STATES.values())
_US_STATE_NAMES = set(_US_STATES.keys())

# Patterns for US locations: "City, ST" or "City, State"
_US_CITY_STATE_ABBREV = re.compile(
    r'(?:^|[,\-/\s])(' + '|'.join(re.escape(a.upper()) for a in sorted(_US_ABBREVS, key=len, reverse=True)) + r')(?:\s|$|[,\-/)])',
    re.IGNORECASE,
)
_US_COUNTRY_PATTERNS = re.compile(
    r'\b(?:united\s+states|usa|u\.s\.a\.?|u\.s\.?)\b|(?:^|\s)us(?:\s|$)', re.IGNORECASE
)


def classify_location_rule_based(location: str) -> str | None:
    """Classify a job location string. Returns region string or None if ambiguous.

    Returns:
        "US" — US location
        "Remote" — remote/global
        country name — non-US country
        None — ambiguous, needs LLM
    """
    if not location or not location.strip():
        return "Remote"

    loc = location.strip()
    loc_lower = loc.lower()

    # Check remote keywords first
    for kw in _REMOTE_KEYWORDS:
        if kw in loc_lower:
            # "Remote - India" or "Remote, UK" → check if non-US qualifier
            rest = loc_lower.replace(kw, "").strip(" -,/()[]|")
            if rest:
                # Check if the rest is a non-US country/city
                for pattern, country in _NON_US_COUNTRIES.items():
                    if pattern in rest:
                        return country
                # "Remote - US" or "Remote, USA"
                if _US_COUNTRY_PATTERNS.search(rest):
                    return "US"
                # Check for US state abbreviations in rest
                for abbr in _US_ABBREVS:
                    if re.search(r'\b' + re.escape(abbr) + r'\b', rest, re.IGNORECASE):
                        return "US"
            return "Remote"

    # Check explicit US country patterns
    if _US_COUNTRY_PATTERNS.search(loc_lower):
        return "US"

    # Check non-US countries/cities (full match or contained)
    # First check full location against known entries
    for pattern, country in _NON_US_COUNTRIES.items():
        if pattern == loc_lower:
            return country
        # Check as part of comma/dash-separated location
        parts = [p.strip() for p in re.split(r'[,\-/]', loc_lower)]
        for part in parts:
            if part == pattern:
                return country

    # Check for Canadian provinces before US state matching
    parts = [p.strip() for p in re.split(r'[,\-/\s]+', loc_lower)]
    for part in parts:
        if part in _CANADIAN_PROVINCES:
            return "Canada"

    # Check US state abbreviations (", CA" or "- CA" patterns)
    if _US_CITY_STATE_ABBREV.search(loc):
        return "US"

    # Check full US state names
    for state_name in _US_STATE_NAMES:
        if state_name in loc_lower:
            # "Georgia" alone is ambiguous — needs context
            if state_name == "georgia" and loc_lower.strip() == "georgia":
                return None  # Ambiguous
            # "Atlanta, Georgia" or "Georgia, US" → US
            parts = [p.strip() for p in re.split(r'[,\-/]', loc_lower)]
            for part in parts:
                if part == state_name:
                    return "US"

    # Common US city patterns (cities that are unambiguously US)
    us_cities = {
        "new york", "nyc", "los angeles", "san francisco", "chicago",
        "seattle", "austin", "boston", "denver", "portland",
        "san diego", "san jose", "atlanta", "dallas", "houston",
        "phoenix", "philadelphia", "washington dc", "washington, dc",
        "miami", "minneapolis", "raleigh", "detroit", "pittsburgh",
        "charlotte", "nashville", "salt lake city", "las vegas",
        "san antonio", "indianapolis", "columbus", "jacksonville",
    }
    for city in us_cities:
        if city in loc_lower:
            return "US"

    # Nothing matched — ambiguous
    return None


def classify_work_type(location: str, title: str = "") -> str | None:
    """Classify work type from location and title strings.

    Returns:
        "remote" — remote job
        "onsite" — on-site/in-office job
        "hybrid" — hybrid job
        None — ambiguous, no clear signal
    """
    combined = f"{location or ''} {title or ''}".lower()

    has_remote = any(kw in combined for kw in _REMOTE_KEYWORDS)
    has_hybrid = any(kw in combined for kw in _HYBRID_KEYWORDS)
    has_onsite = any(kw in combined for kw in _ONSITE_KEYWORDS)

    # Hybrid takes priority (e.g. "remote/hybrid" = hybrid)
    if has_hybrid:
        return "hybrid"
    if has_onsite:
        return "onsite"
    if has_remote:
        return "remote"
    return None


async def classify_locations_llm(ai_client, locations: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Use LLM to classify ambiguous location strings in batch.

    Args:
        ai_client: AIClient instance
        locations: list of (job_id, location_string) tuples

    Returns:
        list of (job_id, region) tuples
    """
    if not locations:
        return []

    results = []
    # Process in batches of 50
    for i in range(0, len(locations), 50):
        batch = locations[i:i + 50]
        location_list = "\n".join(
            f'{idx}. "{loc}"' for idx, (_, loc) in enumerate(batch)
        )

        prompt = f"""Classify each job location into a region. Respond with ONLY a JSON array.

For each location, determine if it is:
- "US" — in the United States
- "Remote" — remote/global/no specific location
- The country name (e.g. "India", "UK", "Germany") — if outside the US

Locations:
{location_list}

Respond with a JSON array like: [{{"index": 0, "region": "US"}}, {{"index": 1, "region": "India"}}]
JSON only, no other text:"""

        try:
            from app.ai_client import parse_json_response
            raw = await ai_client.chat(prompt, max_tokens=1024, timeout=30.0)
            parsed = parse_json_response(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    idx = item.get("index")
                    region = item.get("region", "Unknown")
                    if idx is not None and 0 <= idx < len(batch):
                        job_id = batch[idx][0]
                        results.append((job_id, region))
                # Mark any missing indices as Unknown
                classified_indices = {item.get("index") for item in parsed}
                for idx, (job_id, _) in enumerate(batch):
                    if idx not in classified_indices:
                        results.append((job_id, "Unknown"))
            else:
                # Unexpected format — mark all as Unknown
                for job_id, _ in batch:
                    results.append((job_id, "Unknown"))
        except Exception as e:
            logger.warning(f"LLM location classification failed: {e}")
            for job_id, _ in batch:
                results.append((job_id, "Unknown"))

        await asyncio.sleep(0)  # Yield between batches

    return results
