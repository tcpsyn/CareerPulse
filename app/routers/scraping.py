import asyncio
import json
import logging
import time
import time as _time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.ai_client import check_ai_reachable
from app.database import Database
from app.scheduler import (
    run_enrichment_cycle,
    run_location_classification,
    run_scrape_cycle,
)
from app.scrapers import ALL_SCRAPERS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _fresh_state(task_id: str) -> dict:
    now = time.monotonic()
    return {
        "active": True,
        "phase": "scraping",
        "started_at": now,
        "last_updated_at": now,
        "current": None,
        "completed": 0,
        "total": 0,
        "new_jobs": 0,
        "sources": [],
        "scoring": {"scored": 0, "total": 0, "skipped_reason": None},
        "errors": [],
        "task_id": task_id,
    }


def _set_phase(
    progress: dict,
    phase: str,
    current: str | None = None,
    active: bool = True,
) -> None:
    """Transition the scrape state machine. Bumps heartbeat on every call."""
    progress["phase"] = phase
    if current is not None:
        progress["current"] = current
    progress["active"] = active
    progress["last_updated_at"] = time.monotonic()


def _mirror_scoring_once(app, progress: dict) -> None:
    sp = getattr(app.state, "scoring_progress", None)
    if not sp:
        return
    progress["scoring"] = {
        "scored": sp.get("scored", 0),
        "total": sp.get("total", 0),
        "skipped_reason": progress.get("scoring", {}).get("skipped_reason"),
    }
    progress["last_updated_at"] = time.monotonic()


async def _mirror_scoring_progress(app, progress: dict) -> None:
    try:
        while True:
            await asyncio.sleep(1.0)
            _mirror_scoring_once(app, progress)
    except asyncio.CancelledError:
        raise


async def _scrape_and_score(app, task_id: str) -> None:
    """Phase pipeline. Router owns phase/active — scheduler only updates counters."""
    progress = app.state.scrape_progress
    bg_db = app.state.bg_db
    mirror_task: asyncio.Task | None = None
    try:
        config = await bg_db.get_search_config()
        terms = config["search_terms"] if config else []
        keys = await bg_db.get_scraper_keys()
        scrapers = [s(search_terms=terms, scraper_keys=keys) for s in ALL_SCRAPERS]
        progress["total"] = len(scrapers)
        progress["last_updated_at"] = time.monotonic()

        _set_phase(progress, "scraping")
        await run_scrape_cycle(
            bg_db,
            scrapers,
            search_terms=terms,
            progress=progress,
            scraper_keys=keys,
            force=True,
        )

        _set_phase(progress, "enriching", current="Fetching job details")
        await asyncio.wait_for(run_enrichment_cycle(bg_db), timeout=600)

        ai_client = getattr(app.state, "ai_client", None)
        _set_phase(progress, "classifying", current="Classifying locations")
        await asyncio.wait_for(
            run_location_classification(bg_db, ai_client), timeout=600
        )

        if ai_client:
            reachable, detail = await asyncio.wait_for(
                check_ai_reachable(ai_client), timeout=15
            )
            if reachable:
                _set_phase(progress, "scoring", current="Scoring jobs")
                mirror_task = asyncio.create_task(
                    _mirror_scoring_progress(app, progress)
                )
                try:
                    await asyncio.wait_for(
                        app.state.score_unscored(bg_db), timeout=1800
                    )
                finally:
                    if mirror_task and not mirror_task.done():
                        mirror_task.cancel()
                        try:
                            await mirror_task
                        except (asyncio.CancelledError, Exception):
                            pass
                    mirror_task = None
                    _mirror_scoring_once(app, progress)
            else:
                progress["scoring"]["skipped_reason"] = detail
                progress["last_updated_at"] = time.monotonic()
        else:
            progress["scoring"]["skipped_reason"] = "No AI provider configured"
            progress["last_updated_at"] = time.monotonic()

        _set_phase(progress, "done", active=False)

    except asyncio.CancelledError:
        phase_name = progress.get("phase", "unknown")
        _set_phase(progress, "error", active=False)
        progress["errors"].append("Cancelled by user")
        logger.info(f"Scrape pipeline cancelled during phase: {phase_name}")
        raise
    except asyncio.TimeoutError:
        phase_name = progress.get("phase", "unknown")
        logger.exception("Scrape pipeline phase timed out")
        _set_phase(progress, "error", active=False)
        progress["errors"].append(f"{phase_name} phase timed out")
    except Exception as e:
        logger.exception("Scrape pipeline failed")
        _set_phase(progress, "error", active=False)
        progress["errors"].append(f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        if mirror_task and not mirror_task.done():
            mirror_task.cancel()


@router.get("/health")
async def health(request: Request):
    db: Database = request.app.state.db

    db_ok = False
    try:
        cursor = await db.db.execute("SELECT 1")
        await cursor.fetchone()
        db_ok = True
    except Exception:
        pass

    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        scheduler_state = "running" if scheduler.running else "stopped"
    else:
        scheduler_state = "not_configured"

    last_scrape = None
    try:
        schedules = await db.get_all_scraper_schedules()
        times = [s["last_scraped_at"] for s in schedules if s.get("last_scraped_at")]
        if times:
            last_scrape = max(times)
    except Exception:
        pass

    ai_client = getattr(request.app.state, "ai_client", None)

    ai_status = "not_configured"
    ai_detail = ""
    if ai_client:
        reachable, ai_detail = await check_ai_reachable(ai_client)
        ai_status = "ok" if reachable else "unreachable"

    start = getattr(request.app.state, "start_time", None)
    uptime_seconds = round(_time.monotonic() - start, 1) if start else None

    body = {
        "status": "healthy" if db_ok else "unhealthy",
        "db": "ok" if db_ok else "error",
        "scheduler": scheduler_state,
        "last_scrape": last_scrape,
        "ai_provider": ai_client.provider if ai_client else None,
        "ai_configured": ai_client is not None,
        "ai_status": ai_status,
        "ai_detail": ai_detail if ai_status != "ok" else "",
        "uptime_seconds": uptime_seconds,
    }

    if not db_ok:
        return Response(
            content=json.dumps(body),
            media_type="application/json",
            status_code=503,
        )
    return body


@router.post("/scrape")
async def trigger_scrape(request: Request):
    app = request.app
    progress = app.state.scrape_progress
    if progress and progress.get("active"):
        return JSONResponse(
            {
                "error": "scrape_already_running",
                "task_id": progress.get("task_id"),
            },
            status_code=409,
        )

    task_id = uuid.uuid4().hex
    app.state.scrape_progress = _fresh_state(task_id)
    app.state.scrape_task = asyncio.create_task(_scrape_and_score(app, task_id))
    return JSONResponse(
        {"task_id": task_id, "status": "started"},
        status_code=202,
    )


@router.post("/scrape/cancel")
async def cancel_scrape(request: Request):
    app = request.app
    task = getattr(app.state, "scrape_task", None)
    progress = app.state.scrape_progress
    if not progress or not progress.get("active") or not task or task.done():
        return JSONResponse(
            {"error": "no_active_scrape"},
            status_code=404,
        )
    task.cancel()
    return {"cancelled": True}


@router.get("/scrape/progress")
async def scrape_progress(request: Request):
    progress = request.app.state.scrape_progress
    now = time.monotonic()
    if not progress:
        return {
            "active": False,
            "phase": "done",
            "started_at": None,
            "last_updated_at": None,
            "current": None,
            "completed": 0,
            "total": 0,
            "new_jobs": 0,
            "sources": [],
            "scoring": {"scored": 0, "total": 0, "skipped_reason": None},
            "errors": [],
            "task_id": None,
            "server_now": now,
        }
    return {**progress, "server_now": now}


@router.post("/jobs/enrich")
async def enrich_jobs(request: Request):
    bg_db = getattr(request.app.state, "bg_db", request.app.state.db)
    enriched = await run_enrichment_cycle(bg_db, limit=50)
    return {"enriched": enriched}


@router.post("/score")
async def trigger_score(request: Request):
    app = request.app
    if not getattr(app.state, "ai_client", None):
        return {"status": "skipped", "reason": "No AI provider configured. Go to Settings → AI to set one up."}

    async def _run_scoring():
        try:
            await asyncio.wait_for(
                app.state.score_unscored(app.state.bg_db), timeout=1800
            )
        except asyncio.TimeoutError:
            logger.error("Background scoring timed out after 30 minutes")
        except Exception:
            logger.exception("Background scoring failed")

    asyncio.create_task(_run_scoring())
    return {"status": "scoring_triggered"}


@router.get("/score/progress")
async def score_progress(request: Request):
    progress = request.app.state.scoring_progress
    if not progress:
        return {"active": False, "scored": 0, "total": 0}
    return progress


@router.post("/rescore-failed")
async def rescore_failed(request: Request):
    """Clear error scores (score=0 from transient failures) and trigger rescoring."""
    app = request.app
    bg_db = getattr(app.state, "bg_db", app.state.db)
    cleared = await bg_db.clear_failed_scores()
    if cleared and getattr(app.state, "ai_client", None):
        async def _run_rescore():
            try:
                await asyncio.wait_for(
                    app.state.score_unscored(bg_db), timeout=1800
                )
            except asyncio.TimeoutError:
                logger.error("Background rescoring timed out")
            except Exception:
                logger.exception("Background rescoring failed")
        asyncio.create_task(_run_rescore())
    return {"cleared": cleared, "rescoring": cleared > 0 and getattr(app.state, "ai_client", None) is not None}


@router.post("/rescore-all")
async def rescore_all(request: Request):
    """Clear all scores and trigger full rescoring with current rubric."""
    app = request.app
    bg_db = getattr(app.state, "bg_db", app.state.db)
    cleared = await bg_db.clear_all_scores()
    has_ai = getattr(app.state, "ai_client", None) is not None
    if cleared and has_ai:
        async def _run_rescore():
            try:
                await asyncio.wait_for(
                    app.state.score_unscored(bg_db), timeout=3600
                )
            except asyncio.TimeoutError:
                logger.error("Full rescoring timed out after 1h")
            except Exception:
                logger.exception("Full rescoring failed")
        asyncio.create_task(_run_rescore())
    return {"cleared": cleared, "rescoring": cleared > 0 and has_ai}


@router.post("/dismiss-stale")
async def dismiss_stale(request: Request):
    dismissed = await request.app.state.db.auto_dismiss_stale()
    return {"ok": True, "dismissed": dismissed}


@router.post("/clear-jobs")
async def clear_jobs(request: Request):
    await request.app.state.db.clear_jobs()
    return {"ok": True, "message": "All jobs, scores, and applications cleared"}


@router.post("/clear-all")
async def clear_all(request: Request):
    await request.app.state.db.clear_all()
    request.app.state.matcher = None
    request.app.state.tailor = None
    return {"ok": True, "message": "All data cleared"}
