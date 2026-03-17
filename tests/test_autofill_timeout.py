import asyncio
import json

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.database import Database


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

    with patch("app.main.AUTOFILL_ANALYZE_TIMEOUT", 1):
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
