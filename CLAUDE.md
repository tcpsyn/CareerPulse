# CareerPulse (JobFinder)

Job discovery and matching platform — scrapes job boards, scores listings against resume with AI, generates tailored resumes/cover letters.

## Running the App
```bash
# Development (uv auto-manages venv and deps)
uv run uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8085

# Docker
docker compose up -d
```

## Tech Stack
- Python (FastAPI), aiosqlite
- AI: Anthropic/OpenAI (configurable via settings UI)
- APScheduler for periodic scraping
- Vanilla JS frontend (served from `app/static/`)

## Key Architecture
- `app/main.py` — FastAPI app with lifespan, routes
- `app/database.py` — async SQLite via aiosqlite
- `app/scrapers/` — job board scrapers (pluggable)
- `app/matcher.py` — AI-powered job/resume matching
- `app/tailoring.py` — generates tailored resumes/cover letters
- `app/ai_client.py` — multi-provider AI client (Anthropic, OpenAI, Ollama)
- `app/pdf_generator.py` — resume/cover letter PDF output
- `app/scheduler.py` — periodic scrape cycles
- `app/digest.py` / `app/emailer.py` — email digest notifications

## Environment Variables
Required in `.env`:
- `JOBFINDER_ANTHROPIC_API_KEY` — AI scoring (or configure via UI)
- `JOBFINDER_DB_PATH` — default: `data/jobfinder.db`
- `JOBFINDER_RESUME_PATH` — default: `data/resume.txt`
- `JOBFINDER_SCRAPE_INTERVAL_HOURS` — default: 6

## Testing
```bash
uv run pytest
```

## Git Remote
- **GitHub**: `https://github.com/tcpsyn/CareerPulse.git` (origin)
