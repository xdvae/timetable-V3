# University Timetable Generator

A working web app: enter your rooms, faculty, enrollment numbers, subjects
and teaching assignments; click **Generate Timetable**; it solves a real
constraint-satisfaction problem (Google OR-Tools CP-SAT) and gives you a
conflict-free timetable, exportable as Excel / CSV / printable HTML.

## What it does

- **Auto-splits sections**: give it "BCA-1, 250 students" + your max
  section size (e.g. 80) → it creates BCA-1-A/B/C/D automatically, sized
  as evenly as possible.
- **Auto-splits lab groups**: each section is split further for
  practicals based on your max lab-group size (e.g. 40).
- **Hard constraints enforced** (never violated): no teacher, room, or
  student group is ever double-booked; room/lab capacity is respected;
  no class spans across the lunch break; a faculty member never teaches
  more than N consecutive periods without a free period.
- **Soft optimization**: the solver minimizes how late in the day classes
  run, which — because a group can't have two classes at once — also
  eliminates dead gaps in the middle of the day as a side effect. Net
  result: students finish as early as possible with no "9-11, gap, 3-4"
  schedules.
- **Multiple views**: by section, by faculty, by room — each exportable
  independently.

## Setup

```bash
cd timetable_app
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5050** in your browser.

The first run creates `timetable.db` (SQLite) automatically — all your
data persists there between runs. To start completely fresh, just delete
`timetable.db`.

## What's new in this version

- **Fixed room-name format.** Only a room number with an optional single block letter is accepted (e.g. `503 B`, `B503`, `301`) — every equivalent spelling normalizes to one canonical form (`503-B`), and the database rejects true duplicates outright.
- **Faculty load warnings.** Adding a teaching assignment shows a flash message with the faculty member's weekly hours before/after, and flags it in orange if it pushes them past their configured weekly max.
- **Overview page.** A dedicated screen showing every section and its auto-generated lab groups, plus a per-faculty workload card listing every subject/group they teach and their running weekly total.
- **Subjects carry default weekly hours.** Each subject can define its usual theory hrs/week and practical hrs/week (labs default to a 2-hour block, but you can set it to 1 to split a lab into two separate 1-hour sessions). Picking a subject on the Teaching Assignments form auto-fills these — still fully editable per assignment.
- **Split section timetable view.** A section's page now shows the whole-section theory schedule and each lab group's practical schedule as separate, clearly labelled tables/sheets, instead of one merged (and confusing) grid.
- **Free Faculty view.** A new page (`Timetable → Who's Free When`) showing every faculty member's status hour-by-hour for a chosen day — green for free, red for what they're teaching.
- **Colorful, clearer UI.** Theory vs. practical are color-coded throughout (blue/green), section and lab-group cards, and a refreshed visual style overall.

## v4 fixes (latest feedback round)

- **Section timetable is one unified table again.** Theory and both lab groups are shown together in a single grid (each cell lists subject, faculty, group, and room), rather than split into separate tables — matches how a department actually reads a class timetable.
- **Free Faculty view now shows room numbers too**, in the same "Subject · Group · Room" format used everywhere else.
- **Faculty weekly workload is now visible in three places**: a "Weekly Load" column on the Faculty list, a subtitle on each faculty's timetable page ("Weekly teaching load: 13 hrs"), and the existing per-faculty card on the Overview page.
- **`audit_schedule.py`** — a standalone script that independently re-checks every generated schedule against every hard constraint (room/faculty/student-group double-booking, break-crossing, capacity/equipment, consecutive-teaching limit) directly against the database, separately from the solver's own logic. Run it any time after generating a timetable: `python audit_schedule.py`.

## v6: full UI redesign

The interface has been redesigned for people who aren't developers — department staff, not programmers — since this is heading toward a real deployment.

- **Sidebar navigation**, grouped into Setup / People / Academics / Data / Timetable, replacing the old flat 12-item top navbar that was genuinely hard to scan.
- **A calm, institutional visual identity** instead of generic Bootstrap defaults: deep ink-navy structure, a warm brass accent used only for primary actions, a serif typeface for page titles, Inter for everything else (dense timetable tables need maximum legibility).
- **Content sections use a colored left rule** instead of the identical drop-shadow card look everywhere, so the page reads more like organized records than a generic dashboard template.
- Every existing page (rooms, faculty, subjects, assignments, config, import, etc.) inherits the same color/type tokens automatically, so the whole app is visually consistent without having rewritten every single template from scratch.
- The color legend (theory=blue, lab=green, free=green, busy=red) is now shown directly above each grid so the meaning of the colors doesn't have to be guessed.

Note: this app loads Bootstrap, Bootstrap Icons, and Google Fonts from public CDNs at runtime — normal on any machine with regular internet access, but they won't load if you're testing in a fully offline/sandboxed environment.

## Phase 1: selling this as a per-institution product

The app now supports being deployed once per paying customer — same codebase, each institution gets its own instance, own database, own login. Nobody's data ever touches anyone else's, because there's no shared server at all yet (real multi-tenancy is a Phase 2 problem, deliberately deferred).

### What's new

- **Login required.** Every page now requires signing in. The first admin login is created automatically on first startup from environment variables.
- **Environment-based setup.** `.env.example` lists everything a new deployment needs: `SECRET_KEY`, `INSTITUTION_NAME`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, optionally `DATABASE_URL`. Copy it to `.env` for local use, or set these in your hosting platform's dashboard for a real deploy.
- **Change Password page**, so you can hand off a temporary password and the customer can change it themselves.
- **`backup.py`** — copies the database to a timestamped file in `backups/`, prunes old ones, and documents how to sync those off-server (e.g. with `rclone` to S3/Backblaze). Run it on a daily cron/scheduled job once real customer data is in here.
- **`Procfile`** and `gunicorn` in requirements — for deploying to Railway, Render, Fly.io, or similar platforms that auto-detect a `Procfile`. Don't run `python app.py` (the Flask dev server) in production — the Procfile's gunicorn command is the real one, with a 90-second timeout since the scheduler can take up to a minute on larger datasets.

### Onboarding a new paying institution (the actual repeatable steps)

1. Deploy a fresh copy of this codebase to your hosting platform of choice, on its own subdomain.
2. Set these environment variables in that deployment:
   - `SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_hex(32))"`
   - `INSTITUTION_NAME` — shown on their dashboard
   - `ADMIN_USERNAME` / `ADMIN_PASSWORD` — their first login
3. Deploy. The database and admin login are created automatically on first boot.
4. Set up a daily scheduled job to run `python backup.py` (most platforms have a "cron job" or "scheduled task" feature).
5. Send them their login URL and password. They do the rest through the UI — Config, Rooms, Faculty, Enrollments, Subjects, Assignments, or a CSV import — with zero further work from you.

### Local testing with auth

```bash
cp .env.example .env
# edit .env: set ADMIN_PASSWORD to something, or leave blank to get a
# generated password printed to the console on first run
python seed_demo.py   # optional — loads the demo dataset
python app.py
```
The demo dataset shipped with this zip already has a login set up: **username `admin`, password `demo-admin-2026`** — change it immediately if you're using this beyond local testing.

## v5 fixes (rendering bug + a real scheduling bug + bigger dataset)

- **Fixed a genuine timetable-view rendering bug.** A multi-hour block (e.g. a 2-hour lab) used to repeat its text in every hour column it covered, which could look like two separate lectures at the same time. It's now rendered as one merged cell (colspan) — no more visual duplication. When two *different* sub-groups legitimately have parallel sessions at the same hour (different rooms), they now show as clearly separate stacked rows under that day, with a note explaining they're simultaneous-but-different, not a conflict.
- **Found and fixed a real scheduling bug.** The solver treated a section and its lab groups as fully independent resources, so it could (rarely) schedule a lab-group practical at the same time as a whole-section theory class — impossible in reality, since a lab group's students are a subset of the section. Added a hard constraint so a lab group's session can never overlap its own section's theory session. `audit_schedule.py` now checks for this specifically too.
- **Much bigger sample dataset for testing.** `sample_data/workload_sample.csv` now covers 4 programs — BCA, BSc IT, BCS, and B.Tech CSE — each with 9 subjects (mixing theory-only, practical-only, and theory+lab subjects), ~19 faculty (some teaching across multiple programs, as real faculty do), and realistic weekly loads (27-30 hrs/section). `seed_demo.py` now loads this through the actual CSV import pipeline rather than hand-built ORM calls, so it also doubles as an end-to-end test of that feature.

## Fastest way to try it: CSV import

Instead of clicking through forms, go to **Import CSV** in the nav bar and
upload two files:

1. **Rooms CSV** — `name, room_type (theory/lab), capacity, equipment_count`
2. **Workload CSV** — one row per (section, subject, faculty) teaching
   assignment: `program, year_label, section, total_students, faculty_name,
   faculty_type, subject_code, subject_name, session_type (theory/practical),
   credits, periods_per_week, block_length`

Sample files with realistic mock data (3 programs, 5 sections, 10 faculty,
21 subjects, each section loaded to ~20-22 periods/week) are in
`sample_data/` and downloadable straight from the Import page. A
**practical** row automatically fans out into one teaching assignment per
auto-generated lab group of that section — you don't need to list lab
groups yourself. Re-uploading is safe: existing rooms/faculty/subjects/
sections are matched by name and not duplicated.

After importing both files, go to **Timetable → Generate Timetable**.

## How to use it (in order) — manual data entry

1. **Config** — set working days, period times, where the lunch break
   falls, max section size, max lab group size, and how many consecutive
   periods a faculty member can teach before needing a break.
2. **Rooms** — add theory rooms and labs (capacity, and for labs, how
   much equipment / how many computers).
3. **Faculty** — add faculty; optionally set specific unavailable slots
   (e.g. a visiting faculty member only free two mornings a week).
4. **Programs** — e.g. BCA, B.Tech CSE, MCA.
5. **Enrollments** — pick a program + year label (e.g. "1st Year") and
   total student count. Sections and lab groups are generated for you
   immediately — click "View Sections" to see them.
6. **Subjects** — add subjects against each enrollment (program+year),
   with credits.
7. **Teaching Assignments** — the core input: faculty + subject +
   section (theory) or lab group (practical) + periods/week + block
   length (1 = single-period theory class, 2 = a 2-hour lab block).
8. **Timetable → Generate Timetable** — runs the solver (a few seconds
   to ~30s depending on size). Then browse by section / faculty / room,
   and export to Excel, CSV, or a printable HTML page from each view.

## If scheduling fails

The solver will tell you *why* it couldn't find a timetable — usually one
of:
- Not enough rooms/labs of the right capacity for a group's size
- A faculty member's availability is too restrictive for their load
- Too many periods/week assigned relative to available slots

Add more rooms, loosen availability, or spread load across more faculty,
then re-generate.

## Project structure

```
app.py          Flask routes (all pages + API-like endpoints)
models.py       SQLAlchemy models (SQLite)
scheduler.py    OR-Tools CP-SAT scheduling engine
export.py       Excel / CSV / printable-HTML export
templates/      Jinja2 HTML templates (Bootstrap 5)
requirements.txt
```

## Notes on the scheduling model

Each "Teaching Assignment" (faculty + subject + section/lab-group +
periods/week + block length) is expanded into session blocks that the
solver places on a (day, start period, room) triple, subject to:

- room type/capacity match
- no faculty/room/student-group double-booking
- no block spans the lunch break
- faculty consecutive-teaching-without-a-break limit

...and minimizes the sum of start-periods across all sessions, which is
what produces compact, early-finishing schedules without needing a more
complex hand-tuned gap-penalty formula.

This is deliberately an MVP core engine matching what you described:
extending it (visiting-faculty auto-assignment, theory+lab adjacency
preference, combined/cross-department classes, multi-department
simultaneous scheduling) is straightforward from here — the data model
already supports inter-department and visiting faculty types, it's just
not yet wired into extra constraints.
#   t i m e t a b l e - V 3  
 