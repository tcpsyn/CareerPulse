"""Backend coverage for the robust Scrape Now pipeline.

Design reference: docs/plans/2026-04-12-robust-scrape-now-design.md

Covers per-scraper timeout, 409 concurrency guard, cancel endpoint, phase
transitions, premature-done regression, error propagation, and heartbeat.
"""
import asyncio
from dataclasses import dataclass

import pytest
from httpx import AsyncClient, ASGITransport

from app.database import Database
from app.routers import scraping as scraping_router
from app.scheduler import run_scrape_cycle


@dataclass
class _FakeListing:
    title: str = "Staff Engineer"
    company: str = "Acme"
    location: str = "Remote"
    description: str = "Build stuff."
    url: str = "https://example.test/jobs/1"
    source: str = "fake"
    salary_min: int | None = 200_000
    salary_max: int | None = 250_000
    posted_date: str | None = None
    application_method: str = "url"
    contact_email: str | None = None


class _FastFakeScraper:
    """Returns one listing immediately."""

    source_name = "fake_fast"

    def __init__(self, *args, **kwargs):
        pass

    async def scrape(self):
        return [_FakeListing()]


class _HangingScraper:
    """Awaits forever — must be killed by the per-scraper timeout."""

    source_name = "fake_hang"

    def __init__(self, *args, **kwargs):
        pass

    async def scrape(self):
        await asyncio.sleep(9999)
        return []


@pytest.fixture
async def app(tmp_path):
    from app.main import create_app
    application = create_app(db_path=str(tmp_path / "test.db"), testing=True)
    db = Database(str(tmp_path / "test.db"))
    await db.init()
    application.state.db = db
    application.state.bg_db = db
    application.state.ai_client = None
    application.state.embedding_client = None
    yield application
    await db.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _wait_for(predicate, timeout=5.0, interval=0.02):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Task #2: per-scraper timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_per_scraper_timeout(db, monkeypatch):
    """A hung scraper must be killed by the per-scraper timeout and the
    cycle must continue to the next source."""
    # Collapse the per-scraper timeout to a sub-second value for the test.
    monkeypatch.setattr(
        "app.scheduler.PER_SCRAPER_TIMEOUT", 0.2, raising=True
    )

    progress = {
        "sources": [],
        "completed": 0,
        "total": 0,
        "current": None,
        "new_jobs": 0,
        "last_updated_at": 0.0,
    }
    scrapers = [_HangingScraper(), _FastFakeScraper()]
    result = await run_scrape_cycle(
        db, scrapers, search_terms=[], progress=progress, force=True
    )
    assert result >= 0
    assert len(progress["sources"]) == 2
    statuses = {s["name"]: s["status"] for s in progress["sources"]}
    assert statuses["fake_hang"] == "timeout"
    assert statuses["fake_fast"] == "ok"
    hang = next(s for s in progress["sources"] if s["name"] == "fake_hang")
    assert hang["error"] and "exceeded" in hang["error"]
    assert hang["duration_ms"] is not None


# ---------------------------------------------------------------------------
# Task #2: heartbeat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_heartbeat_updates(db):
    """`last_updated_at` must advance as the cycle progresses."""
    import time

    progress = {
        "sources": [],
        "completed": 0,
        "total": 0,
        "current": None,
        "new_jobs": 0,
        "last_updated_at": time.monotonic(),
    }
    start_hb = progress["last_updated_at"]
    await run_scrape_cycle(
        db, [_FastFakeScraper()], search_terms=[], progress=progress, force=True
    )
    assert progress["last_updated_at"] > start_hb


# ---------------------------------------------------------------------------
# Task #3: 409 concurrency guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_concurrent_click_returns_409(app, client, monkeypatch):
    """Second POST /api/scrape during an active run returns 409 with the
    original task_id — never blocks on a lock."""
    gate = asyncio.Event()

    async def _blocking_scrape(*args, **kwargs):
        await gate.wait()

    async def _noop(*args, **kwargs):
        return 0

    monkeypatch.setattr(scraping_router, "run_scrape_cycle", _blocking_scrape)
    monkeypatch.setattr(scraping_router, "run_enrichment_cycle", _noop)
    monkeypatch.setattr(scraping_router, "run_location_classification", _noop)

    first = await client.post("/api/scrape")
    assert first.status_code == 202
    first_task_id = first.json()["task_id"]

    # Yield so the background task starts and grabs `active=True`.
    await asyncio.sleep(0)

    second = await client.post("/api/scrape")
    assert second.status_code == 409
    body = second.json()
    assert body["error"] == "scrape_already_running"
    assert body["task_id"] == first_task_id

    gate.set()
    await asyncio.wait_for(app.state.scrape_task, timeout=5.0)


# ---------------------------------------------------------------------------
# Task #3: cancel endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_cancel(app, client, monkeypatch):
    """POST /api/scrape/cancel must end the run in phase=error with
    'Cancelled by user' recorded."""
    gate = asyncio.Event()

    async def _blocking_scrape(*args, **kwargs):
        await gate.wait()

    async def _noop(*args, **kwargs):
        return 0

    monkeypatch.setattr(scraping_router, "run_scrape_cycle", _blocking_scrape)
    monkeypatch.setattr(scraping_router, "run_enrichment_cycle", _noop)
    monkeypatch.setattr(scraping_router, "run_location_classification", _noop)

    resp = await client.post("/api/scrape")
    assert resp.status_code == 202
    await asyncio.sleep(0)

    cancel = await client.post("/api/scrape/cancel")
    assert cancel.status_code == 200
    assert cancel.json() == {"cancelled": True}

    try:
        await asyncio.wait_for(app.state.scrape_task, timeout=5.0)
    except asyncio.CancelledError:
        pass

    progress = app.state.scrape_progress
    assert progress["phase"] == "error"
    assert progress["active"] is False
    assert "Cancelled by user" in progress["errors"]


@pytest.mark.asyncio
async def test_cancel_returns_404_when_idle(app, client):
    resp = await client.post("/api/scrape/cancel")
    assert resp.status_code == 404
    assert resp.json()["error"] == "no_active_scrape"


# ---------------------------------------------------------------------------
# Task #1/#3: phase transitions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_phase_transitions(app, client, monkeypatch):
    """Phases must progress scraping → enriching → classifying → done (no
    AI client in test env → scoring is skipped)."""
    observed_phases: list[str] = []

    def _record_phase():
        p = app.state.scrape_progress
        if p and p["phase"] not in observed_phases:
            observed_phases.append(p["phase"])

    async def _scrape(*args, **kwargs):
        _record_phase()

    async def _enrich(*args, **kwargs):
        _record_phase()
        return 0

    async def _classify(*args, **kwargs):
        _record_phase()
        return 0

    monkeypatch.setattr(scraping_router, "run_scrape_cycle", _scrape)
    monkeypatch.setattr(scraping_router, "run_enrichment_cycle", _enrich)
    monkeypatch.setattr(scraping_router, "run_location_classification", _classify)

    resp = await client.post("/api/scrape")
    assert resp.status_code == 202

    await asyncio.wait_for(app.state.scrape_task, timeout=5.0)

    assert observed_phases[:3] == ["scraping", "enriching", "classifying"]
    progress = app.state.scrape_progress
    assert progress["phase"] == "done"
    assert progress["active"] is False
    # ai_client is None in testing → skipped
    assert progress["scoring"]["skipped_reason"] == "No AI provider configured"


# ---------------------------------------------------------------------------
# Task #1: premature-done regression
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_premature_done_regression(app, client, monkeypatch):
    """`active` must be true across every intermediate phase. The old
    bug set active=False at the end of run_scrape_cycle, so /progress
    would report done before enrichment, classification, or scoring
    actually ran."""
    seen = []

    async def _scrape(*args, **kwargs):
        seen.append(("scraping", app.state.scrape_progress["active"]))

    async def _enrich(*args, **kwargs):
        seen.append(("enriching", app.state.scrape_progress["active"]))
        return 0

    async def _classify(*args, **kwargs):
        seen.append(("classifying", app.state.scrape_progress["active"]))
        return 0

    monkeypatch.setattr(scraping_router, "run_scrape_cycle", _scrape)
    monkeypatch.setattr(scraping_router, "run_enrichment_cycle", _enrich)
    monkeypatch.setattr(scraping_router, "run_location_classification", _classify)

    resp = await client.post("/api/scrape")
    assert resp.status_code == 202
    await asyncio.wait_for(app.state.scrape_task, timeout=5.0)

    assert [name for name, _ in seen] == ["scraping", "enriching", "classifying"]
    assert all(active is True for _, active in seen)
    assert app.state.scrape_progress["active"] is False
    assert app.state.scrape_progress["phase"] == "done"


# ---------------------------------------------------------------------------
# Task #1: error in phase
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_error_in_phase(app, client, monkeypatch):
    """An exception inside enrichment must land us in phase=error with the
    error recorded on the progress state."""
    async def _scrape(*args, **kwargs):
        return None

    async def _enrich_boom(*args, **kwargs):
        raise RuntimeError("enrichment exploded")

    async def _classify(*args, **kwargs):
        return 0

    monkeypatch.setattr(scraping_router, "run_scrape_cycle", _scrape)
    monkeypatch.setattr(scraping_router, "run_enrichment_cycle", _enrich_boom)
    monkeypatch.setattr(scraping_router, "run_location_classification", _classify)

    resp = await client.post("/api/scrape")
    assert resp.status_code == 202
    await asyncio.wait_for(app.state.scrape_task, timeout=5.0)

    progress = app.state.scrape_progress
    assert progress["phase"] == "error"
    assert progress["active"] is False
    assert any("enrichment exploded" in e or "RuntimeError" in e for e in progress["errors"])


# ---------------------------------------------------------------------------
# Progress endpoint shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_progress_shape_when_idle(app, client):
    resp = await client.get("/api/scrape/progress")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "active",
        "phase",
        "completed",
        "total",
        "new_jobs",
        "sources",
        "scoring",
        "errors",
        "task_id",
        "server_now",
    ):
        assert key in body
    assert body["active"] is False
    assert body["phase"] == "done"
    assert body["task_id"] is None


@pytest.mark.asyncio
async def test_progress_includes_server_now_and_task_id(app, client, monkeypatch):
    gate = asyncio.Event()

    async def _blocking(*args, **kwargs):
        await gate.wait()

    async def _noop(*args, **kwargs):
        return 0

    monkeypatch.setattr(scraping_router, "run_scrape_cycle", _blocking)
    monkeypatch.setattr(scraping_router, "run_enrichment_cycle", _noop)
    monkeypatch.setattr(scraping_router, "run_location_classification", _noop)

    started = await client.post("/api/scrape")
    task_id = started.json()["task_id"]
    await asyncio.sleep(0)

    mid = await client.get("/api/scrape/progress")
    body = mid.json()
    assert body["task_id"] == task_id
    assert body["active"] is True
    assert isinstance(body["server_now"], (int, float))
    assert body["last_updated_at"] is not None

    gate.set()
    await asyncio.wait_for(app.state.scrape_task, timeout=5.0)
