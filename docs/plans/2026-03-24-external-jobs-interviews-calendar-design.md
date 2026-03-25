# External Jobs, Interview Tracking & Calendar

**Date:** 2026-03-24
**Status:** Approved

## Overview

Allow users to add jobs not found through CareerPulse to the pipeline, track interview rounds with numbered stages, and view upcoming interviews/reminders on a dedicated calendar with iCal subscription support.

## Data Model

New `interview_rounds` table:

```sql
interview_rounds (
  id            INTEGER PRIMARY KEY,
  job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  round_number  INTEGER NOT NULL,
  label         TEXT NOT NULL DEFAULT '',
  scheduled_at  TEXT,
  duration_min  INTEGER DEFAULT 60,
  interviewer_name  TEXT DEFAULT '',
  interviewer_title TEXT DEFAULT '',
  contact_id    INTEGER REFERENCES contacts(id),
  location      TEXT DEFAULT '',
  notes         TEXT DEFAULT '',
  status        TEXT DEFAULT 'scheduled',  -- scheduled | completed | cancelled
  created_at    TEXT NOT NULL
)
```

New `ical_tokens` table:

```sql
ical_tokens (
  id         INTEGER PRIMARY KEY,
  token      TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
)
```

No changes to existing tables. Jobs with interview rounds have application status "interviewing".

## API Endpoints

### Interview Rounds
- `GET /api/jobs/{job_id}/interviews` — list all rounds for a job
- `POST /api/jobs/{job_id}/interviews` — create round (auto-assigns next round_number)
- `PUT /api/interviews/{id}` — update round
- `DELETE /api/interviews/{id}` — remove round

### Calendar
- `GET /api/calendar?start=ISO&end=ISO` — all events in range (interviews + reminders)
- `GET /api/calendar.ics?token=<token>` — iCal subscription feed

### Add External Job (enhanced)
- Existing `POST /api/jobs/save-external` gets `fetch_description: true` option
- Auto-fetches title, company, description from URL; falls back silently on failure

### Promote Interviewer
- `POST /api/interviews/{id}/save-contact` — creates contact from interviewer name/title, links to round and job

## Calendar View

New top-level nav item `#/calendar` between Pipeline and Stats.

### Layout
- Monthly grid with day cells
- Dots/chips on days with events, color-coded: interviews (blue), reminders (amber), deadlines (red)
- Click day to expand and see events
- Event chip: "2:00 PM — Dropbox — Round 2: Technical"
- Click event opens interview detail panel

### Agenda Sidebar
- Right side shows next 7 days of events chronologically
- Quick-add interview button per job

### Top Bar
- Month navigation (prev/next, today button)
- "Subscribe" button shows iCal URL with copy-to-clipboard
- Revoke/regenerate token button

## Interview Detail Panel

Opened when clicking an interview from pipeline or calendar. Split view:

### Left Side — Interview Info
- Round number + label, date/time, interviewer name/title
- Location/link (clickable for Zoom/Meet URLs)
- Notes, status controls (scheduled/completed/cancelled)
- Link to full job detail

### Right Side — Compensation Snapshot
- Pre-populated salary calculator using job's salary_min/max or salary_estimate
- Employment type auto-set from job tags (contract vs FTE)
- Shows: gross annual, estimated taxes, net take-home
- Contract jobs: hourly rate breakdown, W2 vs 1099 vs C2C comparison
- Editable (tweak numbers without affecting saved job data)

Reuses existing `salary-calculator.js` logic in compact read-only-by-default mode with "Edit" toggle.

## Add External Job Modal

Triggered by "Add Job" button in pipeline kanban header.

### Fields
- **URL** — on blur/paste, auto-fetches title, company, description
- **Title** (required) — pre-filled from fetch
- **Company** (required) — pre-filled from fetch
- **Description** (textarea) — pre-filled, editable
- **Location** (optional)
- **Salary** min/max (optional)
- **Initial Status** dropdown — defaults to "interested"
- **Add First Interview** toggle — expands: label, datetime picker, interviewer name/title, location/link

### Fetch Behavior
- Auto-fetch on URL blur using existing enrichment extractors
- Success: populate fields, green checkmark
- Failure: silently leave empty, no error
- User can always override fetched values

## Interview Rounds in Job Detail

New "Interviews" section below existing job info for pipeline jobs.

### Timeline
- Vertical timeline sorted by round_number
- Card: "Round 1: Phone Screen" header, date/time, interviewer, location/link, status badge, notes
- Completed = checkmark, cancelled = strikethrough

### Actions
- Edit round (reschedule, update notes, change status)
- "Save to Network" next to interviewer name — promotes to contact
- Delete round
- "Add Interview Round" button at bottom with inline form
- Label suggestions: Phone Screen, Technical, Culture Fit, HR, Hiring Manager, Panel, Final (or type custom)
- Round number auto-assigned

### Status Sync
- Adding first interview round auto-moves application to "interviewing"
- Completing all rounds does NOT auto-advance (user decides outcome)

## iCal Feed

### Endpoint
`GET /api/calendar.ics?token=<token>`

### Token
- 32-char random hex, stored in `ical_tokens` table
- Generated on first calendar view visit or via "Subscribe" button
- Regenerate invalidates old token

### Contents
- `VCALENDAR` with `VEVENT` entries for:
  - Interview rounds (scheduled only): "Round N: Label — Company"
  - Reminders (pending only): "Follow-up: Company — Job Title"
- Fields: `UID` (type+id), `DTSTAMP`, `DTSTART`, `DTEND`, `SUMMARY`, `DESCRIPTION`, `LOCATION`
- `PRODID: -//CareerPulse//Calendar//EN`

### Headers
- `Content-Type: text/calendar`
- `Cache-Control: no-cache`

## Testing

### Backend (~40-50 tests)
- Interview rounds CRUD, auto-increment round_number
- Round number gaps (delete round 2 of 3, next is 4)
- Status sync (first interview → "interviewing")
- Calendar endpoint date range filtering, interviews + reminders combined
- iCal feed: valid .ics, correct VEVENTs, token auth, invalid token → 401
- External job save: fetch success, fetch failure fallback, invalid URL
- Promote interviewer: creates contact, links to job, idempotent

### Frontend (~15-20 tests)
- Calendar view: month grid, event chips, navigation
- Add external job modal: form validation, fetch behavior
- Interview timeline rendering in detail view
- Interview detail panel with salary calculator pre-population
- Pipeline kanban drag-and-drop regression

### Integration
- Full flow: add external job → add interviews → calendar view → iCal subscribe → complete rounds
- Existing pipeline tests pass (no schema breaks)
