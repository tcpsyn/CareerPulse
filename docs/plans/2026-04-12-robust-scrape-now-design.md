# Robust "Scrape Now" — Design

**Date:** 2026-04-12
**Status:** Approved — ready for implementation
**Owner:** CareerPulse team

## Problem

Hitting "Scrape Now" is unreliable. Observed failure modes:

1. **Spinner shows `0/0` forever** — the task is hung before any scraper progress is reported.
2. **Spinner hangs on a specific scraper mid-cycle** — an individual source blocks the whole run.
3. **UI reports "done" too early** — new jobs appear without scores because scoring runs after the frontend has stopped polling.
4. **No error visibility** — per-scraper failures are logged server-side but never surfaced in the UI.
5. **No recovery path** — refreshing the page drops the progress indicator; there is no way to cancel a stuck run; clicking "Scrape Now" again during a hung run compounds the problem.

## Root causes (from code audit)

- `app/routers/scraping.py:81` wraps the work in `async with app.state.scrape_lock:`. A stuck previous task causes the next click to wait on the lock for up to 30 minutes (the `asyncio.wait_for` wrapper), producing the `0/0` symptom.
- `app/scheduler.py:128` sets `progress["active"] = False` at the end of `run_scrape_cycle`, *before* enrichment, location classification, and scoring run in the router. The UI sees `active=false` immediately, stops polling, and shows "done" while work is still happening.
- No per-scraper timeout. One hung `scraper.scrape()` call blocks the entire cycle.
- No heartbeat. The UI cannot distinguish "working" from "stalled."
- Errors are caught with `logger.exception` and never propagated to the UI.
- `app/static/js/app.js:210-254` does not check for an active scrape on page mount; refresh drops the polling.

## Goals

- "Scrape Now" works reliably every time, or fails loudly with a clear reason.
- A single hung scraper never blocks the cycle.
- Concurrent clicks never queue behind a stuck run.
- The UI shows phase, progress, per-source status, and stall detection.
- Users can cancel a running scrape.
- Page refresh resumes the indicator.

## Non-goals

- Server-Sent Events / WebSockets (deferred — 2s polling is sufficient).
- Persisting scrape history across restarts (in-memory state is fine).
- Retrying failed scrapers automatically in the same run.

---

## Design

### 1. State model

`app.state.scrape_progress` becomes a structured dict:

```python
{
  "active": bool,
  "phase": "scraping" | "enriching" | "classifying" | "scoring" | "done" | "error",
  "started_at": float,        # monotonic
  "last_updated_at": float,   # monotonic heartbeat
  "current": str | None,      # current scraper or phase detail
  "completed": int,           # scrapers done
  "total": int,               # total scrapers
  "new_jobs": int,
  "sources": [
    {
      "name": str,
      "status": "pending" | "running" | "ok" | "failed" | "timeout" | "skipped",
      "listings_found": int,
      "new_jobs": int,
      "error": str | None,
      "duration_ms": int | None,
    }
  ],
  "scoring": {"scored": int, "total": int, "skipped_reason": str | None},
  "errors": [str],             # top-level errors
  "task_id": str | None,
}
```

**Invariants:**

- `active == True` iff `phase not in {"done", "error"}`.
- `last_updated_at` is bumped on every mutation.
- `sources` entries are appended in scraper order; `status == "running"` for at most one at a time.
- `task_id` is a UUID generated per run; the cancel endpoint requires a matching ID.

**Persistence:** in-memory on `app.state` only. The lifespan startup in `app/main.py` resets `scrape_progress = None` so a crashed previous run never leaves `active=true`.

### 2. Concurrency, locking, and cancellation

**Endpoints:**

| Method | Path                     | Success                                       | Failure                                                 |
| ------ | ------------------------ | --------------------------------------------- | ------------------------------------------------------- |
| POST   | `/api/scrape`            | `202 {"task_id": ..., "status": "started"}`   | `409 {"error": "scrape_already_running", "task_id": …}` |
| POST   | `/api/scrape/cancel`     | `200 {"cancelled": true}`                     | `404 {"error": "no_active_scrape"}`                     |
| GET    | `/api/scrape/progress`   | `200 <state object>`                          | —                                                       |

**Concurrency guard** (replaces `scrape_lock`):

```python
progress = app.state.scrape_progress
if progress and progress.get("active"):
    return JSONResponse(
        {"error": "scrape_already_running", "task_id": progress["task_id"]},
        status_code=409,
    )

task_id = uuid.uuid4().hex
app.state.scrape_progress = _fresh_state(task_id)
app.state.scrape_task = asyncio.create_task(_scrape_and_score(app, task_id))
return {"task_id": task_id, "status": "started"}
```

Key behavior: the check is synchronous against `progress.active`, so a duplicate click returns 409 immediately instead of hanging at `0/0`.

**Cancellation:** `POST /api/scrape/cancel` calls `app.state.scrape_task.cancel()`. `_scrape_and_score` catches `asyncio.CancelledError`, sets `phase="error"`, appends `"Cancelled by user"` to `errors`, then re-raises.

**Stale-state recovery on startup:** in `app/main.py` lifespan, reset `app.state.scrape_progress = None` and `app.state.scrape_task = None` on boot.

### 3. Per-scraper timeouts and error tracking

`run_scrape_cycle` in `app/scheduler.py` wraps each `scraper.scrape()` call in `asyncio.wait_for`:

```python
PER_SCRAPER_TIMEOUT = 120  # seconds

src = {
    "name": source_name, "status": "running",
    "listings_found": 0, "new_jobs": 0,
    "error": None, "duration_ms": None,
}
progress["sources"].append(src)
progress["current"] = source_name
progress["last_updated_at"] = time.monotonic()

t0 = time.monotonic()
try:
    listings = await asyncio.wait_for(
        scraper_instance.scrape(), timeout=PER_SCRAPER_TIMEOUT
    )
    src["status"] = "ok"
    src["listings_found"] = len(listings)
except asyncio.TimeoutError:
    src["status"] = "timeout"
    src["error"] = f"exceeded {PER_SCRAPER_TIMEOUT}s"
    _scraper_breaker.record_failure(f"scraper:{source_name}")
    logger.warning(f"{source_name}: timeout after {PER_SCRAPER_TIMEOUT}s")
    continue
except Exception as e:
    src["status"] = "failed"
    src["error"] = str(e)[:200]
    _scraper_breaker.record_failure(f"scraper:{source_name}")
    logger.error(f"{source_name} failed: {e}")
    continue
finally:
    src["duration_ms"] = int((time.monotonic() - t0) * 1000)
    progress["last_updated_at"] = time.monotonic()
```

**Heartbeat discipline:** every progress mutation bumps `last_updated_at`. Inside the per-listing insert loop, bump the heartbeat every 25 listings so large payloads do not trip stall detection.

**Module import safety:** move `from app.scrapers import ALL_SCRAPERS` and `from app.scheduler import ...` to the top of `app/routers/scraping.py`. This eliminates first-click import latency inside the task.

**`run_scrape_cycle` no longer touches `active`.** It only updates `completed`, `current`, `new_jobs`, and per-source entries. The router owns phase/active.

### 4. Phase pipeline in the router

```python
async def _scrape_and_score(app, task_id):
    progress = app.state.scrape_progress
    bg_db = app.state.bg_db
    try:
        config = await bg_db.get_search_config()
        terms = config["search_terms"] if config else []
        keys = await bg_db.get_scraper_keys()
        scrapers = [s(search_terms=terms, scraper_keys=keys) for s in ALL_SCRAPERS]
        progress["total"] = len(scrapers)

        _set_phase(progress, "scraping")
        await run_scrape_cycle(
            bg_db, scrapers, search_terms=terms,
            progress=progress, scraper_keys=keys, force=True,
        )

        _set_phase(progress, "enriching", current="Fetching job details")
        await asyncio.wait_for(run_enrichment_cycle(bg_db), timeout=600)

        _set_phase(progress, "classifying", current="Classifying locations")
        ai_client = getattr(app.state, "ai_client", None)
        await asyncio.wait_for(
            run_location_classification(bg_db, ai_client), timeout=600
        )

        if ai_client:
            reachable, detail = await asyncio.wait_for(
                check_ai_reachable(ai_client), timeout=15
            )
            if reachable:
                _set_phase(progress, "scoring", current="Scoring jobs")
                await asyncio.wait_for(
                    app.state.score_unscored(bg_db), timeout=1800
                )
            else:
                progress["scoring"]["skipped_reason"] = detail
        else:
            progress["scoring"]["skipped_reason"] = "No AI provider configured"

        _set_phase(progress, "done", active=False)

    except asyncio.CancelledError:
        _set_phase(progress, "error", active=False)
        progress["errors"].append("Cancelled by user")
        raise
    except asyncio.TimeoutError:
        logger.exception("Scrape pipeline phase timed out")
        _set_phase(progress, "error", active=False)
        progress["errors"].append(f"{progress['phase']} phase timed out")
    except Exception as e:
        logger.exception("Scrape pipeline failed")
        _set_phase(progress, "error", active=False)
        progress["errors"].append(f"{type(e).__name__}: {str(e)[:200]}")
```

`_set_phase(progress, phase, current=None, active=True)` is a small helper that bumps `last_updated_at`, sets `phase`, optionally updates `current`, and optionally flips `active`.

**Scoring progress bridge:** `score_unscored` already maintains `app.state.scoring_progress`. During the scoring phase, a lightweight background coroutine mirrors `scoring_progress` into `progress["scoring"]` every second so the single `/api/scrape/progress` endpoint has everything.

### 5. Frontend: polling, stall detection, UI

All frontend changes land in `app/static/js/app.js` (scrape handler) and a small new render helper.

**Resume on mount:** on SPA init, call `GET /api/scrape/progress` once. If `active == true`, bind to the current `task_id` and start polling immediately.

**Polling:** 1500ms interval. Stops only when `phase` is `"done"` or `"error"`.

**Phase-aware label:**

| Phase          | Label                                  |
| -------------- | -------------------------------------- |
| `scraping`     | `Scraping: wellfound (7/14)`           |
| `enriching`    | `Enriching job details…`               |
| `classifying`  | `Classifying locations…`               |
| `scoring`      | `Scoring: 42/120`                      |
| `done`         | reset to `Scrape Now`, summary toast   |
| `error`        | reset to `Scrape Now`, red toast       |

**Stall detection:** client computes `stallSec = nowMonotonicClient - p.last_updated_at`. Because the server's `last_updated_at` is monotonic and the client has no shared clock, the server includes `server_now` in the progress response so the client can compute `stallSec = server_now - last_updated_at`.

- `stallSec > 30s` → button border turns amber, label becomes `Stalled — {current} ({n}s)`, a small "Cancel" link appears beside the spinner.
- `stallSec > 120s` → label turns red, a toast says "Scrape appears stuck — click Cancel to stop."

**Cancel button:** calls `POST /api/scrape/cancel`, shows `Cancelling…`, then a `Cancelled` toast when the server reports `phase=error`.

**Concurrent click handling:** if `POST /api/scrape` returns `409`, the frontend silently starts polling the returned `task_id` instead of showing an error.

**End-of-run summary:**

- On `phase == "done"`: toast `Scrape complete — {new_jobs} new jobs. {ok}/{total} sources ok{, N timeout}{, M failed}. [View details]`.
- On `phase == "error"`: red toast `Scrape failed — {errors[0]}. [View details]`.
- "View details" opens a modal listing each source row: name, status badge, duration, listings found, new jobs, error message. Reuses the existing modal infra from `app.js`.

Both `#scrape-btn` and `#stats-scrape-btn` get the same treatment via the existing `handleScrape`/`startScrapePoll` path.

---

## Testing

### Backend (pytest)

- `test_scrape_per_scraper_timeout`: inject a scraper whose `scrape()` awaits `asyncio.sleep(999)`; assert the run completes, the source is marked `timeout`, other scrapers still run.
- `test_scrape_concurrent_click_returns_409`: trigger one scrape, trigger a second; assert 409 and identical `task_id`.
- `test_scrape_cancel`: trigger, call cancel, assert `phase=="error"`, `"Cancelled by user"` in errors.
- `test_scrape_phase_transitions`: mock all phases, assert `scraping → enriching → classifying → scoring → done`.
- `test_scrape_premature_done_regression`: ensure `active` is true until after scoring finishes.
- `test_scrape_error_in_phase`: raise in enrichment; assert `phase=="error"` and error recorded.
- `test_scrape_heartbeat_updates`: assert `last_updated_at` advances on each progress mutation.

### Frontend (vitest)

- Phase label rendering for each phase.
- Stall detection math (30s / 120s thresholds).
- 409 handling: polling starts with the returned `task_id`.
- Resume on mount when `active == true`.
- End-of-run summary toast and modal content.

### Manual

- Hit "Scrape Now", refresh mid-run, confirm spinner resumes.
- Force one scraper to hang (temporarily add `await asyncio.sleep(200)`), confirm timeout path and that the rest of the cycle completes.
- Click "Scrape Now" twice rapidly, confirm 409 is silent and polling binds to the existing run.
- Click cancel mid-run, confirm cancellation and error toast.

---

## Rollout

Single PR with backend, frontend, and tests. No migrations. No flags. After merge, update `CLAUDE.md` with the new scrape contract and the per-scraper timeout setting.

## Implementation slices (for the team)

1. **Backend — state model + phase helper + router refactor** (backend-dev)
2. **Backend — scheduler per-scraper timeout + heartbeat + source tracking** (backend-dev)
3. **Backend — cancel endpoint + concurrency guard + startup reset** (backend-dev)
4. **Backend — tests** (backend-dev)
5. **Frontend — phase-aware polling, stall detection, resume-on-mount, 409 handling** (frontend-dev)
6. **Frontend — summary toast + details modal** (frontend-dev)
7. **Frontend — tests** (frontend-dev)
8. **Docs — CLAUDE.md update for scrape contract** (docs-specialist)
