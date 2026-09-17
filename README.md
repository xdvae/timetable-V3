# UniSchedule

UniSchedule is a university timetable management and generation system. Administrators manage
scheduling data — configuration, rooms, faculty, programs, enrollments, sections, subjects, and
teaching assignments — and the system generates a conflict-free timetable with Google OR-Tools
CP-SAT, viewable by section, faculty member, or room and exportable as Excel, CSV, or printable
HTML.

The project has two frontends sharing one backend:

- **Flask backend** (`app.py`, `models.py`, `scheduler.py`, …) — the scheduling engine, the
  database, the original server-rendered Jinja interface, and a JSON API layer.
- **React frontend** (`frontend/`) — the new administrative UI, currently under migration,
  communicating with Flask over same-origin `/api/*` requests.

## Overview

The core scheduling problem: given rooms (with capacity and type), faculty (with availability
and workload limits), student groups (sections split into lab groups), subjects, teaching
assignments, working days, periods, lunch-break rules, and consecutive-teaching limits, produce
a weekly timetable in which no room, faculty member, or student group is ever double-booked.

Backend responsibilities:

- **Flask** — HTTP routes for the legacy Jinja pages and the JSON API.
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
   ▼
Flask JSON API layer (api_routes.py)
   │
   ├── SQLAlchemy / database (models.py, instance/timetable.db)
   │
   ├── Scheduler / OR-Tools (scheduler.py)
   │
   └── existing Flask/Jinja application (app.py + templates/)
```

An important architectural decision: **the existing Flask/Jinja application remains intact**.
The React application is being introduced as a new frontend inside `frontend/`, and the JSON
API layer under `/api/*` exists specifically so React can communicate with the existing Flask
application. The non-API Flask routes keep serving the legacy server-rendered interface, and
the React timetable is being built with custom CSS Grid (not FullCalendar) against the same
lane/block semantics the backend already produces.

## Project Structure

```text
app.py              Flask routes (legacy Jinja pages)
api_routes.py       Additive JSON API layer (/api/*) for the React frontend
models.py           SQLAlchemy models (Config, Room, Faculty, Program,
                    Enrollment, Section, LabGroup, Subject,
                    TeachingAssignment, ScheduledClass, AdminUser)
scheduler.py        OR-Tools CP-SAT scheduling engine (untouched by frontend work)
validators.py       Shared validation/normalization (e.g. room names)
csv_import.py       Rooms + workload CSV import pipeline
export.py           Timetable export builders (CSV / HTML / XLSX grids)
seed_demo.py        Loads sample_data/ through the real CSV import pipeline
backup.py           Timestamped SQLite backups for scheduled jobs
audit_schedule.py   Standalone checker that re-verifies a generated schedule
requirements.txt    Pinned Python dependencies
Procfile            gunicorn entrypoint for hosting platforms
.env.example        Documented environment variables (safe to commit)
instance/           Local application state (see Database)
sample_data/        rooms_sample.csv + workload_sample.csv
templates/          Legacy Jinja templates (Bootstrap 5)
frontend/           React application (see Frontend)
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
│   │   ├── timetable/  reserved for the future timetable UI
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

### Flask application (`app.py`)

Owns all business logic and the legacy UI: dashboard counts, configuration, rooms, faculty
(including per-slot availability), programs, enrollments (with automatic section/lab-group
splitting), subjects, teaching assignments (with weekly-load accounting), CSV import, the
scheduler run endpoint, timetable views by section/faculty/room, the Who's Free matrix, file
exports, and password management. Authentication is enforced globally: every route except the
login page requires a signed-in session.

### API layer (`api_routes.py`)

An isolated Blueprint exposing the same data and outcomes as JSON, reusing the existing
queries, helpers, and scheduler invocation — no duplicated business rules. It was introduced
specifically for React connectivity. Unauthenticated API calls receive a machine-readable
`401 {"error": "Authentication required."}` instead of the HTML login redirect.

Authentication/session:

- `POST /api/login`, `POST /api/logout`, `GET /api/me`, `POST /api/change-password`

Read APIs (same shapes the Jinja pages already use):

- `/api/dashboard`, `/api/config`, `/api/rooms`, `/api/faculty`,
  `/api/faculty/<fid>/availability`, `/api/programs`, `/api/enrollments`,
  `/api/enrollments/<eid>/sections`, `/api/subjects`, `/api/assignments`,
  `/api/overview`, `/api/timetable`, `/api/timetable/<view>/<obj_id>`,
  `/api/timetable/free`

Write APIs exist as additive variants of the form POSTs (rooms, faculty, programs,
enrollments, subjects, assignments, config, availability, CSV imports, schedule generation),
returning `{ok, message, …}` on success and `{error, field_errors?}` with 4xx statuses on
validation failure. Timetable downloads (Excel/CSV/printable HTML) and sample CSVs keep
working through the existing download routes, which React calls directly.

## Scheduling Engine

`scheduler.py` expands each teaching assignment into session blocks and places them with
OR-Tools CP-SAT subject to hard constraints — room type/capacity/equipment match, no
room/faculty/student-group double-booking, lab-group sessions never overlapping their parent
section's theory, no block spanning the lunch break, faculty availability, and a maximum
run of consecutive teaching periods — while minimizing how late in the day classes run so
schedules come out compact with no dead gaps. Its rules are intentionally kept separate from
the React frontend, which only renders the resulting lane/block structures.

## Timetable Views

The backend supports three timetable views — `section`, `faculty`, `room` — plus a Who's Free
matrix showing every faculty member's hour-by-hour status for a chosen day. Multi-period
blocks render as one merged cell (`colspan`); genuinely parallel sessions (e.g. two lab
groups in different rooms) render as stacked lanes under the same day. The React timetable UI
is being implemented with custom CSS Grid against these exact semantics and is not complete
yet; until then the full timetable experience lives in the Jinja interface and the JSON
payloads described above.

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

Accurate as of the `frontend` branch. A route placeholder existing does **not** mean the
page is implemented — only the items marked done render real backend data.

### Foundation

- [x] React/Vite foundation
- [x] React Compiler
- [x] Tailwind/shadcn foundation
- [x] React Router
- [x] Responsive application shell
- [x] Authentication foundation (`/api/me`, `RequireAuth`, `?next=`)
- [x] Centralized API client
- [x] Flask JSON connectivity layer (`api_routes.py`)

### Implemented React pages (real data)

- [x] Dashboard (`/`)
- [x] Config (`/config`, read-only)
- [x] Rooms (`/rooms`, read-only)
- [x] Faculty (`/faculty`, read-only, links to availability)

### In progress / planned

- [ ] Login UI (route + shell exist; full sign-in form pending)
- [ ] Faculty availability UI (route + navigation links exist)
- [ ] Programs
- [ ] Enrollments
- [ ] Sections
- [ ] Subjects
- [ ] Teaching assignments
- [ ] Import UI
- [ ] Overview
- [ ] Timetable UI (custom CSS Grid; backend semantics documented above)
- [ ] Who's Free UI
- [ ] Change Password UI
- [ ] React CRUD workflows
- [ ] Full integration/regression testing

## Local Development

Backend (from the repository root):

```bash
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python app.py
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

Demo data (optional, exercises the real import pipeline):

```bash
python seed_demo.py
```

Or use the Import page with `sample_data/rooms_sample.csv` and
`sample_data/workload_sample.csv`, then Timetable → Generate Timetable.

## Environment Configuration

Copy `.env.example` to `.env` for local use (`.env` is git-ignored and must never be
committed). Variables: `SECRET_KEY` (signs session cookies; required in any real deployment),
`INSTITUTION_NAME` (shown on the dashboard), `ADMIN_USERNAME` / `ADMIN_PASSWORD` (first
login; a random password is generated and printed once if unset), and optionally
`DATABASE_URL` (defaults to the local SQLite file; a Postgres URL is supported for more
durable deployments). The checked-in `instance/timetable.db` is intentional demo state (see
Database) — it is already tracked in Git, so ignore rules below do not remove it.

## Database

Local development uses SQLite. The default file lives under `instance/` (see
`SQLALCHEMY_DATABASE_URI` in `app.py`; `DATABASE_URL` overrides it). `instance/timetable.db`
is currently tracked in Git as the project's demo state — do not delete it, and point
`DATABASE_URL` elsewhere if you want a scratch database. Any *new* `*.db` / `*.sqlite` files
are ignored by the root `.gitignore`. Schema changes go through `models.py`; there is no
migration tooling — deleting the SQLite file and re-running recreates an empty schema.

## CSV Import

Two formats, handled by `csv_import.py` (also reachable as structured JSON via
`POST /api/import/rooms` and `POST /api/import/workload`):

- **Rooms CSV** (`sample_data/rooms_sample.csv`): `name, room_type (theory/lab), capacity,
  equipment_count` — equipment optional, labs only. Names normalize to one canonical form;
  re-uploads update in place.
- **Workload CSV** (`sample_data/workload_sample.csv`): one row per teaching assignment —
  `program, year_label, section, total_students, faculty_name, faculty_type, subject_code,
  subject_name, session_type (theory/practical), credits, periods_per_week, block_length`.
  Sections are created exactly as named; lab groups auto-generate from config; a practical row
  fans out into one assignment per lab group. Re-uploads match by name and are not duplicated.

## Export

`export.py` builds day × period grids (single view per file) served by the existing routes,
which the React app will call directly:

- **Excel** (`.xlsx`, styled workbook) — download
- **CSV** (`text/csv`) — download
- **Printable HTML** (`text/html`) — opens for printing

There is no PDF export. Exports are per timetable view (one section, faculty member, or
room at a time).

## Development Rules

### Backend preservation

`scheduler.py`, `models.py`, `validators.py`, `csv_import.py`, `export.py`, the database
schema, and the existing Jinja interface must not change unless strictly required for
React/backend connectivity or application integrity. All React work lives under `frontend/`.
The API layer (`api_routes.py`) is the only sanctioned bridge — extend it additively rather
than editing business logic.

### Frontend rules

Use React, JavaScript, Tailwind, shadcn/ui, Lucide, and React Router. Do not introduce MUI,
Bootstrap, Ant Design, Chakra UI, or FullCalendar into the React app, and do not add state,
data-fetching, or styling libraries without a concrete, recorded need. (The legacy Jinja
templates keep their existing Bootstrap dependency; that rule applies to the new frontend.)

## Git Workflow

- Work happens on feature branches (current migration branch: `frontend`); open PRs for
  review instead of pushing straight to main.
- Backend changes need explicit justification in the PR description.
- Never commit secrets (`.env`, passwords, keys) or local database copies; generated
  artifacts (`node_modules/`, `dist/`, `__pycache__/`, `backups/`) stay ignored.
- Never force-push shared branches.

## Contributing

1. Create a branch from the current migration branch.
2. Backend: `pip install -r requirements.txt`. Frontend: `cd frontend && npm install`.
3. Make your changes (frontend work stays in `frontend/`).
4. Run `npm run lint` and `npm run build`; for backend changes, run the app and
   `python audit_schedule.py` after generating a timetable. (There is no automated test
   suite; verification is manual — say what you ran in the PR.)
5. Inspect `git status` and `git diff --name-only`; confirm no unintended files.
6. Submit a PR describing behavior changes and verification steps.

## License

License: not currently specified (no LICENSE file in the repository).

## Known Limitations / Roadmap

- The React migration is ongoing: most workflows (programs, enrollments, subjects,
  assignments, import, overview, timetable, CRUD) still exist only in the Jinja UI and as
  JSON endpoints awaiting React pages.
- Each deployment serves one institution with one admin login; multi-tenancy is not
  implemented.
- Production deployment architecture (beyond the provided `Procfile`/gunicorn entrypoint)
  is not finalized.
- The checked-in demo database does not currently regenerate cleanly end-to-end
  (`audit_schedule.py` reports break-spanning lab blocks against the current config), so
  treat generation results on the demo dataset as illustrative until the data is refreshed.
