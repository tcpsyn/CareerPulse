import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import time as _time
from datetime import datetime, timezone

from app.database import Database
from app.ai_client import AIClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _build_ai_client(ai_settings: dict | None, env_key: str = "") -> AIClient | None:
    """Build an AIClient from DB settings or env fallback."""
    if ai_settings and ai_settings.get("provider"):
        provider = ai_settings["provider"]
        api_key = ai_settings.get("api_key", "")
        model = ai_settings.get("model", "")
        base_url = ai_settings.get("base_url", "")
        if provider == "ollama":
            return AIClient(provider, model=model, base_url=base_url)
        if api_key:
            return AIClient(provider, api_key=api_key, model=model, base_url=base_url)
    if env_key:
        return AIClient("anthropic", api_key=env_key)
    return None


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
        from app.scheduler import run_scrape_cycle, run_enrichment_cycle, run_maintenance_cycle, run_reminder_check, run_digest_cycle

        settings = Settings()

        resume_text = ""
        if os.path.exists(settings.resume_path):
            with open(settings.resume_path) as f:
                resume_text = f.read()

        if not resume_text:
            config = await app.state.db.get_search_config()
            if config and config.get("resume_text"):
                resume_text = config["resume_text"]

        ai_settings = await app.state.db.get_ai_settings()
        client = _build_ai_client(ai_settings, settings.anthropic_api_key)

        logger.info(f"Lifespan: client={'yes' if client else 'no'}, resume={len(resume_text)} chars")
        if client and resume_text:
            from app.matcher import JobMatcher
            from app.tailoring import Tailor
            app.state.matcher = JobMatcher(client, resume_text)
            app.state.tailor = Tailor(client, resume_text)
            logger.info("Matcher and Tailor initialized")
        else:
            app.state.matcher = None
            app.state.tailor = None
            logger.warning("Matcher NOT initialized - client=%s, resume=%d chars",
                           bool(client), len(resume_text))

        app.state.ai_client = client
        app.state.settings = settings

        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler()

        async def scheduled_scrape():
            db = app.state.db
            config = await db.get_search_config()
            terms = config["search_terms"] if config else []
            keys = await db.get_scraper_keys()
            scrapers = [s(search_terms=terms, scraper_keys=keys) for s in ALL_SCRAPERS]
            await run_scrape_cycle(db, scrapers, search_terms=terms, scraper_keys=keys)

        async def scheduled_enrichment():
            await run_enrichment_cycle(app.state.db)

        async def scheduled_scoring():
            await _score_unscored(app.state.db)

        async def scheduled_maintenance():
            await run_maintenance_cycle(app.state.db)

        async def scheduled_reminder_check():
            due = await run_reminder_check(app.state.db)
            for r in due:
                await app.state.db.add_event(
                    r["job_id"], "reminder_due",
                    f"Follow-up reminder due for {r.get('company', 'unknown')}"
                )

        async def scheduled_digest():
            await run_digest_cycle(app.state.db)

        scheduler.add_job(
            scheduled_scrape, "interval",
            hours=settings.scrape_interval_hours,
            id="scrape_cycle",
        )
        scheduler.add_job(
            scheduled_enrichment, "interval",
            hours=2,
            id="enrichment_cycle",
        )
        scheduler.add_job(
            scheduled_scoring, "interval",
            hours=1,
            id="scoring_cycle",
        )
        scheduler.add_job(
            scheduled_maintenance, "interval",
            hours=24,
            id="maintenance_cycle",
        )
        scheduler.add_job(
            scheduled_reminder_check, "interval",
            hours=12,
            id="reminder_check",
        )
        scheduler.add_job(
            scheduled_digest, "cron",
            hour=8,
            id="digest_cycle",
        )
        scheduler.start()
        app.state.scheduler = scheduler
    else:
        app.state.matcher = None
        app.state.tailor = None
        app.state.ai_client = None
        app.state.scheduler = None

    app.state.start_time = _time.monotonic()

    yield

    if getattr(app.state, "scheduler", None):
        app.state.scheduler.shutdown(wait=False)
    await app.state.db.close()


def _build_form_analysis_prompt(
    profile_summary: str,
    qa_summary: str,
    fields_summary: str,
    form_html: str,
    page_url: str,
) -> str:
    """Build the AI prompt for form field analysis and autofill mapping."""

    # Include structured fields when available, fall back to form HTML
    if fields_summary:
        fields_section = f"""STRUCTURED FORM FIELDS (JSON with id, name, type, label, placeholder, options):
{fields_summary}"""
    else:
        fields_section = ""

    if form_html:
        html_section = f"""RAW FORM HTML (use for additional context — labels, grouping, nearby text):
{form_html[:8000]}"""
    else:
        html_section = ""

    prompt = f"""You are a job application autofill assistant. Analyze form fields and map them to the user's profile data.

=== USER PROFILE SCHEMA ===
The profile has these sections and field types:

PERSONAL INFO (top-level fields):
- full_name, middle_name, preferred_name (text)
- email (text)
- phone, phone_country_code, phone_type, additional_phone (text)
- address_street1, address_street2, address_city, address_state, address_zip, address_country_code, address_country_name
- perm_address_street1, perm_address_street2, perm_address_city, perm_address_state, perm_address_zip, perm_address_country_code, perm_address_country_name
- location (text, general location summary)
- linkedin_url, github_url, portfolio_url, website_url
- date_of_birth (text, ISO format)
- pronouns
- drivers_license, drivers_license_class, drivers_license_state

WORK AUTHORIZATION:
- country_of_citizenship, authorized_to_work_us, requires_sponsorship, authorization_type
- security_clearance, clearance_status

SALARY & AVAILABILITY:
- desired_salary_min, desired_salary_max (integers)
- salary_period (e.g. "yearly", "hourly")
- availability_date (text, ISO format)
- notice_period (text, e.g. "2 weeks")
- willing_to_relocate (text)

PREFERENCES:
- how_heard_default (text, default answer for "How did you hear about us?")
- background_check_consent (text)
- cover_letter_template (text)

WORK HISTORY (array): company, job_title, location_city, location_state, location_country, start_month, start_year, end_month, end_year, is_current, description
EDUCATION (array): school, degree_type, field_of_study, minor, start_month, start_year, grad_month, grad_year, gpa, honors
CERTIFICATIONS (array): name, issuing_org, cert_type, license_number, state, date_obtained, expiration_date
SKILLS (array): name, years_experience, proficiency
LANGUAGES (array): language, proficiency
REFERENCES (array): name, title, company, phone, email, relationship, years_known
MILITARY: branch, rank, specialty, start_date, end_date
EEO: gender, race_ethnicity, disability_status, veteran_status, veteran_categories, sexual_orientation

=== USER PROFILE DATA ===
{profile_summary}

=== CUSTOM Q&A BANK ===
Each entry has: question_pattern, category, answer.
{qa_summary}

=== FORM DATA ===
{fields_section}

{html_section}

PAGE URL: {page_url}

=== OUTPUT FORMAT ===
Return a JSON array of objects, one per field to fill:
[
  {{"selector": "#field-id-or-name", "value": "the value to fill", "action": "fill_text|select_dropdown|click_radio|check_checkbox|skip", "confidence": 0.0-1.0, "field_label": "human readable label"}}
]

=== RULES (follow strictly) ===

SELECTORS:
- Use CSS selector format: #id when id exists, otherwise [name="xxx"]
- Each selector must uniquely identify one field

OPTION MATCHING (CRITICAL):
- For dropdowns (select), radio buttons, and checkboxes: you MUST pick a value that EXACTLY matches one of the provided option values or option text. Do NOT invent option values.
- If the field has an "options" array, the value MUST be one of those option values exactly as written.
- If no option is a reasonable match, set action to "skip".

MULTI-PART DATES:
- Forms often split dates into separate month/year/day dropdowns.
- For month selects: match the format of the options (e.g. "1" vs "01" vs "January" vs "Jan").
- For year selects: use the 4-digit year from the profile data.
- For day selects: use the day number matching the option format.
- Map graduation dates from education entries, employment dates from work history.

Q&A MATCHING:
- For open-ended text fields with questions (textarea, long text inputs), FIRST check the Custom Q&A Bank for a matching question_pattern before generating a generic answer.
- Match by semantic similarity, not exact string match — e.g. "Why are you interested in this role?" matches a pattern like "interest in role" or "why this company".
- If a Q&A match is found, use that answer verbatim.

PHONE FORMAT:
- Check the field's placeholder or label for format hints (e.g. "(555) 555-5555", "+1", "xxx-xxx-xxxx").
- If the form has separate country code and phone number fields, split accordingly.
- Use phone_country_code from profile if available.

EEO / VOLUNTARY SELF-IDENTIFICATION:
- Use the stored EEO preferences from the profile (gender, race_ethnicity, disability_status, veteran_status, sexual_orientation).
- If a stored preference is empty, default to "Decline to self-identify" or the closest decline/prefer-not-to-answer option.
- MUST use exact option values from the dropdown/radio options.

SALARY & COMPENSATION:
- Use desired_salary_min or desired_salary_max as appropriate.
- If the form asks for a single expected salary, use desired_salary_min.
- Include salary_period context if the form asks for it.

START DATE / AVAILABILITY:
- Use availability_date from profile if set.
- If not set and the form requires an answer, use notice_period to suggest a date.

GENERAL:
- Skip fields you cannot confidently fill (set action to "skip").
- For "How did you hear about us?" questions, use how_heard_default from profile; if empty, use "Online Job Board".
- For file upload fields, always skip.
- For CAPTCHA or verification fields, always skip.
- Return ONLY the JSON array, no other text or explanation."""

    return prompt


def create_app(db_path: str = "data/jobfinder.db", testing: bool = False) -> FastAPI:
    app = FastAPI(title="CareerPulse", lifespan=lifespan)
    app.state.db_path = db_path
    app.state.testing = testing

    app.state.scoring_progress = None
    app.state.scrape_progress = None
    app.state.notification_subscribers: list[asyncio.Queue] = []
    app.state.alert_threshold = 80

    async def _broadcast_notification(notification: dict):
        for queue in list(app.state.notification_subscribers):
            try:
                queue.put_nowait(notification)
            except asyncio.QueueFull:
                pass

    async def _check_high_score_alerts(db, job_id: int, score: int, job_title: str, company: str):
        if score >= app.state.alert_threshold:
            title = f"High score: {job_title}"
            message = f"{company} — Score {score}"
            notif_id = await db.insert_notification(job_id, "high_score", title, message)
            notif = {"id": notif_id, "job_id": job_id, "type": "high_score", "title": title, "message": message, "read": 0}
            await _broadcast_notification(notif)

    async def _score_unscored(db):
        matcher = app.state.matcher
        if not matcher:
            logger.warning("Matcher not available, skipping scoring")
            return
        all_unscored = await db.get_unscored_jobs(limit=10000)
        total = len(all_unscored)
        if total == 0:
            return
        app.state.scoring_progress = {"scored": 0, "total": total, "active": True}
        scored = 0
        batch_size = 5
        try:
            for i in range(0, total, batch_size):
                batch = all_unscored[i:i + batch_size]
                results = await matcher.score_batch(batch)
                for r in results:
                    await db.insert_score(
                        r["job_id"], r["score"], r["reasons"],
                        r["concerns"], r["keywords"],
                    )
                    job = await db.get_job(r["job_id"])
                    if job:
                        await _check_high_score_alerts(db, r["job_id"], r["score"], job["title"], job["company"])
                scored += len(results)
                app.state.scoring_progress = {"scored": scored, "total": total, "active": True}
                logger.info(f"Scored {scored}/{total} jobs")
        finally:
            app.state.scoring_progress = {"scored": scored, "total": total, "active": False}
            logger.info(f"Scoring complete: {scored}/{total} jobs")

    def _reinit_ai_services(client: AIClient | None, resume_text: str = ""):
        """Re-initialize matcher and tailor with new AI client."""
        app.state.ai_client = client
        if client and resume_text:
            from app.matcher import JobMatcher
            from app.tailoring import Tailor
            app.state.matcher = JobMatcher(client, resume_text)
            app.state.tailor = Tailor(client, resume_text)
        else:
            app.state.matcher = None
            app.state.tailor = None

    async def _create_follow_up_reminder(db, job_id: int, days: int = 7):
        """Auto-create a follow-up reminder N days from now when a job is marked applied."""
        from datetime import timedelta
        existing = await db.get_reminders_for_job(job_id)
        pending = [r for r in existing if r["status"] == "pending"]
        if not pending:
            remind_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            await db.create_reminder(job_id, remind_at, "follow_up")
            logger.info(f"Created follow-up reminder for job {job_id} in {days} days")

    async def _save_parsed_profile(db, profile_data: dict):
        """Save AI-parsed resume data into profile tables, merging with existing."""
        try:
            personal = profile_data.get("personal", {})
            if personal:
                clean = {k: v for k, v in personal.items() if v is not None}
                if clean:
                    existing = await db.get_user_profile() or {}
                    # Only fill in empty fields, don't overwrite user edits
                    merged = {}
                    for k, v in clean.items():
                        existing_val = existing.get(k)
                        if not existing_val or existing_val == "":
                            merged[k] = v
                    if "first_name" in clean and "last_name" in clean:
                        if not existing.get("full_name"):
                            merged["full_name"] = f"{clean['first_name']} {clean['last_name']}"
                    if merged:
                        await db.save_user_profile(**merged)

            # For list tables, only add if table is currently empty
            for key, endpoint in [
                ("work_history", "save_work_history"),
                ("education", "save_education"),
                ("certifications", "save_certification"),
                ("skills", "save_skill"),
                ("languages", "save_language"),
            ]:
                items = profile_data.get(key, [])
                if not items:
                    continue
                full = await db.get_full_profile()
                existing_items = full.get(key, [])
                if existing_items:
                    continue  # Don't overwrite existing data
                save_fn = getattr(db, endpoint)
                for item in items:
                    clean_item = {k: v for k, v in item.items() if v is not None}
                    if clean_item:
                        await save_fn(clean_item)

            logger.info("Parsed profile data saved from resume")
        except Exception as e:
            logger.error(f"Failed to save parsed profile: {e}")

    @app.get("/api/health")
    async def health():
        db: Database = app.state.db

        db_ok = False
        try:
            cursor = await db.db.execute("SELECT 1")
            await cursor.fetchone()
            db_ok = True
        except Exception:
            pass

        scheduler = getattr(app.state, "scheduler", None)
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

        ai_client = getattr(app.state, "ai_client", None)

        start = getattr(app.state, "start_time", None)
        uptime_seconds = round(_time.monotonic() - start, 1) if start else None

        body = {
            "status": "healthy" if db_ok else "unhealthy",
            "db": "ok" if db_ok else "error",
            "scheduler": scheduler_state,
            "last_scrape": last_scrape,
            "ai_provider": ai_client.provider if ai_client else None,
            "ai_configured": ai_client is not None,
            "uptime_seconds": uptime_seconds,
        }

        if not db_ok:
            return Response(
                content=json.dumps(body),
                media_type="application/json",
                status_code=503,
            )
        return body

    @app.get("/api/jobs")
    async def list_jobs(
        sort: str = Query("score"),
        limit: int = Query(50),
        offset: int = Query(0),
        min_score: int | None = Query(None),
        search: str | None = Query(None),
        source: str | None = Query(None),
        work_type: str | None = Query(None),
        employment_type: str | None = Query(None),
        location: str | None = Query(None),
        region: str | None = Query(None),
        clearance: str | None = Query(None),
        posted_within: str | None = Query(None),
    ):
        config = await app.state.db.get_search_config()
        exclude_terms = config.get("exclude_terms", []) if config else []
        jobs = await app.state.db.list_jobs(
            sort_by=sort, limit=limit, offset=offset,
            min_score=min_score, search=search, source=source,
            work_type=work_type, employment_type=employment_type,
            location=location, exclude_terms=exclude_terms,
            region=region, clearance=clearance,
            posted_within=posted_within,
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
        events = await app.state.db.get_events(job_id)
        similar = await app.state.db.find_similar_jobs(job["title"], job["company"], exclude_id=job_id)
        interview_prep = await app.state.db.get_interview_prep(job_id)
        return {**job, "score": score, "sources": sources, "application": application, "events": events, "similar": similar, "interview_prep": interview_prep}

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
            raise HTTPException(503, "Tailor not available (no AI provider configured or no resume)")

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

        await app.state.db.add_event(job_id, "prepared", "Application prepared")

        return {
            "job_id": job_id,
            "status": "prepared",
            "tailored_resume": result.get("tailored_resume", ""),
            "cover_letter": result.get("cover_letter", ""),
        }

    @app.post("/api/jobs/{job_id}/estimate-salary")
    async def estimate_salary_endpoint(job_id: int):
        from app.salary_estimator import estimate_salary
        job = await app.state.db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        client = getattr(app.state, "ai_client", None)
        if not client:
            raise HTTPException(503, "No AI provider configured")
        # Skip if salary already known from listing
        if job.get("salary_min") and job.get("salary_max"):
            return {"ok": True, "already_known": True,
                    "min": job["salary_min"], "max": job["salary_max"]}
        result = await estimate_salary(client, job)
        if result.get("min") and result["min"] > 0:
            await app.state.db.update_job_contact(job_id,
                salary_estimate_min=result["min"],
                salary_estimate_max=result["max"],
                salary_confidence=result.get("confidence", "low"),
            )
        return {"ok": True, **result}

    @app.post("/api/jobs/{job_id}/find-apply-link")
    async def find_apply_link(job_id: int):
        from app.apply_link_finder import find_apply_url
        job = await app.state.db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        url = await find_apply_url(job["url"])
        if url:
            await app.state.db.update_job_contact(job_id, apply_url=url)
        return {"ok": True, "apply_url": url}

    @app.post("/api/jobs/{job_id}/find-contact")
    async def find_contact(job_id: int):
        from app.contact_finder import find_hiring_contact
        job = await app.state.db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")

        result = await find_hiring_contact(
            job["company"], job["title"], job.get("location", "")
        )

        update = {"contact_lookup_done": 1}
        if result.get("email"):
            update["hiring_manager_email"] = result["email"]
        if result.get("name"):
            update["hiring_manager_name"] = result["name"]
        if result.get("title"):
            update["hiring_manager_title"] = result["title"]

        await app.state.db.update_job_contact(job_id, **update)

        await app.state.db.add_event(job_id, "note",
            f"Contact lookup: {'Found ' + result['email'] if result.get('email') else 'No contact found'}")

        return {"ok": True, "contact": result}

    @app.get("/api/jobs/{job_id}/resume.pdf")
    async def download_resume_pdf(job_id: int):
        from app.pdf_generator import generate_resume_pdf
        job = await app.state.db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        application = await app.state.db.get_application(job_id)
        if not application or not application.get("tailored_resume"):
            raise HTTPException(404, "No tailored resume prepared for this job")
        pdf_bytes = generate_resume_pdf(application["tailored_resume"])
        await app.state.db.add_event(job_id, "pdf_downloaded", "Resume PDF downloaded")
        filename = f"Resume - {job['company']} - {job['title']}.pdf".replace("/", "-")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/jobs/{job_id}/cover-letter.pdf")
    async def download_cover_letter_pdf(job_id: int):
        from app.pdf_generator import generate_cover_letter_pdf
        job = await app.state.db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        application = await app.state.db.get_application(job_id)
        if not application or not application.get("cover_letter"):
            raise HTTPException(404, "No cover letter prepared for this job")
        pdf_bytes = generate_cover_letter_pdf(
            application["cover_letter"],
            company=job.get("company", ""),
            position=job.get("title", ""),
        )
        await app.state.db.add_event(job_id, "pdf_downloaded", "Cover letter PDF downloaded")
        filename = f"Cover Letter - {job['company']} - {job['title']}.pdf".replace("/", "-")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

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
            to=job.get("hiring_manager_email") or job.get("contact_email"),
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

        await app.state.db.add_event(job_id, "email_drafted", "Email drafted")

        return {"job_id": job_id, "email": email}

    @app.post("/api/jobs/{job_id}/events")
    async def add_event(job_id: int, request: Request):
        job = await app.state.db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        body = await request.json()
        detail = body.get("detail", "")
        if not detail.strip():
            raise HTTPException(400, "Detail is required")
        await app.state.db.add_event(job_id, "note", detail)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/apply")
    async def apply_to_job(job_id: int):
        db = app.state.db
        job = await db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        apply_url = job.get("apply_url") or job["url"]
        await db.upsert_application(job_id, status="applied")
        await db.add_event(job_id, "applied", "Applied via CareerPulse")
        await _create_follow_up_reminder(db, job_id)
        return {"url": apply_url, "status": "applied"}

    @app.post("/api/jobs/{job_id}/generate-cover-letter")
    async def generate_cover_letter_endpoint(job_id: int):
        db = app.state.db
        client = app.state.ai_client
        if not client:
            raise HTTPException(503, "AI client not configured")

        job = await db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")

        config = await db.get_search_config()
        resume_text = config["resume_text"] if config else ""
        profile = await db.get_user_profile() or {}
        score = await db.get_score(job_id)
        match_reasons = score["match_reasons"] if score else []

        from app.cover_letter import generate_cover_letter
        result = await generate_cover_letter(
            client=client,
            job_title=job["title"],
            company=job["company"],
            job_description=job.get("description") or "",
            resume_text=resume_text,
            profile=profile,
            match_reasons=match_reasons,
        )

        app_record = await db.get_application(job_id)
        if app_record:
            await db.update_application(app_record["id"], cover_letter=result["cover_letter"])
        else:
            app_id = await db.insert_application(job_id, status="interested")
            await db.update_application(app_id, cover_letter=result["cover_letter"])

        return result

    @app.put("/api/jobs/{job_id}/cover-letter")
    async def save_cover_letter(job_id: int, request: Request):
        db = app.state.db
        job = await db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")

        body = await request.json()
        cover_letter = body.get("cover_letter", "")

        app_record = await db.get_application(job_id)
        if app_record:
            await db.update_application(app_record["id"], cover_letter=cover_letter)
        else:
            app_id = await db.insert_application(job_id, status="interested")
            await db.update_application(app_id, cover_letter=cover_letter)

        return {"ok": True}

    @app.post("/api/jobs/{job_id}/interview-prep")
    async def generate_interview_prep(job_id: int):
        db = app.state.db
        client = app.state.ai_client
        if not client:
            raise HTTPException(503, "AI client not configured")

        job = await db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")

        score = await db.get_score(job_id)
        company = await db.get_company(job["company"])
        work_history = await db.get_work_history()
        config = await db.get_search_config()
        resume_text = config["resume_text"] if config else ""

        company_context = ""
        if company:
            parts = []
            if company.get("description"):
                parts.append(f"About: {company['description']}")
            if company.get("glassdoor_rating"):
                parts.append(f"Glassdoor: {company['glassdoor_rating']}")
            company_context = "\n".join(parts)

        work_context = ""
        if work_history:
            entries = []
            for w in work_history[:5]:
                entry = f"- {w.get('job_title', '')} at {w.get('company', '')}"
                if w.get("description"):
                    entry += f": {w['description'][:200]}"
                entries.append(entry)
            work_context = "\n".join(entries)

        match_context = ""
        if score:
            reasons = score.get("match_reasons", [])
            concerns = score.get("concerns", [])
            if reasons:
                match_context += "Match strengths: " + "; ".join(reasons) + "\n"
            if concerns:
                match_context += "Concerns: " + "; ".join(concerns)

        prompt = f"""You are an interview preparation coach. Generate interview prep materials for this candidate and job.

JOB: {job['title']} at {job['company']}
DESCRIPTION: {(job.get('description') or '')[:2000]}

{f'COMPANY INFO: {company_context}' if company_context else ''}
{f'MATCH ANALYSIS: {match_context}' if match_context else ''}
{f'WORK HISTORY: {work_context}' if work_context else ''}
{f'RESUME: {resume_text[:1500]}' if resume_text else ''}

Return ONLY valid JSON with this structure:
{{
    "behavioral_questions": ["5 likely behavioral questions with brief tips"],
    "technical_questions": ["5 likely technical questions based on the job requirements"],
    "star_stories": ["3 STAR-format story outlines the candidate could prepare based on their experience"],
    "talking_points": ["5 key talking points to emphasize in the interview"]
}}"""

        from app.ai_client import parse_json_response
        raw = await client.chat(prompt, max_tokens=2048)
        prep = parse_json_response(raw)

        await db.save_interview_prep(job_id, prep)
        await db.add_event(job_id, "interview_prep", "Interview prep generated")

        return {"job_id": job_id, "prep": prep}

    @app.get("/api/jobs/{job_id}/interview-prep")
    async def get_interview_prep(job_id: int):
        prep = await app.state.db.get_interview_prep(job_id)
        if not prep:
            raise HTTPException(404, "No interview prep found")
        return {"prep": prep}

    @app.post("/api/jobs/{job_id}/application")
    async def update_application(job_id: int, status: str = Query(...), notes: str = Query("")):
        db = app.state.db
        app_row = await db.get_application(job_id)
        if not app_row:
            await db.insert_application(job_id, status)
        else:
            await db.update_application(app_row["id"], status=status, notes=notes)
        if status == "applied":
            now = datetime.now(timezone.utc).isoformat()
            app_row = await db.get_application(job_id)
            if app_row and not app_row.get("applied_at"):
                await db.update_application(app_row["id"], applied_at=now)
            await _create_follow_up_reminder(db, job_id)
        await db.add_event(job_id, "status_change", f"Status changed to {status}")
        return {"ok": True}

    @app.get("/api/reminders")
    async def get_reminders(status: str = Query(None)):
        reminders = await app.state.db.get_reminders(status=status, include_job=True)
        return {"reminders": reminders}

    @app.get("/api/reminders/due")
    async def get_due_reminders():
        due = await app.state.db.get_due_reminders()
        return {"reminders": due}

    @app.post("/api/jobs/{job_id}/reminders")
    async def create_reminder(job_id: int, request: Request):
        db = app.state.db
        job = await db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        body = await request.json()
        remind_at = body.get("remind_at")
        reminder_type = body.get("type", "follow_up")
        if not remind_at:
            raise HTTPException(400, "remind_at is required")
        rid = await db.create_reminder(job_id, remind_at, reminder_type)
        return {"ok": True, "reminder_id": rid}

    @app.post("/api/reminders/{reminder_id}/complete")
    async def complete_reminder(reminder_id: int):
        await app.state.db.complete_reminder(reminder_id)
        return {"ok": True}

    @app.post("/api/reminders/{reminder_id}/dismiss")
    async def dismiss_reminder(reminder_id: int):
        await app.state.db.dismiss_reminder(reminder_id)
        return {"ok": True}

    @app.get("/api/stats")
    async def get_stats():
        return await app.state.db.get_stats()

    @app.get("/api/analytics")
    async def get_analytics():
        return await app.state.db.get_analytics()

    @app.get("/api/skill-gaps")
    async def get_skill_gaps():
        db = app.state.db
        gap_data = await db.get_skill_gap_data(min_score=50, max_score=80)
        user_skills = await db.get_skills()
        user_skill_names = {s["name"].lower().strip() for s in user_skills if s.get("name")}
        return {
            "job_count": gap_data["job_count"],
            "top_concerns": gap_data["top_concerns"],
            "top_keywords": gap_data["top_keywords"],
            "user_skills": [s["name"] for s in user_skills],
        }

    @app.post("/api/skill-gaps/analyze")
    async def analyze_skill_gaps():
        from app.ai_client import parse_json_response
        db = app.state.db
        client = getattr(app.state, "ai_client", None)
        if not client:
            raise HTTPException(503, "AI client not configured")

        gap_data = await db.get_skill_gap_data(min_score=50, max_score=80)
        if gap_data["job_count"] == 0:
            return {"skills": [], "message": "No jobs in the 50-80 score range to analyze"}

        user_skills = await db.get_skills()
        user_skill_names = [s["name"] for s in user_skills if s.get("name")]

        prompt = f"""You are a career advisor. Analyze the skill gaps between a job seeker's current skills and the jobs they almost qualify for (scored 50-80 out of 100).

CURRENT SKILLS: {', '.join(user_skill_names) if user_skill_names else 'Not specified'}

TOP CONCERNS FROM JOB MATCHES (concern, frequency):
{chr(10).join(f'- {c}: {n} jobs' for c, n in gap_data['top_concerns'][:15])}

SUGGESTED KEYWORDS/SKILLS FROM JOB MATCHES (keyword, frequency):
{chr(10).join(f'- {k}: {n} jobs' for k, n in gap_data['top_keywords'][:15])}

TOTAL NEAR-MATCH JOBS: {gap_data['job_count']}

Return ONLY valid JSON with this structure:
{{
    "skills": [
        {{
            "name": "skill name",
            "jobs_unlocked": estimated number of additional jobs this would unlock,
            "difficulty": "low/medium/high" (how hard to learn),
            "time_estimate": "estimated time to become proficient",
            "reason": "brief explanation of why this skill matters"
        }}
    ]
}}

Rank by ROI (jobs unlocked relative to learning difficulty). Return top 5 skills."""

        raw = await client.chat(prompt, max_tokens=1024)
        result = parse_json_response(raw)
        return {
            "skills": result.get("skills", []),
            "job_count": gap_data["job_count"],
        }

    @app.get("/api/pipeline")
    async def get_pipeline():
        db = app.state.db
        stats = await db.get_pipeline_stats()
        return {"stats": stats}

    @app.get("/api/pipeline/{status}")
    async def get_pipeline_jobs(status: str):
        db = app.state.db
        jobs = await db.get_pipeline_jobs(status)
        return {"jobs": jobs, "count": len(jobs)}

    # === Notifications ===
    @app.get("/api/notifications")
    async def get_notifications(unread: bool = Query(False)):
        db = app.state.db
        notifications = await db.get_notifications(unread_only=unread)
        count = await db.get_unread_notification_count()
        return {"notifications": notifications, "unread_count": count}

    @app.post("/api/notifications/{notification_id}/read")
    async def mark_notification_read(notification_id: int):
        await app.state.db.mark_notification_read(notification_id)
        return {"ok": True}

    @app.post("/api/notifications/read-all")
    async def mark_all_read():
        await app.state.db.mark_all_notifications_read()
        return {"ok": True}

    @app.get("/api/notifications/stream")
    async def notification_stream():
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        app.state.notification_subscribers.append(queue)

        async def event_generator():
            try:
                while True:
                    notif = await queue.get()
                    yield f"data: {json.dumps(notif)}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                app.state.notification_subscribers.remove(queue)

        return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/export/csv")
    async def export_csv(
        min_score: int | None = Query(None),
        status: str | None = Query(None),
    ):
        import csv
        import io

        jobs = await app.state.db.list_jobs(sort_by="score", limit=10000)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Title", "Company", "Location", "Score", "Status",
            "Salary Min", "Salary Max", "URL", "Posted Date",
            "Contact Email", "Applied At", "Source"
        ])

        for job in jobs:
            app_row = job.get("app_status", "")
            if status and app_row != status:
                continue
            score = job.get("match_score") or 0
            if min_score and score < min_score:
                continue
            sources = await app.state.db.get_sources(job["id"])
            source_names = ", ".join(s["source_name"] for s in sources)
            application = await app.state.db.get_application(job["id"])
            writer.writerow([
                job["title"], job["company"], job.get("location", ""),
                job.get("match_score", ""), app_row,
                job.get("salary_min", ""), job.get("salary_max", ""),
                job["url"], job.get("posted_date", ""),
                job.get("contact_email", ""),
                application.get("applied_at", "") if application else "",
                source_names,
            ])

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="careerpulse-export.csv"'},
        )

    @app.get("/api/digest")
    async def get_digest(
        min_score: int = Query(60),
        hours: int = Query(24),
    ):
        from app.digest import generate_digest
        return await generate_digest(app.state.db, min_score, hours)

    @app.post("/api/digest/send-test")
    async def send_digest_test():
        from app.digest import send_digest
        success = await send_digest(app.state.db)
        if not success:
            raise HTTPException(400, "Digest not sent — check email settings and digest configuration")
        return {"ok": True, "message": "Digest sent"}

    @app.get("/api/settings/email")
    async def get_email_settings():
        settings = await app.state.db.get_email_settings()
        if settings:
            settings.pop("smtp_password", None)
        return settings or {}

    @app.post("/api/settings/email")
    async def save_email_settings(request: Request):
        data = await request.json()
        existing = await app.state.db.get_email_settings()
        if data.get("smtp_password") == "" and existing:
            data["smtp_password"] = existing.get("smtp_password", "")
        await app.state.db.update_email_settings(data)

        # Update digest scheduler job time if changed
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler and scheduler.running:
            digest_time = data.get("digest_time", "08:00")
            try:
                hour, minute = digest_time.split(":")
                scheduler.reschedule_job("digest_cycle", trigger="cron", hour=int(hour), minute=int(minute))
            except Exception:
                pass

        return {"ok": True}

    @app.post("/api/settings/email/test")
    async def test_email_settings(request: Request):
        from app.emailer import send_email
        data = await request.json()
        existing = await app.state.db.get_email_settings()
        if data.get("smtp_password") == "" and existing:
            data["smtp_password"] = existing.get("smtp_password", "")
        test_to = data.get("from_address", "")
        if not test_to:
            raise HTTPException(400, "From address required for test")
        success = await send_email(
            data,
            to=test_to,
            subject="CareerPulse SMTP Test",
            body_text="Your SMTP settings are configured correctly.",
            body_html="<p>Your SMTP settings are configured correctly.</p>",
        )
        if not success:
            raise HTTPException(500, "Failed to send test email — check SMTP settings")
        return {"ok": True, "message": f"Test email sent to {test_to}"}

    @app.post("/api/jobs/{job_id}/send-email")
    async def send_job_email(job_id: int):
        from app.emailer import send_application_email
        email_settings = await app.state.db.get_email_settings()
        if not email_settings or not email_settings.get("smtp_host"):
            raise HTTPException(400, "SMTP not configured")
        application = await app.state.db.get_application(job_id)
        if not application or not application.get("email_draft"):
            raise HTTPException(400, "No email draft for this job")
        email_draft = json.loads(application["email_draft"])
        success = await send_application_email(email_settings, email_draft)
        if not success:
            raise HTTPException(500, "Failed to send email")
        await app.state.db.add_event(job_id, "email_sent", f"Email sent to {email_draft.get('to', '')}")
        return {"ok": True, "message": "Email sent"}

    @app.post("/api/clear-jobs")
    async def clear_jobs():
        await app.state.db.clear_jobs()
        return {"ok": True, "message": "All jobs, scores, and applications cleared"}

    @app.post("/api/clear-all")
    async def clear_all():
        await app.state.db.clear_all()
        app.state.matcher = None
        app.state.tailor = None
        return {"ok": True, "message": "All data cleared"}

    @app.post("/api/scrape")
    async def trigger_scrape():
        async def _scrape_and_score():
            try:
                from app.scrapers import ALL_SCRAPERS
                from app.scheduler import run_scrape_cycle, run_enrichment_cycle

                db = app.state.db
                config = await db.get_search_config()
                terms = config["search_terms"] if config else []
                keys = await db.get_scraper_keys()
                scrapers = [s(search_terms=terms, scraper_keys=keys) for s in ALL_SCRAPERS]
                app.state.scrape_progress = {"completed": 0, "total": len(scrapers), "current": None, "new_jobs": 0, "active": True}
                await run_scrape_cycle(db, scrapers, search_terms=terms, progress=app.state.scrape_progress, scraper_keys=keys)

                await run_enrichment_cycle(db)
                await _score_unscored(db)
            except Exception:
                logger.exception("Background scrape+score failed")
                if app.state.scrape_progress:
                    app.state.scrape_progress["active"] = False

        asyncio.create_task(_scrape_and_score())
        return {"status": "triggered"}

    @app.get("/api/scrape/progress")
    async def scrape_progress():
        progress = app.state.scrape_progress
        if not progress:
            return {"active": False, "completed": 0, "total": 0, "current": None, "new_jobs": 0}
        return progress

    @app.post("/api/jobs/enrich")
    async def enrich_jobs():
        from app.scheduler import run_enrichment_cycle
        enriched = await run_enrichment_cycle(app.state.db, limit=50)
        return {"enriched": enriched}

    @app.post("/api/score")
    async def trigger_score():
        async def _run_scoring():
            try:
                await _score_unscored(app.state.db)
            except Exception:
                logger.exception("Background scoring failed")

        asyncio.create_task(_run_scoring())
        return {"status": "scoring_triggered"}

    @app.get("/api/score/progress")
    async def score_progress():
        progress = app.state.scoring_progress
        if not progress:
            return {"active": False, "scored": 0, "total": 0}
        return progress

    @app.get("/api/profile")
    async def get_profile():
        profile = await app.state.db.get_user_profile()
        return profile or {"full_name": "", "email": "", "phone": "", "location": "",
                            "linkedin_url": "", "github_url": "", "portfolio_url": ""}

    @app.post("/api/profile")
    async def update_profile(request: Request):
        body = await request.json()
        # save_user_profile dynamically checks table columns, so pass all fields
        body.pop("id", None)
        body.pop("updated_at", None)
        await app.state.db.save_user_profile(**body)
        return {"ok": True}

    @app.get("/api/profile/full")
    async def get_full_profile():
        return await app.state.db.get_full_profile()

    @app.put("/api/profile/full")
    async def update_full_profile(request: Request):
        body = await request.json()
        await app.state.db.save_full_profile(body)
        return {"ok": True}

    @app.post("/api/profile/learn")
    async def learn_from_autofill(request: Request):
        body = await request.json()
        job_url = body.get("job_url", "")
        job_title = body.get("job_title", "")
        company = body.get("company", "")
        new_data = body.get("new_data", {})

        if new_data:
            existing = await app.state.db.get_user_profile() or {}
            existing.pop("id", None)
            existing.pop("updated_at", None)
            updated = {k: v for k, v in new_data.items() if v}
            existing.update(updated)
            await app.state.db.save_user_profile(**existing)

        await app.state.db.save_autofill_history(
            job_url=job_url, job_title=job_title, company=company,
            new_data_saved=new_data,
        )
        return {"ok": True}

    @app.get("/api/custom-qa")
    async def list_custom_qa():
        return {"items": await app.state.db.get_custom_qa()}

    @app.post("/api/custom-qa")
    async def save_custom_qa(request: Request):
        body = await request.json()
        qa_id = await app.state.db.save_custom_qa(body)
        return {"ok": True, "id": qa_id}

    @app.delete("/api/custom-qa/{qa_id}")
    async def delete_custom_qa(qa_id: int):
        await app.state.db.delete_custom_qa(qa_id)
        return {"ok": True}

    @app.post("/api/autofill/analyze")
    async def analyze_form(request: Request):
        body = await request.json()
        form_html = body.get("form_html", "")
        form_fields = body.get("fields", [])
        page_url = body.get("page_url", "")

        client = getattr(app.state, "ai_client", None)
        if not client:
            return {"mappings": [], "error": "No AI provider configured"}

        profile = await app.state.db.get_full_profile()
        custom_qa = await app.state.db.get_custom_qa()

        profile_summary = json.dumps(profile, default=str, indent=2)
        qa_summary = json.dumps(custom_qa, default=str) if custom_qa else "[]"
        fields_summary = json.dumps(form_fields[:200], default=str, indent=2) if form_fields else ""

        prompt = _build_form_analysis_prompt(
            profile_summary=profile_summary,
            qa_summary=qa_summary,
            fields_summary=fields_summary,
            form_html=form_html,
            page_url=page_url,
        )

        try:
            response = await client.chat(prompt, max_tokens=4000)
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0]
            mappings = json.loads(text)
            return {"mappings": mappings}
        except json.JSONDecodeError:
            return {"mappings": [], "error": "Failed to parse AI response"}
        except Exception as e:
            logger.error(f"Autofill analyze failed: {e}")
            raise HTTPException(500, f"Analysis failed: {str(e)}")

    @app.get("/api/autofill/history")
    async def get_autofill_history(limit: int = Query(50)):
        return {"items": await app.state.db.get_autofill_history(limit=limit)}

    # Work History CRUD
    @app.post("/api/work-history")
    async def save_work_history(request: Request):
        body = await request.json()
        entry_id = await app.state.db.save_work_history(body)
        return {"ok": True, "id": entry_id}

    @app.delete("/api/work-history/{entry_id}")
    async def delete_work_history(entry_id: int):
        await app.state.db.delete_work_history(entry_id)
        return {"ok": True}

    # Education CRUD
    @app.post("/api/education")
    async def save_education(request: Request):
        body = await request.json()
        entry_id = await app.state.db.save_education(body)
        return {"ok": True, "id": entry_id}

    @app.delete("/api/education/{entry_id}")
    async def delete_education(entry_id: int):
        await app.state.db.delete_education(entry_id)
        return {"ok": True}

    # Certifications CRUD
    @app.post("/api/certifications")
    async def save_certification(request: Request):
        body = await request.json()
        entry_id = await app.state.db.save_certification(body)
        return {"ok": True, "id": entry_id}

    @app.delete("/api/certifications/{entry_id}")
    async def delete_certification(entry_id: int):
        await app.state.db.delete_certification(entry_id)
        return {"ok": True}

    # Skills CRUD
    @app.post("/api/skills")
    async def save_skill(request: Request):
        body = await request.json()
        entry_id = await app.state.db.save_skill(body)
        return {"ok": True, "id": entry_id}

    @app.delete("/api/skills/{entry_id}")
    async def delete_skill(entry_id: int):
        await app.state.db.delete_skill(entry_id)
        return {"ok": True}

    # Languages CRUD
    @app.post("/api/languages")
    async def save_language(request: Request):
        body = await request.json()
        entry_id = await app.state.db.save_language(body)
        return {"ok": True, "id": entry_id}

    @app.delete("/api/languages/{entry_id}")
    async def delete_language(entry_id: int):
        await app.state.db.delete_language(entry_id)
        return {"ok": True}

    # References CRUD
    @app.post("/api/references")
    async def save_reference(request: Request):
        body = await request.json()
        entry_id = await app.state.db.save_reference(body)
        return {"ok": True, "id": entry_id}

    @app.delete("/api/references/{entry_id}")
    async def delete_reference(entry_id: int):
        await app.state.db.delete_reference(entry_id)
        return {"ok": True}

    @app.get("/api/search-config")
    async def get_search_config():
        config = await app.state.db.get_search_config()
        if not config:
            return {"resume_text": "", "search_terms": [], "job_titles": [],
                    "key_skills": [], "seniority": "", "summary": "",
                    "ats_score": 0, "ats_issues": [], "ats_tips": [],
                    "exclude_terms": [], "updated_at": None}
        return config

    @app.post("/api/search-config/terms")
    async def update_search_terms(request: Request):
        body = await request.json()
        terms = body.get("search_terms", [])
        if not isinstance(terms, list):
            raise HTTPException(400, "search_terms must be a list")
        await app.state.db.update_search_terms(terms)
        return {"ok": True, "search_terms": terms}

    @app.post("/api/search-config/exclude-terms")
    async def update_exclude_terms(request: Request):
        body = await request.json()
        terms = body.get("exclude_terms", [])
        if not isinstance(terms, list):
            raise HTTPException(400, "exclude_terms must be a list")
        await app.state.db.update_exclude_terms(terms)
        return {"ok": True, "exclude_terms": terms}

    @app.get("/api/ai-settings")
    async def get_ai_settings():
        settings = await app.state.db.get_ai_settings()
        if not settings:
            env_key = getattr(getattr(app.state, "settings", None), "anthropic_api_key", "") or ""
            return {
                "provider": "anthropic" if env_key else "",
                "api_key": _mask_key(env_key),
                "model": "",
                "base_url": "",
                "has_key": bool(env_key),
                "updated_at": None,
            }
        return {
            "provider": settings["provider"],
            "api_key": _mask_key(settings["api_key"]),
            "model": settings["model"],
            "base_url": settings["base_url"],
            "has_key": bool(settings["api_key"]),
            "updated_at": settings["updated_at"],
        }

    @app.post("/api/ai-settings")
    async def update_ai_settings(request: Request):
        body = await request.json()
        provider = body.get("provider", "anthropic")
        api_key = body.get("api_key", "")
        model = body.get("model", "")
        base_url = body.get("base_url", "")

        from app.ai_client import ALL_PROVIDERS
        if provider not in ALL_PROVIDERS:
            raise HTTPException(400, f"Provider must be one of: {', '.join(ALL_PROVIDERS)}")

        # If api_key is masked (starts with ****), keep existing key
        if api_key.startswith("****"):
            existing = await app.state.db.get_ai_settings()
            if existing:
                api_key = existing["api_key"]
            else:
                env_key = getattr(getattr(app.state, "settings", None), "anthropic_api_key", "") or ""
                api_key = env_key

        await app.state.db.save_ai_settings(provider, api_key, model, base_url)

        # Re-initialize AI services
        client = _build_ai_client({"provider": provider, "api_key": api_key,
                                    "model": model, "base_url": base_url})
        config = await app.state.db.get_search_config()
        resume_text = config.get("resume_text", "") if config else ""
        _reinit_ai_services(client, resume_text)

        return {"ok": True, "provider": provider, "model": model}

    @app.get("/api/ai-settings/models")
    async def list_ollama_models(base_url: str = Query("http://localhost:11434")):
        """Fetch available models from an Ollama instance."""
        import httpx
        from app.ai_client import _resolve_ollama_url
        url = f"{_resolve_ollama_url(base_url).rstrip('/')}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                models = [m["name"] for m in data.get("models", [])]
                return {"ok": True, "models": models}
        except Exception as e:
            return {"ok": False, "models": [], "error": str(e)}

    @app.post("/api/ai-settings/test")
    async def test_ai_connection(request: Request):
        body = await request.json()
        provider = body.get("provider", "anthropic")
        api_key = body.get("api_key", "")
        model = body.get("model", "")
        base_url = body.get("base_url", "")

        if api_key.startswith("****"):
            existing = await app.state.db.get_ai_settings()
            if existing:
                api_key = existing["api_key"]
            else:
                env_key = getattr(getattr(app.state, "settings", None), "anthropic_api_key", "") or ""
                api_key = env_key

        try:
            client = AIClient(provider, api_key=api_key, model=model, base_url=base_url)
            response = await client.chat("Reply with exactly: OK", max_tokens=10)
            return {"ok": True, "response": response.strip()[:50]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/scraper-keys")
    async def get_scraper_keys():
        keys = await app.state.db.get_scraper_keys()
        result = {}
        for name, data in keys.items():
            result[name] = {
                "has_key": bool(data["api_key"]),
                "email": data["email"],
            }
        return result

    @app.post("/api/scraper-keys")
    async def save_scraper_keys(request: Request):
        body = await request.json()
        for name, data in body.items():
            api_key = data.get("api_key", "")
            email = data.get("email", "")
            if api_key.startswith("****"):
                existing = await app.state.db.get_scraper_key(name)
                if existing:
                    api_key = existing["api_key"]
                else:
                    api_key = ""
            await app.state.db.save_scraper_key(name, api_key, email)
        return {"ok": True}

    @app.get("/api/scraper-schedule")
    async def get_scraper_schedule():
        db = app.state.db
        schedules = await db.get_all_scraper_schedules()
        return {"schedules": schedules}

    @app.post("/api/scraper-schedule")
    async def update_scraper_schedule(request: Request):
        data = await request.json()
        db = app.state.db
        source_name = data.get("source_name")
        interval_hours = data.get("interval_hours")
        if not source_name or interval_hours is None:
            raise HTTPException(400, "source_name and interval_hours required")
        await db.update_scraper_schedule(source_name, int(interval_hours))
        return {"ok": True}

    @app.post("/api/resume/upload")
    async def upload_resume(file: UploadFile = File(...)):
        content = await file.read()
        filename = (file.filename or "").lower()

        if filename.endswith(".pdf"):
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            resume_text = "\n".join(page.get_text() for page in doc)
            doc.close()
        else:
            resume_text = content.decode("utf-8", errors="replace")

        client = getattr(app.state, "ai_client", None)
        if not client and not getattr(app.state, "testing", False):
            ai_settings = await app.state.db.get_ai_settings()
            env_key = getattr(getattr(app.state, "settings", None), "anthropic_api_key", "") or ""
            client = _build_ai_client(ai_settings, env_key)

        analysis = {"search_terms": [], "job_titles": [], "key_skills": [],
                    "seniority": "", "summary": "", "ats_score": 0, "ats_issues": [], "ats_tips": []}
        profile_data = {}
        logger.info(f"Resume upload: {len(resume_text)} chars, client={'yes' if client else 'no'}")
        if client:
            from app.resume_analyzer import analyze_resume, parse_resume_to_profile
            analysis_task = analyze_resume(client, resume_text)
            profile_task = parse_resume_to_profile(client, resume_text)
            analysis, profile_data = await asyncio.gather(analysis_task, profile_task)
            logger.info(f"Analysis result: ats_score={analysis.get('ats_score')}, terms={len(analysis.get('search_terms', []))}")
            logger.info(f"Profile parse: {len(profile_data)} sections extracted")

            _reinit_ai_services(client, resume_text)

        await app.state.db.save_search_config(
            resume_text,
            analysis["search_terms"],
            job_titles=analysis["job_titles"],
            key_skills=analysis["key_skills"],
            seniority=analysis.get("seniority", ""),
            summary=analysis.get("summary", ""),
            ats_score=analysis.get("ats_score", 0),
            ats_issues=analysis.get("ats_issues", []),
            ats_tips=analysis.get("ats_tips", []),
        )

        if profile_data:
            await _save_parsed_profile(app.state.db, profile_data)

        return {
            "ok": True,
            "search_terms": analysis["search_terms"],
            "job_titles": analysis["job_titles"],
            "key_skills": analysis["key_skills"],
            "seniority": analysis.get("seniority", ""),
            "summary": analysis.get("summary", ""),
            "ats_score": analysis.get("ats_score", 0),
            "ats_issues": analysis.get("ats_issues", []),
            "ats_tips": analysis.get("ats_tips", []),
            "resume_length": len(resume_text),
            "profile_parsed": bool(profile_data),
        }

    @app.get("/api/companies/{company_name:path}")
    async def get_company_info(company_name: str):
        from app.company_research import research_company
        # Check cache first
        cached = await app.state.db.get_company(company_name)
        if cached:
            return cached
        # Fetch and cache
        info = await research_company(company_name)
        fields = {}
        if info.get("description"):
            fields["description"] = info["description"]
        if info.get("website"):
            fields["website"] = info["website"]
        if info.get("glassdoor_rating"):
            fields["glassdoor_rating"] = info["glassdoor_rating"]
        if info.get("size"):
            fields["size"] = info["size"]
        if info.get("industry"):
            fields["industry"] = info["industry"]
        if fields:
            await app.state.db.save_company(company_name, **fields)
        return await app.state.db.get_company(company_name) or info

    if not testing:
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        if os.path.exists(static_dir):
            app.mount("/static", StaticFiles(directory=static_dir), name="static")

            @app.get("/")
            async def index():
                return FileResponse(os.path.join(static_dir, "index.html"))

    return app


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"****{key[-4:]}"
