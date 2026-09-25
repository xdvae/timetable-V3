# UniSchedule

UniSchedule is a university timetable management and generation system. Administrators manage
scheduling data — configuration, rooms, faculty, programs, enrollments, sections, subjects, and
teaching assignments — and the system generates a conflict-free timetable with Google OR-Tools
CP-SAT, viewable by section, faculty member, or room and exportable as Excel, CSV, or printable
HTML.

The project has one browser frontend and one backend:

- **Flask backend** (`backend/app.py`, `backend/api_routes.py`, `backend/models.py`,
  `backend/scheduler.py`, …) — the scheduling engine, the database, the JSON API,
  file exports/sample downloads, and (in production) the React static bundle.
- **React frontend** (`frontend/`) — the administrative UI, communicating with Flask
  over same-origin `/api/*` requests (plus same-origin export/download URLs).

## Overview

The core scheduling problem: given rooms (with capacity and type), faculty (with availability
and workload limits), student groups (sections split into lab groups), subjects, teaching
assignments, working days, periods, lunch-break rules, and consecutive-teaching limits, produce
a weekly timetable in which no room, faculty member, or student group is ever double-booked.

Backend responsibilities:

- **Flask** — HTTP routes for the JSON API, file exports/sample downloads, and the
  React production bundle.
- **SQLAlchemy** — ORM over the application database (SQLite file by default).
- **Flask-Login** — session-cookie authentication (single admin login per deployment).
- **OR-Tools CP-SAT** — the constraint solver behind timetable generation.

Frontend responsibilities (React application in `frontend/`):

- **React + Vite + JavaScript** with the **React Compiler** enabled.
- **React Router** — client-side routing mirroring the backend's page structure.
- **Tailwind CSS v4 + shadcn/ui + Radix primitives + Lucide React** — design system and
  accessible UI components. No TypeScript, no Axios, no TanStack Query.

## Architecture

```text
Browser
   │
   ▼
React frontend (frontend/)
   │  same-origin /api/* (session cookie, no tokens)
   │  same-origin /export/* and /import/sample/* downloads
   ▼
Flask (backend/app.py, served as backend.app:app)
   ├── JSON API layer (backend/api_routes.py)
   ├── Export / sample-download routes
   ├── React production bundle (frontend/dist/, SPA fallback)
   │
   ├── SQLAlchemy / database (backend/models.py, backend/instance/timetable.db)
   │
   └── Scheduler / OR-Tools (backend/scheduler.py)
```

The React application is the browser frontend. The Flask application exposes the JSON
API under `/api/*`, serves timetable exports under `/export/*` and sample CSVs under
`/import/sample/*` (both called directly by React as same-origin downloads), and — in
production — serves the React production build with an SPA fallback. The React
timetable uses custom CSS Grid (not FullCalendar) against the same lane/block semantics
the backend produces.

## Project Structure

```text
UniSchedule/
├── backend/
│   ├── app.py           Flask application (API + export/sample-download routes +
│   │                     React production-bundle serving); served as backend.app:app
│   ├── api_routes.py    JSON API layer (/api/*) for the React frontend
│   ├── helpers.py       Shared timetable helpers (section splitting, timetable-view
│   │                     queries/titles, export cell text) used by backend/app.py
│   │                     and backend/api_routes.py
│   ├── models.py        SQLAlchemy models (Config, Room, Faculty, Program,
│   │                     Enrollment, Section, LabGroup, Subject,
│   │                     TeachingAssignment, ScheduledClass, AdminUser)
│   ├── scheduler.py     OR-Tools CP-SAT scheduling engine (untouched by frontend work)
│   ├── validators.py    Shared validation/normalization (e.g. room names)
│   ├── csv_import.py    Rooms + workload CSV import pipeline
│   ├── export.py        Timetable export builders (CSV / HTML / XLSX grids)
│   ├── seed_demo.py     Loads backend/sample_data/ through the real CSV import pipeline
│   ├── backup.py        Timestamped SQLite backups for scheduled jobs
│   ├── audit_schedule.py Standalone checker that re-verifies a generated schedule
│   ├── requirements.txt Pinned Python dependencies
│   ├── sample_data/     rooms_sample.csv + workload_sample.csv
│   └── instance/        Local application state (see Database)
├── frontend/            React application (see Frontend)
├── Procfile             gunicorn entrypoint for hosting platforms (backend.app:app)
├── .env.example         Documented environment variables (safe to commit)
└── README.md
```

```text
frontend/
├── src/
│   ├── app/            router.jsx, auth.jsx (RequireAuth), providers.jsx
│   ├── components/
│   │   ├── dashboard/  StatCard
│   │   ├── feedback/   toast system, loading/error/empty states
│   │   ├── layout/     AppShell, Page, Panel, placeholders
│   │   ├── navigation/ sidebar + nav-config
│   │   ├── timetable/  TimetableGrid, TimetableClassBlock, TimetableLegend
│   │   └── ui/         shadcn/ui primitives (button, input, table, …)
│   ├── hooks/          useApi, useAuth, useToast, useMediaQuery
│   ├── lib/            utils (cn)
│   ├── pages/          one folder per route (Dashboard, Rooms, …)
│   ├── services/
│   │   └── api/        centralized fetch client + per-domain modules
│   ├── App.jsx
│   ├── main.jsx
│   └── index.css       Tailwind v4 theme + UniSchedule design tokens
├── public/
├── package.json
├── vite.config.js      Tailwind plugin, @ alias, /api dev proxy → :5050
├── components.json     shadcn/ui configuration
└── jsconfig.json       @/* path alias
```

## Backend

### Flask application (`backend/app.py`)

Owns the HTTP layer: the JSON API blueprint, timetable file exports
(`/export/<view>/<id>/<fmt>`), sample CSV downloads (`/import/sample/<kind>`), and
serving the React production bundle with an SPA fallback. Shared timetable helpers
(section splitting, view queries, export cell text) live in `helpers.py` so both the
routes and the API use one implementation. Authentication is enforced globally: every
backend route except the API login and the React shell requires a signed-in session.

### API layer (`backend/api_routes.py`)

A Blueprint exposing the data and outcomes as JSON, reusing the existing queries,
helpers, and scheduler invocation — no duplicated business rules. Unauthenticated API
calls receive a machine-readable `401 {"error": "Authentication required."}`.

Authentication/session:

- `POST /api/login`, `POST /api/logout`, `GET /api/me`, `POST /api/change-password`

Read APIs:

- `/api/dashboard`, `/api/config`, `/api/rooms`, `/api/faculty`,
  `/api/faculty/<fid>/availability`, `/api/programs`, `/api/enrollments`,
  `/api/enrollments/<eid>/sections`, `/api/subjects`, `/api/assignments`,
  `/api/overview`, `/api/timetable`, `/api/timetable/<view>/<obj_id>`,
  `/api/timetable/free`

Write APIs mirror the former form POSTs (rooms, faculty, programs,
enrollments, subjects, assignments, config, availability, CSV imports, schedule generation),
returning `{ok, message, …}` on success and `{error, field_errors?}` with 4xx statuses on
validation failure. Timetable downloads (Excel/CSV/printable HTML via `/export/*`) and
sample CSVs (`/import/sample/*`) are same-origin download routes, which React calls
directly.

## Scheduling Engine

`backend/scheduler.py` expands each teaching assignment into session blocks and places them with
OR-Tools CP-SAT subject to hard constraints — room type/capacity/equipment match, no
room/faculty/student-group double-booking, lab-group sessions never overlapping their parent
section's theory, no block spanning the lunch break, faculty availability, a maximum
run of consecutive teaching periods, and HN1 (a student section may have at most two
consecutive theory periods in a teaching-period segment of a day — labs and free periods
reset the theory streak, and the streak does not cross configured breaks) — while minimizing how late in the day classes run so
schedules come out compact with no dead gaps. Its rules are intentionally kept separate from
the React frontend, which only renders the resulting lane/block structures.

Backend phases: 6C (additive schema), 6D (HN1), 6D.2 (read-only audit),
6E (locked interdepartment blocks), 6F (specializations — synchronized
cohorts with conservative originating-section occupancy, no student-level
scheduling; see `backend/PHASE_6F_SPECIALIZATIONS.md`).

## Timetable Views

The backend supports three timetable views — `section`, `faculty`, `room` — plus a Who's Free
matrix showing every faculty member's hour-by-hour status for a chosen day. Multi-period
blocks render as one merged cell (`colspan`); genuinely parallel sessions (e.g. two lab
groups in different rooms) render as stacked lanes under the same day. The React timetable
renders these lane/block structures with custom CSS Grid, and the Who's Free matrix is a
dedicated React page against `/api/timetable/free`.

## Frontend

Stack: React 19, Vite, JavaScript (no TypeScript), React Compiler, React Router, Tailwind
CSS v4, shadcn/ui on Radix primitives, Lucide icons, plain `fetch` (no Axios).

Architecture:

- `services/api/` — one centralized `fetch` client (same-origin + credentials, structured
  `ApiError`s) with thin per-domain modules; no endpoint strings in JSX.
- `app/auth.jsx` — Flask session-cookie auth via `GET /api/me`; `RequireAuth` redirects
  signed-out users to `/login?next=`. No JWT, nothing in `localStorage`.
- `hooks/useApi` — shared GET-on-mount hook with cancellation; every data page shows
  Skeleton loading states, human-readable `Alert` errors with retry, and proper empty states.
- `components/layout/` — responsive `AppShell` (246px sidebar on desktop, off-canvas drawer
  with hamburger on mobile), `Page` (title/subtitle/breadcrumbs/actions, 1400px cap),
  `Panel` with institutional left-rule accents.
- `index.css` — design tokens carrying over the existing identity: ink `#16233F`, brass
  `#B8873A`, steel `#3E6B96`, sage `#4B7B62`, signal `#A6423A`; Inter for UI, Source Serif 4
  for display type. Theory → steel, practical/lab → sage, danger → signal, primary actions →
  brass.

## Authentication

Single-tenant session auth with Flask-Login. The first admin login is created automatically
on first startup from environment variables (see `.env.example`); the React app learns the
current user from `GET /api/me` and never sees or stores passwords, tokens, or secrets.
There is no JWT and no credential storage in the browser. Never commit `.env` or any real
secret — only `.env.example` belongs in Git.

## Current Frontend Status

Accurate as of the `frontend` branch. The React app is the complete browser frontend:
every workflow below renders real backend data over `/api/*` (exports and sample CSVs
use the same-origin download routes).

### Foundation

- [x] React/Vite foundation
- [x] React Compiler
- [x] Tailwind/shadcn foundation
- [x] React Router
- [x] Responsive application shell
- [x] Authentication (`/login` sign-in form, `GET /api/me`, `RequireAuth`, `?next=`)
- [x] Centralized API client
- [x] Flask JSON API layer (`backend/api_routes.py`)

### Implemented React pages (real data)

- [x] Login (`/login`, session-cookie sign-in with `?next=` redirect)
- [x] Dashboard (`/`)
- [x] Config (`/config`, read + write)
- [x] Rooms (`/rooms`, create + delete)
- [x] Faculty (`/faculty`, create + delete, links to availability)
- [x] Faculty availability (`/faculty/:fid/availability`, read + write)
- [x] Programs (`/programs`, create + delete)
- [x] Enrollments (`/enrollments`, create + delete, auto-generated sections)
- [x] Sections (`/enrollments/:eid/sections`, read-only)
- [x] Subjects (`/subjects`, create + delete)
- [x] Teaching assignments (`/assignments`, create + delete)
- [x] Import (`/import`, rooms + workload CSV upload, sample CSV downloads)
- [x] Overview (`/overview`, sections/groups + faculty workload)
- [x] Timetable (`/timetable`, generation + section/faculty/room views + Excel/CSV/Print export)
- [x] Who's Free (`/timetable/free`)
- [x] Change Password (`/account/change-password`)

## Local Development

Backend (from the repository root):

```bash
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r backend/requirements.txt
python -m backend.app
```

The backend serves on `http://127.0.0.1:5050`. On first run it creates the SQLite database and
the initial admin login from the environment (see below).

Frontend (from `frontend/`):

```bash
npm install
npm run dev
```

Vite serves the React app (its normal development port) and proxies `/api` requests to the
backend at `127.0.0.1:5050`, so same-origin session cookies work during development.
`npm run lint` and `npm run build` verify the frontend.

Production (single process, same origin):

```bash
cd frontend && npm install && npm run build
cd .. && gunicorn backend.app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 90
```

Flask serves `frontend/dist/` (git-ignored build output) with an SPA fallback: unknown
non-API `GET` paths return `index.html` so React Router deep links work, while unmatched
`/api/*` paths still return JSON 404s and `/export/*` + `/import/sample/*` keep serving
downloads. If `dist/` has not been built, browser hits 404 but the API is unaffected.

Demo data (optional, exercises the real import pipeline):

```bash
python -m backend.seed_demo
```

Or use the Import page with `backend/sample_data/rooms_sample.csv` and
`backend/sample_data/workload_sample.csv`, then Timetable → Generate Timetable.

## Environment Configuration

Copy `.env.example` to `.env` for local use (`.env` is git-ignored and must never be
committed). Variables: `SECRET_KEY` (signs session cookies; required in any real deployment),
`INSTITUTION_NAME` (shown on the dashboard), `ADMIN_USERNAME` / `ADMIN_PASSWORD` (first
login; a random password is generated and printed once if unset), and optionally
`DATABASE_URL` (defaults to the local SQLite file; a Postgres URL is supported for more
durable deployments). The checked-in `backend/instance/timetable.db` is intentional demo state (see
Database) — it is already tracked in Git, so ignore rules below do not remove it.

## Database

Local development uses SQLite. The default file lives under `backend/instance/` (see
`SQLALCHEMY_DATABASE_URI` in `backend/app.py`; `DATABASE_URL` overrides it).
`backend/instance/timetable.db` is currently tracked in Git as the project's demo state — do not
delete it, and point `DATABASE_URL` elsewhere if you want a scratch database. Any *new* `*.db` /
`*.sqlite` files are ignored by the root `.gitignore`. Schema changes go through `backend/models.py`;
there is no migration tooling — deleting the SQLite file and re-running recreates an empty schema.

## CSV Import

Two formats, handled by `backend/csv_import.py` (also reachable as structured JSON via
`POST /api/import/rooms` and `POST /api/import/workload`):

- **Rooms CSV** (`backend/sample_data/rooms_sample.csv`): `name, room_type (theory/lab), capacity,
  equipment_count` — equipment optional, labs only. Names normalize to one canonical form;
  re-uploads update in place.
- **Workload CSV** (`backend/sample_data/workload_sample.csv`): one row per teaching assignment —
  `program, year_label, section, total_students, faculty_name, faculty_type, subject_code,
  subject_name, session_type (theory/practical), credits, periods_per_week, block_length`.
  Sections are created exactly as named; lab groups auto-generate from config; a practical row
  fans out into one assignment per lab group. Re-uploads match by name and are not duplicated.

## Export

`backend/export.py` builds day × period grids (single view per file) served by `/export/*`
routes, which the React app calls directly:

- **Excel** (`.xlsx`, styled workbook) — download
- **CSV** (`text/csv`) — download
- **Printable HTML** (`text/html`) — opens for printing

There is no PDF export. Exports are per timetable view (one section, faculty member, or
room at a time).

## Development Rules

### Backend preservation

`backend/scheduler.py`, `backend/models.py`, `backend/validators.py`, `backend/csv_import.py`,
`backend/export.py`, the database schema, and the API contracts must not change unless strictly
required for React/backend connectivity or application integrity. All React work lives under
`frontend/`. The API layer (`backend/api_routes.py`) plus shared `backend/helpers.py` is the
sanctioned bridge — extend it rather than editing business logic.

### Frontend rules

Use React, JavaScript, Tailwind, shadcn/ui, Lucide, and React Router. Do not introduce MUI,
Bootstrap, Ant Design, Chakra UI, or FullCalendar into the React app, and do not add state,
data-fetching, or styling libraries without a concrete, recorded need.

## Git Workflow

- Work happens on feature branches (current migration branch: `frontend`); open PRs for
  review instead of pushing straight to main.
- Backend changes need explicit justification in the PR description.
- Never commit secrets (`.env`, passwords, keys) or local database copies; generated
  artifacts (`node_modules/`, `dist/`, `__pycache__/`, `backups/`) stay ignored.
- Never force-push shared branches.

## Contributing

1. Create a branch from the current migration branch.
2. Backend: `pip install -r backend/requirements.txt`. Frontend: `cd frontend && npm install`.
3. Make your changes (frontend work stays in `frontend/`).
4. Run `npm run lint` and `npm run build`; for backend changes, run the app and
   `python -m backend.audit_schedule --db <path>` after generating a timetable. (There is no automated test
   suite; verification is manual — say what you ran in the PR.)
   Audit/diagnostic commands are read-only (SQLite `mode=ro`, no migrations, no admin
   creation); anything requiring schema changes operates on a file copy via the explicit
   `python -m backend.migrate --db <copy> upgrade` command — never on the live database.
5. Inspect `git status` and `git diff --name-only`; confirm no unintended files.
6. Submit a PR describing behavior changes and verification steps.

## License

License: not currently specified (no LICENSE file in the repository).

## Known Limitations / Roadmap

- Each deployment serves one institution with one admin login; multi-tenancy is not
  implemented.
- Production is a single gunicorn process serving both the API and the React build
  (see Local Development); split static hosting is not currently configured.
- The checked-in demo database does not currently regenerate cleanly end-to-end
  (`python -m backend.audit_schedule` reports break-spanning lab blocks against the current
  config), so treat generation results on the demo dataset as illustrative until the data
  is refreshed.
