# UniSchedule — Phase 6V Final Audit (Production Safety / Regression)

> Branch: `frontend` · No commit, no push (phase rule).
> Working tree was clean at start; all changes below are the 6V fixes + tests + this audit.

## 1. Status

```text
PRODUCTION-READY WITH DOCUMENTED LIMITATIONS
```

The codebase is hardened and every release-blocking code condition is resolved
with regression cover. Deployment is safe **provided the three mandatory
pre-deploy actions in §20 are executed** — most importantly migrating the
checked-in demo database (limitation L1), which Phase 6V rules prohibited
modifying in place. A naive default-config deploy without those steps serves
sanitized 500s on core routes (defect 6V-2, repaired path verified).

## 2. Scope

Audited against the working tree (not prior reports alone):

- Production configuration (Procfile/gunicorn target, Flask debug, SPA serving,
  env handling, seed/init behavior), secrets/credentials, auth/session, CORS,
  error sanitization (400/401/404/405/422/500, scheduler UNKNOWN/INFEASIBLE/
  MODEL_INVALID).
- Database integrity (FKs, uniques, orphans, `PRAGMA integrity_check`) on
  isolated copies; migration chain `6C → 6E → 6F → 6J` (upgrade, downgrade,
  re-upgrade, idempotence, failure atomicity); backup/restore round-trip and
  full recovery simulation on temp paths.
- Production-like startup/smoke (real `backend.app` object, temp DBs, built
  `frontend/dist/`), frontend build safety, backend + frontend dependency
  hygiene.
- Regression safety for scheduler status semantics/atomicity, manual edits,
  faculty reassignment/swap, specializations, locked blocks, preferences, 6P
  propagation, 6Q error contract — via the full suites (no behavior changes).
- Repository hygiene, dead/duplicate code, failure injection, test isolation.

Prior audits (`PHASE_6P/Q/R/S/T/U`) were used as evidence maps; every
load-bearing claim was re-verified against current sources.

## 3. Baseline (exact, pre-6V)

| Check | Result |
|---|---|
| Backend (`venv\Scripts\python.exe -m pytest backend\tests\ -q`) | `626 passed, 10 subtests passed` (~354 s) |
| Frontend (`npm test` in `frontend/`) | `9 files, 152 passed` (~11 s) |
| Lint (`npm run lint`) | 0 errors, 0 warnings |
| Build (`npm run build`) | success, `2094 modules transformed`, `~12 s`, only pre-existing >500 kB chunk advisory |
| `backend/instance/timetable.db` SHA256 | `8D7AF21E9140C4730EBCFEA2C0014C842FF42565423737E586231A31ED42071D` |
| `backend/instance/timetable_v2.db` SHA256 | `171D57AC8471ACAFEE32FDBC3589EE6AA4302B83A5DB7C34026B2C2950D85641` |
| Working tree (`git status --short`) | clean |

Baseline matches the expected 6U post-state exactly.

## 4. Production configuration

- **Startup:** `Procfile` → `gunicorn backend.app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 90`.
  The WSGI target imports cleanly and boots against temp DBs (verified via probes).
  `app.run(debug=True, …)` exists only under `if __name__ == "__main__"` (dev path);
  gunicorn does not enable debug. No `flask run --debug` in deploy path.
- **Frontend serving:** Flask serves `frontend/dist/` (git-ignored, built in 6V) with
  SPA fallback; unknown non-API GET paths return `index.html` (verified anon + authed,
  incl. deep routes); unmatched `/api/*` stay JSON. Missing `dist/` only affects
  browser hits, never API/export/sample routes.
- **Environment:** `SECRET_KEY` (random per boot if unset — dev-tolerable, prod must set),
  `INSTITUTION_NAME`, `ADMIN_USERNAME`/`ADMIN_PASSWORD` (random once if unset, printed
  once), `DATABASE_URL` (default local SQLite). `.env.example` holds placeholders only;
  local `.env` (dev credentials) is git-ignored and untracked. `load_dotenv` never
  overrides real environment values.
- **Init safety:** `init_db` = `create_all` + seed `Config` (never drops); `init_admin_from_env`
  inserts only when zero admins exist. `seed_demo` is explicitly manual and destructive
  (`drop_all`, `setdefault` demo password) — must never run against a live DB (docs note).
- **Filesystem paths:** instance path pinned to `backend/instance/`; works from repo root
  for `gunicorn backend.app:app`, `python -m backend.app`, and `python backend/app.py`.
- **Ambiguity resolved by fix:** none in config; one routing defect (6V-1, §19) fixed.

## 5. Security

- **Secrets scan:** pattern sweep (keys/tokens/passwords/private-key/AKIA/gh_sk/bearer/oauth)
  over tracked sources found only placeholders, test passwords, code references, and docs.
  `.env` is ignored (`git check-ignore` confirms); only `.env.example` is tracked. No real
  secret is committed. Test-only credentials stay in tests. Verdict: no leakage.
- **Auth/session:** Flask-Login session cookie; `GET /api/me`, login/logout/change-password
  verified (probes + suites). Anonymous API use → `401 {ok:false, code:AUTH_REQUIRED}`;
  bad credentials → `401 INVALID_CREDENTIALS` (no user-enumeration delta beyond the code);
  logout invalidates (subsequent `/api/me` → 401). SPA shell is intentionally public
  (RequireAuth guards client-side); all data APIs stay 401-guarded. No JWT, no
  `localStorage`/`sessionStorage` credential storage (grep-verified; only comments mention it).
  Passwords are hashed (`werkzeug`), never returned or logged. Cookie flags are Flask
  defaults (HttpOnly, Lax); `Secure` is NOT set — acceptable for local HTTP, but a
  **production HTTPS deployment should set `SESSION_COOKIE_SECURE`** (limitation L4;
  deliberately not forced in code to avoid breaking plain-HTTP installs).
- **CORS:** no `flask-cors`, no `Access-Control-*` code, no wildcard origins. Same-origin
  design (dev Vite proxy `/api → 127.0.0.1:5050`; prod same Flask process). Frontend has
  no hard-coded hosts, no `VITE_*` env, `fetch(..., {credentials:"same-origin"})`.
  Nothing to lock down; no dev-port dependency in production.
- **Error sanitization:** `errors.py` is the single choke point (message cap 2000 chars,
  details scrubbed of traceback/stack/secret/password/SQLAlchemy-ish keys, field errors
  coerced). Live probes: forced-exception 500 shape verified via suites; duplicate-room
  constraint failure → 422 with safe message (no SQL); malformed JSON → 422 (no crash);
  login failure → no leak. Unknown-exception handler maps HTTPExceptions by status and
  sanitizes everything else to 500 `INTERNAL_ERROR`.
- **Debug:** no debug toolbar/profiler; Werkzeug debugger only under Flask debug (off in prod).

## 6. Database

Reference copies inspected read-only (`mode=ro` URIs) in temp dirs:

| Check | `timetable.db` | `timetable_v2.db` |
|---|---|---|
| `PRAGMA integrity_check` | `ok` | `ok` |
| `PRAGMA foreign_key_check` | 0 violations | 0 violations |
| Orphan rows (scheduled→assignment/room, assignment→faculty, section→enrollment, labgroup→section, subject→enrollment, slot→spec, membership) | 0 | 0 (6C tables absent) |
| Duplicate room names | 0 | 0 |
| Row counts (room/faculty/program/enrollment/section/lab_group/subject/assignment/scheduled/config/admin) | 12/19/4/4/4/8/46/58/115/1/1 | identical core counts |
| `schema_migrations` | absent | absent |

Structural finding (defect 6V-2, §19): `timetable.db` carries 6C-era tables but is
**missing every post-6B additive column** (`section.preferred_theory_room_id`,
`scheduled_class.is_locked/slot_id/locked_block_id`, `locked_block.assignment_id`,
`teaching_assignment.specialization_id`); `timetable_v2.db` is pre-6C. Because the ORM
selects all mapped columns even for `count()`, the current app serves sanitized 500s
on dashboard/timetable/schedule/assignments/overview against the un-migrated file.
Read-only `audit_schedule` against the reference file reports the pre-existing,
README-disclosed HN1 violations in demo data (data condition, not a regression) and
confirms hashes never moved.

## 7. Migrations

Chain present: `6c_additive_schema → 6e_locked_assignment → 6f_specializations →
6j_faculty_preferences` (linear `down_revision` links verified; live-DB guard
`--allow-live` intact and refusing by default).

| Migration | Upgrade | Downgrade | Re-upgrade | Data preserved | Result |
|---|---|---|---|---|---|
| 6C | clean pre-6C + hybrid (post-6V fix) | removes own artifacts | ✓ | ✓ row-level (new cols defaulted) | PASS |
| 6E | ✓ incl. hybrid | ✓ | ✓ | ✓ | PASS |
| 6F | ✓ incl. hybrid | ✓ | ✓ | ✓ | PASS |
| 6J | ✓ (already idempotent) | index-only, table+rows kept | ✓ | ✓ | PASS |

Pre-fix behavior (defect 6V-3): `upgrade` on a reference-like copy crashed with
`sqlite3.OperationalError: table specialization already exists` and applied nothing
(clean abort, no misleading version row — but no repair either). Post-fix: the full
chain upgrades a reference copy end-to-end (verified: all 4 revisions `applied`,
row counts 12/19/4/58/115/1 preserved, all ORM columns present, re-run reports
`already up to date`). Failure atomicity holds per revision (version row written only
after the revision's statements all succeed). Operational caution: downgrading 6C on a
hybrid DB would drop tables that pre-date the version history — downgrades are only
meaningful on databases the runner itself upgraded; the runner already forces `--db` to
be an explicit copy unless `--allow-live` is passed.

## 8. Backup / restore

`backend/backup.py` backs up `SQLITE_DB_PATH` (default: live file) to timestamped
`BACKUP_DIR/timetable-<UTC>.db`, pruning beyond `BACKUP_KEEP_LAST=30`. Verified on
isolated paths: exit 0, backup file created, `integrity_check ok`, FK clean, row counts
(room/faculty/section/assignment/scheduled/config/admin) identical src vs restored,
and the app boots against the restored file (anon `/api/dashboard` → 401, proving the
stack serves it). Limitations (documented, non-blocking): no `restore` subcommand
(restore = file copy, operator responsibility); same-second double runs would collide on
the timestamp name; Postgres deployments must use `pg_dump` instead (stated in the script).

## 9. Deployment smoke test

Strongest local production-like verification (Windows cannot execute gunicorn — L3):

- Real `backend.app:app` object booted with temp `DATABASE_URL` + explicit `SECRET_KEY`:
  process-equivalent import/startup clean, no missing dependency (all pinned, freeze-matched).
- Against a **migrated reference copy**: login 200; `/api/dashboard`, `/api/timetable`,
  `/api/schedule/classes`, `/api/assignments`, `/api/overview`, `/api/rooms`,
  `/api/faculty`, `/api/locked-blocks`, `/api/specializations`,
  `/api/timetable/section/1`, `/api/timetable/free` → all 200 with sane payloads.
- Frontend: built `dist/` served; `/`, `/timetable`, deep routes → `index.html` 200
  (anon + authed); `/api/*` unknowns → JSON 404.
- Wrong-method parity post-fix: `GET /api/schedule/run`, `GET /api/login` → 405
  `METHOD_NOT_ALLOWED` JSON; `POST /api/dashboard` → 405 JSON.
- Shutdown: test clients close cleanly; no hanging threads (no background jobs exist —
  scheduling is synchronous per request, `time_limit_seconds=30`, solver discarded).

## 10. Scheduler safety

- **Status semantics** (inspected `scheduler.py:1079-1116` + `api_routes.py:1408-1452`,
  covered by `test_scheduler_status_6t.py` in the green suite): OPTIMAL/FEASIBLE →
  success; proven INFEASIBLE → `INFEASIBLE`; timeout/UNKNOWN → 422 `SCHEDULING_FAILED`
  with `{status:UNKNOWN, timeout:true}` (message never says "infeasible");
  MODEL_INVALID → sanitized 500 `INTERNAL_ERROR`. UNKNOWN is never mapped to INFEASIBLE.
- **Atomicity:** every failure branch raises before any write; success path replaces only
  non-locked rows (legacy pre-6C fallback preserved), keeps locked rows exactly once,
  rebuilds/prunes spec slots, and commits once. Suite pins previous-schedule preservation
  (incl. locked rows) across INFEASIBLE/UNKNOWN/MODEL_INVALID/exception.
- **Objective:** untouched in 6V (6S scales intact by inspection; `test_scheduler_objective_6s`
  green).

## 11. Manual editing safety

No 6V code changes. Suite (`test_manual_edits_6g/6n`, contract tests) green: validate is
dry-run/read-only (scheduler never invoked — pinned by mock), moves relocate exactly one
class, no-op/locked/spec/HN1-H12/faculty/room/group conflicts behave, failed moves leave
the DB unchanged, unrelated rows untouched.

## 12. Faculty safety

No 6V code changes. Reassignment/swap suites green: validation-only paths read-only and
write-identical; mutations atomic (failed swap rolls both back); locked assignments
rejected; availability/specialization guards hold; scheduled classes follow new faculty;
no partial updates; propagation unchanged.

## 13. Specialization safety

No 6V code changes. Suites green: capacity/membership/enrollment linkage, sync patterns,
room capacity, HN1 contribution, slot persist/rebuild/prune, deletion consistency, and
failed-operation atomicity all hold.

## 14. Locked block safety

No 6V code changes. Suites green: assignment linkage, exact day/start/length, mandatory
room, derived faculty/section/subject, conflict triad (room/faculty/group), hierarchy,
availability, HN1/H12, scheduler preservation of `LockedBlock + ScheduledClass(is_locked)`
pairs, deletion consistency.

## 15. Preference safety

No 6V code changes. Suites green: TIME_WINDOW/DAY_OFF_PREFERENCE supported;
SUBJECT_AFFINITY recognized-but-rejected; invalid days/periods/weights rejected; hard
preferences rejected (soft-only); disabled/unknown rows inert; scheduler treats them as
strictly-subordinate soft costs (feasibility identical with/without); preference CRUD
never touches the schedule.

## 16. Propagation regression

No 6V code changes. Frontend propagation suites (152 tests) green: all 14 domains frozen,
single `emitOnSuccess` gate (success + non-noop only), validation/failure/no-op paths emit
nothing, generation fans out to schedule-dependent domains, preference/preferred-room
writes stay config-scoped, no leaks/loops/duplicates beyond documented batching.

## 17. Error regression

Unified `{ok:false, error, code, details?, field_errors?, failures?}` holds on all probed
paths (suites + live probes): `INTERNAL_ERROR`, `SCHEDULING_FAILED`, `UNKNOWN`,
`MODEL_INVALID`, `LOCKED_BLOCK`, specialization/room/faculty/section conflicts,
preference errors, auth errors, and wrong-method 405 (now also on the real routing path
after 6V-1). Frontend `failures.js` labels cover all stable codes; unknown future codes
degrade safely (code preserved, label falls back). One cosmetic pre-existing wart
(documented, not changed): some 404 ApiErrors carry the default `INTERNAL_ERROR` code
(e.g. invalid timetable view) — safe and frontend-tolerated.

## 18. Repository hygiene

- `git status`: only intended 6V files (5 modified + 2 new); no untracked strays; no temp
  DBs inside the repo (all probes used OS temp dirs; `git status --short --ignored=no`
  clean apart from the 6V change set).
- Ignored correctly: `venv/`, `node_modules/`, `frontend/dist/` (rebuilt, not tracked),
  `__pycache__/`, `.pytest_cache/`, `*.db` (except the tracked demo DB), `.env`.
  No `backups/` dir, no `*.log` under `backend/instance/`.
- `templates/` at repo root is an empty, untracked leftover directory (no Jinja code
  remains — the retired frontend is fully gone); left untouched per phase rules.
- `docs/` holds two historical phase notes; no stale migration artifacts; no duplicate
  route implementations, validators, API clients, or scheduler helpers found.
- `.env` (local dev credentials) untracked; `.env.example` placeholders-only.

## 19. Defects found

### 6V-1 — Wrong-method GET on `/api/*` returned JSON 404 on the real app (LOW, FIXED)
- Evidence: `GET /api/schedule/run` (authed, real `backend.app`) → `404 NOT_FOUND` JSON
  pre-fix; the 6U regression test passed only because its harness lacks the SPA catch-all.
  Root cause: `@app.route("/<path:path>", methods=["GET"])` matches first, shadowing
  routing-level 405s; `serve_react` aborted 404 for all `/api/` paths.
- Fix: `api_catchall_response()` in `backend/app.py` — matches the path with `POST`
  against the URL map; a POST hit (or any method beyond the catch-all's own
  GET/HEAD/OPTIONS) returns the unified 405 `METHOD_NOT_ALLOWED` JSON, else 404.
  Non-API SPA behavior byte-identical. Verified: `GET /api/schedule/run`, `GET /api/login`
  → 405 JSON; unknown `/api/*` → 404 JSON; `POST /api/dashboard` → 405 JSON.
- Regression tests: `TestProductionWrongMethodJson6V` (3 tests, production-shaped app
  using the real helper + real `init_api` wiring).

### 6V-2 — Checked-in reference DB schema incompatible with current ORM (HIGH, repair path FIXED; artifact refresh REQUIRED)
- Evidence: current app against an isolated copy of `backend/instance/timetable.db`
  → sanitized 500s on `/api/dashboard`, `/api/timetable`, `/api/schedule/classes`,
  `/api/assignments`, `/api/overview` (ORM selects missing
  `preferred_theory_room_id`/`specialization_id`/`is_locked*`; even `count()` fails).
  Root cause: the file was produced by `create_all()` from an intermediate models.py —
  6C-era tables exist but additive columns were never added and no
  `schema_migrations` history exists. Sanitization held (no leak), but the default
  deploy path is functionally broken.
- Fix (code): idempotent migration upgrades (§7) + verified repair procedure. The
  reference file itself was NOT modified (phase rule); **mandatory pre-deploy action L1**.
- Regression tests: `TestHybridMigrationRepair6V` (4 tests: full repair + preservation,
  idempotence, downgrade/re-upgrade round-trip, ORM readability post-repair).

### 6V-3 — Migration runner crashed on partially-migrated DBs instead of repairing (HIGH, FIXED)
- Evidence: `migrate --db <reference-copy> upgrade` → `OperationalError: table
  specialization already exists`, nothing applied. Root cause: 6C/6E/6F upgrades used
  blind `CREATE TABLE` / `ADD COLUMN` (only 6J was idempotent).
- Fix: `_helpers.py` (`ensure_table`/`ensure_column` via `sqlite_master`/`PRAGMA
  table_info`) + idempotent `upgrade()` in 6C/6E/6F (canonical DDL preserved, `IF NOT
  EXISTS` where SQLite supports it). Downgrades untouched; runner atomicity (version row
  only after success) and `--allow-live` guard unchanged. Existing migration tests
  (`test_migration_6c/6j`) pass unmodified.
- Regression tests: same `TestHybridMigrationRepair6V` class as 6V-2.

No other defects found. No CRITICAL issues. Scheduler behavior, API contracts, error
codes, propagation domains, and frontend behavior are unchanged except the two minimal
fixes above.

## 20. Known limitations

**Mandatory pre-deploy actions (not optional):**

- **L1 — Migrate the database file before serving.** The checked-in
  `backend/instance/timetable.db` is pre-migration (see §6). On a copy (or
...[truncated 7370 chars]