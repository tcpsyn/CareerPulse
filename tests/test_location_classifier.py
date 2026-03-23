import pytest
from unittest.mock import AsyncMock, MagicMock

from app.location_classifier import classify_location_rule_based, classify_locations_llm, classify_work_type


class TestRuleBased:
    """Test classify_location_rule_based."""

    # Empty / None → Remote
    @pytest.mark.parametrize("loc", [None, "", "  "])
    def test_empty_returns_remote(self, loc):
        assert classify_location_rule_based(loc) == "Remote"

    # Remote keywords
    @pytest.mark.parametrize("loc", [
        "Remote", "remote", "Anywhere", "Global", "Distributed",
        "Work from home", "Fully Remote", "100% Remote", "Remote-First",
        "Worldwide", "WFH",
    ])
    def test_remote_keywords(self, loc):
        assert classify_location_rule_based(loc) == "Remote"

    # Remote with US qualifier
    @pytest.mark.parametrize("loc", [
        "Remote - US", "Remote, USA", "Remote (United States)",
        "Remote - CA", "Remote, NY",
    ])
    def test_remote_us(self, loc):
        assert classify_location_rule_based(loc) == "US"

    # Remote with non-US qualifier
    @pytest.mark.parametrize("loc,expected", [
        ("Remote - India", "India"),
        ("Remote, UK", "UK"),
        ("Remote - London", "UK"),
        ("Remote, Germany", "Germany"),
    ])
    def test_remote_non_us(self, loc, expected):
        assert classify_location_rule_based(loc) == expected

    # US state abbreviations
    @pytest.mark.parametrize("loc", [
        "San Francisco, CA", "New York, NY", "Austin, TX",
        "Seattle, WA", "Denver, CO", "Chicago, IL",
        "Portland, OR", "Boston, MA",
    ])
    def test_us_state_abbrevs(self, loc):
        assert classify_location_rule_based(loc) == "US"

    # US full state names
    @pytest.mark.parametrize("loc", [
        "California", "Austin, Texas", "Portland, Oregon",
    ])
    def test_us_state_names(self, loc):
        assert classify_location_rule_based(loc) == "US"

    # US country patterns
    @pytest.mark.parametrize("loc", [
        "United States", "USA", "U.S.", "U.S.A.",
    ])
    def test_us_country_patterns(self, loc):
        assert classify_location_rule_based(loc) == "US"

    # US cities
    @pytest.mark.parametrize("loc", [
        "New York", "NYC", "Los Angeles", "San Francisco",
        "Chicago", "Seattle", "Austin", "Boston", "Denver",
        "San Diego", "Atlanta", "Dallas", "Houston", "Phoenix",
        "Miami", "Nashville",
    ])
    def test_us_cities(self, loc):
        assert classify_location_rule_based(loc) == "US"

    # Non-US countries/cities
    @pytest.mark.parametrize("loc,expected", [
        ("Bengaluru, India", "India"),
        ("London, UK", "UK"),
        ("Berlin, Germany", "Germany"),
        ("Toronto, Canada", "Canada"),
        ("Singapore", "Singapore"),
        ("Tokyo, Japan", "Japan"),
        ("Sydney, Australia", "Australia"),
        ("Dublin, Ireland", "Ireland"),
        ("Amsterdam, Netherlands", "Netherlands"),
        ("Paris, France", "France"),
        ("Mumbai", "India"),
        ("Hyderabad", "India"),
        ("Pune, India", "India"),
    ])
    def test_non_us_locations(self, loc, expected):
        assert classify_location_rule_based(loc) == expected

    # Ambiguous → None
    def test_bare_georgia_is_ambiguous(self):
        assert classify_location_rule_based("Georgia") is None

    # Georgia with context → US
    def test_georgia_with_city_is_us(self):
        assert classify_location_rule_based("Atlanta, Georgia") == "US"
        assert classify_location_rule_based("Atlanta, GA") == "US"

    # Canadian provinces
    @pytest.mark.parametrize("loc", [
        "Toronto, ON", "Vancouver, BC", "Montreal, QC",
    ])
    def test_canadian_provinces(self, loc):
        assert classify_location_rule_based(loc) == "Canada"

    # "on-site" should NOT match Ontario
    @pytest.mark.parametrize("loc,expected", [
        ("Memphis, TN (on-site)", "US"),
        ("Austin, TX on-site", "US"),
        ("San Francisco, CA (on site)", "US"),
    ])
    def test_onsite_not_misclassified_as_canada(self, loc, expected):
        assert classify_location_rule_based(loc) == expected


class TestLLMClassifier:
    """Test classify_locations_llm."""

    @pytest.mark.asyncio
    async def test_llm_batch_success(self):
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value='[{"index": 0, "region": "US"}, {"index": 1, "region": "India"}]')
        locations = [(1, "Some Place, USA"), (2, "Somewhere, India")]
        result = await classify_locations_llm(mock_client, locations)
        assert len(result) == 2
        regions = {job_id: region for job_id, region in result}
        assert regions[1] == "US"
        assert regions[2] == "India"

    @pytest.mark.asyncio
    async def test_llm_failure_returns_unknown(self):
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(side_effect=Exception("API error"))
        locations = [(1, "Ambiguous Place")]
        result = await classify_locations_llm(mock_client, locations)
        assert len(result) == 1
        assert result[0] == (1, "Unknown")

    @pytest.mark.asyncio
    async def test_empty_locations(self):
        mock_client = MagicMock()
        result = await classify_locations_llm(mock_client, [])
        assert result == []


class TestClassifyWorkType:
    """Test classify_work_type."""

    # Remote signals from location
    @pytest.mark.parametrize("location,expected", [
        ("Remote", "remote"),
        ("Fully Remote", "remote"),
        ("Work from home", "remote"),
        ("Anywhere", "remote"),
        ("Remote - US", "remote"),
    ])
    def test_remote_location(self, location, expected):
        assert classify_work_type(location) == expected

    # Remote signal from title
    def test_remote_title(self):
        assert classify_work_type("", "Remote Software Engineer") == "remote"

    # Onsite signals
    @pytest.mark.parametrize("location,expected", [
        ("On-site - NYC", "onsite"),
        ("onsite", "onsite"),
        ("In-Office", "onsite"),
        ("Office-Based", "onsite"),
        ("New York, NY (in office)", "onsite"),
    ])
    def test_onsite(self, location, expected):
        assert classify_work_type(location) == expected

    # Hybrid signals
    @pytest.mark.parametrize("location,expected", [
        ("Hybrid - NYC", "hybrid"),
        ("hybrid", "hybrid"),
        ("New York (Hybrid)", "hybrid"),
    ])
    def test_hybrid(self, location, expected):
        assert classify_work_type(location) == expected

    # Mixed: remote + hybrid → hybrid wins
    def test_remote_hybrid_mixed(self):
        assert classify_work_type("Remote / Hybrid") == "hybrid"

    # Ambiguous — no signals
    @pytest.mark.parametrize("location", [
        "San Francisco, CA",
        "New York, NY",
        "Austin, TX",
        "Flexible",
    ])
    def test_ambiguous_returns_none(self, location):
        assert classify_work_type(location) is None

    # Empty inputs
    def test_empty_returns_none(self):
        assert classify_work_type("") is None
        assert classify_work_type("", "") is None
