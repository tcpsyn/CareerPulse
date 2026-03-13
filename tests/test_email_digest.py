import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.database import Database
from app.digest import generate_digest, _render_html_digest
from app.emailer import send_email, draft_application_email


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
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db(app):
    return app.state.db


@pytest.mark.asyncio
async def test_email_settings_roundtrip(db):
    settings = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "user@example.com",
        "smtp_password": "secret",
        "smtp_use_tls": True,
        "from_address": "noreply@example.com",
        "to_address": "user@example.com",
        "digest_enabled": True,
        "digest_schedule": "daily",
        "digest_time": "09:00",
        "digest_min_score": 70,
    }
    await db.update_email_settings(settings)
    loaded = await db.get_email_settings()
    assert loaded["smtp_host"] == "smtp.example.com"
    assert loaded["smtp_port"] == 587
    assert loaded["smtp_use_tls"] is True
    assert loaded["digest_enabled"] is True
    assert loaded["to_address"] == "user@example.com"
    assert loaded["digest_min_score"] == 70
    assert loaded["digest_time"] == "09:00"


@pytest.mark.asyncio
async def test_email_settings_api_hides_password(client, db):
    await db.update_email_settings({
        "smtp_host": "smtp.example.com",
        "smtp_password": "secret123",
        "from_address": "test@example.com",
    })
    resp = await client.get("/api/settings/email")
    assert resp.status_code == 200
    data = resp.json()
    assert "smtp_password" not in data
    assert data["smtp_host"] == "smtp.example.com"


@pytest.mark.asyncio
async def test_email_settings_api_save(client):
    resp = await client.post("/api/settings/email", json={
        "smtp_host": "mail.example.com",
        "smtp_port": 465,
        "smtp_username": "user",
        "smtp_password": "pass",
        "from_address": "me@example.com",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_email_settings_preserves_password(client, db):
    await db.update_email_settings({
        "smtp_host": "smtp.example.com",
        "smtp_password": "original_secret",
        "from_address": "test@example.com",
    })
    resp = await client.post("/api/settings/email", json={
        "smtp_host": "smtp.newhost.com",
        "smtp_password": "",
        "from_address": "test@example.com",
    })
    assert resp.status_code == 200
    loaded = await db.get_email_settings()
    assert loaded["smtp_host"] == "smtp.newhost.com"
    assert loaded["smtp_password"] == "original_secret"


@pytest.mark.asyncio
async def test_send_email_success():
    settings = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "user",
        "smtp_password": "pass",
        "smtp_use_tls": True,
        "from_address": "from@example.com",
    }
    with patch("app.emailer.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        result = await send_email(
            settings,
            to="recipient@example.com",
            subject="Test",
            body_text="Hello",
        )
    assert result is True
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_email_failure():
    settings = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "from_address": "from@example.com",
    }
    with patch("app.emailer.aiosmtplib.send", new_callable=AsyncMock, side_effect=Exception("SMTP error")):
        result = await send_email(
            settings,
            to="recipient@example.com",
            subject="Test",
            body_text="Hello",
        )
    assert result is False


@pytest.mark.asyncio
async def test_generate_digest_empty(db):
    digest = await generate_digest(db, min_score=60, hours=24)
    assert digest["job_count"] == 0
    assert digest["body"] != ""
    assert digest["html"] != ""
    assert "subject" in digest


def test_html_digest_template():
    jobs = [
        {
            "title": "Software Engineer",
            "company": "Acme Corp",
            "location": "Remote",
            "match_score": 85,
            "url": "https://example.com/job/1",
            "salary_min": 100000,
            "salary_max": 150000,
        },
        {
            "title": "Data Scientist",
            "company": "Big Co",
            "location": "NYC",
            "match_score": 72,
            "url": "https://example.com/job/2",
            "salary_min": None,
            "salary_max": None,
        },
    ]
    html = _render_html_digest(jobs, 24)
    assert "Software Engineer" in html
    assert "Acme Corp" in html
    assert "Data Scientist" in html
    assert "$100,000" in html
    assert "2 new matches" in html


def test_draft_application_email():
    email = draft_application_email(
        to="hr@company.com",
        company="TestCo",
        position="Engineer",
        cover_letter="I'm interested.",
        sender_name="Jane",
        sender_email="jane@test.com",
    )
    assert email["to"] == "hr@company.com"
    assert "Engineer" in email["subject"]
    assert "TestCo" in email["subject"]
    assert "I'm interested." in email["body"]


def test_draft_application_email_no_recipient():
    email = draft_application_email(
        to=None,
        company="TestCo",
        position="Engineer",
        cover_letter="Hi",
        sender_name="Jane",
        sender_email="jane@test.com",
    )
    assert email is None


@pytest.mark.asyncio
async def test_send_job_email_no_smtp(client):
    resp = await client.post("/api/jobs/999/send-email")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_test_email_endpoint(client):
    with patch("app.emailer.aiosmtplib.send", new_callable=AsyncMock):
        resp = await client.post("/api/settings/email/test", json={
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_username": "user",
            "smtp_password": "pass",
            "from_address": "test@example.com",
        })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_digest_send_test_endpoint_no_config(client):
    resp = await client.post("/api/digest/send-test")
    assert resp.status_code == 400
