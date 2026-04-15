import asyncio
import json

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.database import Database
from app.routers.autofill import _deterministic_fill


@pytest.fixture
async def app(tmp_path):
    from app.main import create_app
    application = create_app(db_path=str(tmp_path / "test.db"), testing=True)
    db = Database(str(tmp_path / "test.db"))
    await db.init()
    application.state.db = db
    yield application
    await db.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def mock_ai_client():
    client = AsyncMock()
    client.chat = AsyncMock()
    return client


async def test_autofill_analyze_timeout(app, client, mock_ai_client):
    """AI call that exceeds the timeout should return an error, not hang."""

    async def slow_chat(*args, **kwargs):
        await asyncio.sleep(5)
        return '[]'

    mock_ai_client.chat = AsyncMock(side_effect=slow_chat)
    app.state.ai_client = mock_ai_client

    with patch("app.routers.autofill.AUTOFILL_ANALYZE_TIMEOUT", 1):
        resp = await client.post(
            "/api/autofill/analyze",
            json={"form_html": "<form><input name='email'></form>", "fields": [{"name": "email"}]},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert "timed out" in data["error"].lower()
    assert data["mappings"] == []


async def test_autofill_analyze_no_timeout_on_fast_response(app, client, mock_ai_client):
    """A fast AI response should succeed normally, no timeout error."""

    mock_ai_client.chat = AsyncMock(return_value=json.dumps([
        {"field_name": "email", "value": "test@example.com", "confidence": 0.9}
    ]))
    app.state.ai_client = mock_ai_client

    resp = await client.post(
        "/api/autofill/analyze",
        json={"form_html": "<form><input name='email'></form>", "fields": [{"name": "email"}]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "error" not in data
    assert isinstance(data["mappings"], list)
    assert len(data["mappings"]) == 1


# ─── _deterministic_fill phone field matching ──────────────────

PROFILE = {
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "(555) 123-4567",
    "phone_country_code": "+1",
    "address_country_name": "United States",
}


def test_deterministic_fill_matches_bare_phone_field():
    """Greenhouse #phone (name='phone', id='phone') should match deterministically."""
    fields = [
        {"selector": "#phone", "name": "phone", "id": "phone", "label": "Phone",
         "tag": "input", "type": "text", "placeholder": "", "currentValue": ""},
    ]
    mappings, remaining = _deterministic_fill(fields, PROFILE)
    assert len(mappings) == 1
    assert mappings[0]["selector"] == "#phone"
    assert mappings[0]["value"] == "(555) 123-4567"
    assert mappings[0]["action"] == "fill_text"
    assert remaining == []


def test_deterministic_fill_matches_phone_number_field():
    """Fields with name='phone_number' should still match."""
    fields = [
        {"selector": "#phone_number", "name": "phone_number", "id": "phone_number",
         "label": "Phone Number", "tag": "input", "type": "tel",
         "placeholder": "", "currentValue": ""},
    ]
    mappings, remaining = _deterministic_fill(fields, PROFILE)
    assert len(mappings) == 1
    assert mappings[0]["value"] == "(555) 123-4567"


def test_deterministic_fill_excludes_phone_country_code():
    """phone_country_code should NOT match the phone number rule."""
    fields = [
        {"selector": "#phone_country_code", "name": "phone_country_code",
         "id": "phone_country_code", "label": "Phone Country Code",
         "tag": "select", "type": "", "placeholder": "", "currentValue": "",
         "options": [{"text": "United States (+1)", "value": "US"}]},
    ]
    mappings, remaining = _deterministic_fill(fields, PROFILE)
    assert len(mappings) == 1
    # Should be matched by the country code rule, not the phone number rule
    assert mappings[0]["action"] == "select_dropdown_safe"


def test_deterministic_fill_excludes_phone_extension():
    """phone_extension fields should NOT be filled with the phone number."""
    fields = [
        {"selector": "#phone_ext", "name": "phone_extension",
         "id": "phone_ext", "label": "Phone Extension",
         "tag": "input", "type": "text", "placeholder": "", "currentValue": ""},
    ]
    mappings, remaining = _deterministic_fill(fields, PROFILE)
    # _is_excluded blocks phone-pattern rules for extension fields,
    # so the field falls to remaining (handled by AI)
    phone_mappings = [m for m in mappings if m["value"] == PROFILE["phone"]]
    assert phone_mappings == [], "phone extension field must not be filled with the phone number"


def test_deterministic_fill_greenhouse_phone_and_country_code():
    """Both Greenhouse phone fields should be matched deterministically."""
    fields = [
        {"selector": "#phone_country_code", "name": "phone_country_code",
         "id": "phone_country_code", "label": "Phone Country Code",
         "tag": "select", "type": "", "placeholder": "", "currentValue": "",
         "options": [{"text": "United States (+1)", "value": "US"}]},
        {"selector": "#phone", "name": "phone", "id": "phone", "label": "Phone",
         "tag": "input", "type": "text", "placeholder": "", "currentValue": ""},
    ]
    mappings, remaining = _deterministic_fill(fields, PROFILE)
    assert len(mappings) == 2
    assert remaining == []
    phone_mapping = next(m for m in mappings if m["selector"] == "#phone")
    code_mapping = next(m for m in mappings if m["selector"] == "#phone_country_code")
    assert phone_mapping["value"] == "(555) 123-4567"
    assert phone_mapping["action"] == "fill_text"
    assert code_mapping["action"] == "select_dropdown_safe"
