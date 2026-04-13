# CareerPulse (JobFinder)

Job discovery, matching, and application management platform — scrapes job boards, scores listings against resume with AI, generates tailored resumes/cover letters, tracks applications through a CRM pipeline, and automates follow-ups.

## Running the App
```bash
# Development (uv auto-manages venv and deps)
uv run uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8085

# Docker
docker compose up -d
```

## Tech Stack
- Python (FastAPI), aiosqlite
- AI: Anthropic, OpenAI, Google, OpenRouter, Ollama (configurable via settings UI)
- APScheduler for periodic scraping
- Vanilla JS frontend (served from `app/static/`)

## Key Architecture
- `app/main.py` — FastAPI app assembler: `create_app` factory + lifespan (378 lines); initializes dual DB connections: `app.state.db` for request handlers, `app.state.bg_db` for background tasks (prevents connection contention); lifespan resets `app.state.scrape_progress = None` and `app.state.scrape_task = None` on startup (stale-state guard — ensures `active` is never `true` from a crashed previous run)
- `app/routers/` — API routes split into 12 modules: `jobs.py`, `tailoring.py`, `pipeline.py`, `queue.py`, `contacts.py`, `analytics.py`, `settings.py`, `alerts.py`, `scraping.py`, `autofill.py`, `interviews.py`, `calendar.py`
  - `scraping.py`: implements the Scrape Now phase pipeline (design: `docs/plans/2026-04-12-robust-scrape-now-design.md`); phases: `scraping → enriching → classifying → scoring → done/error`; `_set_phase()` transitions state and bumps `last_updated_at` heartbeat; `_fresh_state()` initializes `scrape_progress` per run; **concurrency guard**: `POST /api/scrape` returns `409 {"error": "scrape_already_running", "task_id": ...}` if `scrape_progress.active` is true — `app.state.scrape_lock` is removed; **cancel**: `POST /api/scrape/cancel` calls `scrape_task.cancel()`, catches `CancelledError` → sets `phase="error"`, appends `"Cancelled by user"` to errors, returns `404` if no active scrape; `GET /api/scrape/progress` returns full state plus `server_now` (monotonic) so the client can compute stall duration without a shared clock; `scrape_progress` shape: `{active, phase, started_at, last_updated_at, current, completed, total, new_jobs, sources: [{name, status, listings_found, new_jobs, error, duration_ms}], scoring: {scored, total, skipped_reason}, errors, task_id}`; router owns `active`/`phase` — `run_scrape_cycle` never touches them
  - `interviews.py`: interview rounds CRUD per application; promote-to-contact endpoint links interviewers to the contacts CRM
  - `calendar.py`: calendar events API aggregates interviews + application deadlines; `GET /api/calendar/ical` serves an iCal feed for external calendar subscriptions
- `app/database.py` — async SQLite via aiosqlite (37 tables, FK enforcement, WAL mode); `jobs.last_seen_at` updated each scrape cycle, drives freshness filtering and 30-day auto-dismiss
- `app/scrapers/` — job board scrapers (pluggable, 14 active sources); base class provides retry/backoff, rate limiting, UA rotation
- `app/matcher.py` — AI-powered job/resume matching (supports resume override)
- `app/tailoring.py` — generates tailored resumes/cover letters (supports resume override)
- `app/ai_client.py` — multi-provider AI client (Anthropic, OpenAI, Google, OpenRouter, Ollama)
- `app/pdf_generator.py` — resume/cover letter PDF output
- `app/docx_generator.py` — resume/cover letter DOCX output
- `app/scheduler.py` — 8 periodic background jobs (scrape, enrich, score, maintain, remind, digest, alert, embed); `PER_SCRAPER_TIMEOUT = 120` wraps each `scraper.scrape()` call via `asyncio.wait_for` — a single hung source is marked `timeout` and skipped without blocking the cycle; `run_scrape_cycle` never touches `active` or `phase` — the router owns lifecycle; heartbeat (`last_updated_at`) is bumped every 25 listings inside the insert loop so large payloads don't trip client-side stall detection
- `app/digest.py` / `app/emailer.py` — email digest notifications
- `app/follow_up.py` — AI-drafted follow-up emails
- `app/predictor.py` — application success prediction
- `app/career_advisor.py` — career trajectory AI analysis
- `app/offer_calculator.py` — offer comparison with cost-of-living normalization
- `app/static/js/app.js` — SPA router, mobile hamburger nav, keyboard shortcuts
- `app/static/js/api.js` — centralized API client
- `app/static/js/utils.js` — HTML sanitization (`escapeHtml`, `sanitizeHtml`, `sanitizeUrl`), shared helpers
- `app/static/js/onboarding.js` — 4-step first-run wizard (profile → resume → AI provider → scrape)
- `app/static/js/views/` — 9 view modules: `feed.js`, `detail.js`, `pipeline.js`, `queue.js`, `stats.js`, `settings.js`, `network.js`, `triage.js`, `calendar.js`
  - `calendar.js`: monthly grid + agenda toggle; renders interview rounds and application events; iCal subscription button
- `app/static/js/interview-panel.js` — interview detail slide-out panel; displays round history, outcome logging, promote-to-contact action, and embedded salary calculator
- `app/static/js/salary-calculator.js` — client-side salary calculator (W2/1099/C2C, tax estimation by state, Chart.js visualizations)
- `app/static/js/tax-data.js` — 2025 federal + all 50 state tax brackets and FICA rates
- `extension/` — Chrome extension (Manifest V3): autofill, job board overlays, queue orchestration

## Environment Variables
Required in `.env` (all optional — can configure via UI instead):
- `JOBFINDER_ANTHROPIC_API_KEY` — AI scoring key (Anthropic); use UI for other providers
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — AWS credentials for Bedrock provider (or use `~/.aws/credentials`, instance profile, etc.)
- `JOBFINDER_USAJOBS_API_KEY` — USAJobs.gov API key (optional, for federal listings)
- `JOBFINDER_DB_PATH` — default: `data/jobfinder.db`
- `JOBFINDER_RESUME_PATH` — default: `data/resume.txt`
- `JOBFINDER_SCRAPE_INTERVAL_HOURS` — default: `6`
- `JOBFINDER_MIN_SALARY` — default: `150000` (annual FTE filter)
- `JOBFINDER_MIN_HOURLY_RATE` — default: `95` (contract rate filter)
- `JOBFINDER_HOST` — default: `0.0.0.0`
- `JOBFINDER_PORT` — default: `8085`

## Testing
```bash
uv run pytest                             # 655 backend tests
cd app/static && npx vitest run           # 140 frontend tests
cd extension && npx vitest run            # 453 extension tests
```
Total: 1,248 tests

CI runs all three suites in parallel on push/PR to main: `.github/workflows/ci.yml`

## Git Remote
- **GitHub**: `https://github.com/tcpsyn/CareerPulse.git` (origin)
