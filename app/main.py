import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import Database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = app.state.db_path
    testing = getattr(app.state, "testing", False)
    os.makedirs(os.path.dirname(db_path) or "data", exist_ok=True)
    app.state.db = Database(db_path)
    await app.state.db.init()

    if not testing:
        from app.config import Settings
        from app.scrapers import ALL_SCRAPERS
        from app.scheduler import run_scrape_cycle

        settings = Settings()

        resume_text = ""
        if os.path.exists(settings.resume_path):
            with open(settings.resume_path) as f:
                resume_text = f.read()

        client = None
        if settings.anthropic_api_key:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        if client and resume_text:
            from app.matcher import JobMatcher
            from app.tailoring import Tailor
            app.state.matcher = JobMatcher(client, resume_text)
            app.state.tailor = Tailor(client, resume_text)
        else:
            app.state.matcher = None
            app.state.tailor = None

        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler()

        async def scheduled_scrape():
            db = app.state.db
            scrapers = [s() for s in ALL_SCRAPERS]
            await run_scrape_cycle(db, scrapers)
            if app.state.matcher:
                unscored = await db.get_unscored_jobs()
                if unscored:
                    results = await app.state.matcher.batch_score(unscored)
                    for r in results:
                        await db.insert_score(
                            r["job_id"], r["score"], r["reasons"],
                            r["concerns"], r["keywords"],
                        )

        scheduler.add_job(
            scheduled_scrape, "interval",
            hours=settings.scrape_interval_hours,
            id="scrape_cycle",
        )
        scheduler.start()
        app.state.scheduler = scheduler
        app.state.settings = settings
    else:
        app.state.matcher = None
        app.state.tailor = None
        app.state.scheduler = None

    yield

    if getattr(app.state, "scheduler", None):
        app.state.scheduler.shutdown(wait=False)
    await app.state.db.close()


def create_app(db_path: str = "data/jobfinder.db", testing: bool = False) -> FastAPI:
    app = FastAPI(title="JobFinder", lifespan=lifespan)
    app.state.db_path = db_path
    app.state.testing = testing

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/jobs")
    async def list_jobs(
        sort: str = Query("score"),
        limit: int = Query(50),
        offset: int = Query(0),
        min_score: int | None = Query(None),
        search: str | None = Query(None),
        source: str | None = Query(None),
    ):
        jobs = await app.state.db.list_jobs(
            sort_by=sort, limit=limit, offset=offset,
            min_score=min_score, search=search, source=source,
        )
        return {"jobs": jobs}

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: int):
        job = await app.state.db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        score = await app.state.db.get_score(job_id)
        sources = await app.state.db.get_sources(job_id)
        application = await app.state.db.get_application(job_id)
        return {**job, "score": score, "sources": sources, "application": application}

    @app.post("/api/jobs/{job_id}/dismiss")
    async def dismiss_job(job_id: int):
        await app.state.db.dismiss_job(job_id)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/prepare")
    async def prepare_application(job_id: int):
        job = await app.state.db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")

        tailor = app.state.tailor
        if not tailor:
            raise HTTPException(503, "Tailor not available (no API key or resume)")

        score = await app.state.db.get_score(job_id)
        match_reasons = score["match_reasons"] if score else []
        suggested_keywords = score["suggested_keywords"] if score else []

        result = await tailor.prepare(
            job_description=job["description"] or "",
            match_reasons=match_reasons,
            suggested_keywords=suggested_keywords,
        )

        application = await app.state.db.get_application(job_id)
        if not application:
            app_id = await app.state.db.insert_application(job_id, "prepared")
        else:
            app_id = application["id"]

        await app.state.db.update_application(
            app_id,
            status="prepared",
            tailored_resume=result.get("tailored_resume", ""),
            cover_letter=result.get("cover_letter", ""),
        )

        return {
            "job_id": job_id,
            "status": "prepared",
            "tailored_resume": result.get("tailored_resume", ""),
            "cover_letter": result.get("cover_letter", ""),
        }

    @app.post("/api/jobs/{job_id}/email")
    async def draft_email(job_id: int):
        from app.emailer import draft_application_email

        job = await app.state.db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")

        application = await app.state.db.get_application(job_id)
        cover_letter = application.get("cover_letter", "") if application else ""
        if not cover_letter:
            raise HTTPException(400, "No cover letter prepared for this job")

        email = draft_application_email(
            to=job.get("contact_email"),
            company=job["company"],
            position=job["title"],
            cover_letter=cover_letter,
            sender_name="Job Seeker",
            sender_email="",
        )

        if not email:
            raise HTTPException(400, "No contact email available for this job")

        if application:
            await app.state.db.update_application(
                application["id"],
                email_draft=json.dumps(email),
            )

        return {"job_id": job_id, "email": email}

    @app.post("/api/jobs/{job_id}/application")
    async def update_application(job_id: int, status: str = Query(...), notes: str = Query("")):
        app_row = await app.state.db.get_application(job_id)
        if not app_row:
            await app.state.db.insert_application(job_id, status)
        else:
            await app.state.db.update_application(app_row["id"], status=status, notes=notes)
        return {"ok": True}

    @app.get("/api/stats")
    async def get_stats():
        return await app.state.db.get_stats()

    @app.post("/api/scrape")
    async def trigger_scrape():
        async def _scrape_and_score():
            try:
                from app.scrapers import ALL_SCRAPERS
                from app.scheduler import run_scrape_cycle

                db = app.state.db
                scrapers = [s() for s in ALL_SCRAPERS]
                await run_scrape_cycle(db, scrapers)

                matcher = app.state.matcher
                if matcher:
                    unscored = await db.get_unscored_jobs()
                    if unscored:
                        results = await matcher.batch_score(unscored)
                        for r in results:
                            await db.insert_score(
                                r["job_id"], r["score"], r["reasons"],
                                r["concerns"], r["keywords"],
                            )
            except Exception:
                logger.exception("Background scrape+score failed")

        asyncio.create_task(_scrape_and_score())
        return {"status": "triggered"}

    if not testing:
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        if os.path.exists(static_dir):
            app.mount("/static", StaticFiles(directory=static_dir), name="static")

            @app.get("/")
            async def index():
                return FileResponse(os.path.join(static_dir, "index.html"))

    return app
