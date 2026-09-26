# Phase 6P.1 — Live Propagation / Cache Invalidation Audit

> Branch: `frontend` · Commit: `a370992` · Scope: audit-only, no source modified.
> Frontend: `frontend/src/` · Backend: `backend/` · DB access: read-only (hashes recorded, §verification note at end of investigation; no writes performed).

---

## 1. Executive Summary

1. **There is no cache to invalidate.** No React Query/TanStack, no Redux/Zustand/Jotai/SWR, no custom query cache, no React context store, no `localStorage`/`sessionStorage` state, no event bus, no backend cache, no SSE/WebSocket, no background job. Verified by code read + `package.json` + repo-wide grep (details in §2–§4).
2. **Current propagation model = "independent GET-on-mount + manual local `retry()`".** Each page owns one (or two) `useApi` fetches that fire once on mount; each mutation dialog owns a `useMutation` that knows nothing about reads. After a successful mutation the *same page* calls its own `retry()` (via `onCreated`/`onSaved`/`onApplied`/`onGenerated`/`onStale` props). Nothing else is notified.
3. **Local (same-page) freshness is already handled almost everywhere.** Every CRUD page refetches its own list after create/delete; the editor refetches after move; assignments refetch after reassign/swap/delete; locked-blocks refetch after create/delete; specializations refetch both queries after membership changes; generation refetches timetable home.
4. **Cross-page / cross-surface staleness is confirmed and systematic.** A mutation updates the database synchronously, but pages that are already mounted (or visited earlier in the SPA session without remount) keep showing their previously fetched snapshot until the user navigates back (remount → fresh GET) or manually retries. Concrete confirmed risks: move → stale timetable views/editor/free-faculty/overview; reassign/swap → stale timetable + overview + locked-block assignment labels; generation → stale editor/views/overview/free-faculty/dashboard counts; locked-block create/delete → stale editor/timetable/assignments; specialization membership → stale sections-derived data only where consumed. See §6.
5. **Backend needs no invalidation.** Every `GET` is a fresh authoritative `SELECT`; every authoritative `POST` commits synchronously before responding (or rolls back atomically); validation-only endpoints are provably read-only. Explicit statement: **No backend cache requiring invalidation was found.**
6. **Recommended 6P.2 architecture: lightweight central invalidation/event mechanism (option 2), with local `retry()` retained as the execution primitive.** No new data-fetching dependency. A tiny pub/sub of logical resource domains (`schedule`, `assignments`, `lockedBlocks`, `specializations`, `sections`, `rooms`, `faculty`, `preferences`, `overview`, `dashboard`, `config`) where successful authoritative mutations emit domain events and mounted `useApi` consumers re-fetch once. Only successful mutations emit; failures and validation-only calls never emit. This is the smallest architecture that fixes confirmed cross-page staleness without the regression risk/complexity of TanStack Query, a global store, context state, or sockets.

---

## 2. Current State Architecture

### 2.1 Repository inventory (with file paths)

**Fetch/mutation primitives (the only two hooks in the app):**

| File | Role |
|---|---|
| `frontend/src/hooks/use-api.js` (42 lines) | Sole GET hook. Returns `{ data, error, isLoading, retry }`. |
| `frontend/src/hooks/use-mutation.js` (39 lines) | Sole mutation hook. Returns `{ execute, isSubmitting, error, fieldErrors, reset }`. No invalidation awareness. |
| `frontend/src/services/api/client.js` (85 lines) | Sole `fetch` call site (`client.js:47`). `ApiError` envelope (`client.js:11-27`), `request()` (`client.js:33-79`), `api.get/post/del` (`client.js:81-85`; `del` exported but never used — deletes are `POST …/delete`). |
| `frontend/src/lib/failures.js` (73 lines) | `getFailures(error)` + `FAILURE_LABELS` + `failureContext()` for 422 `failures[]` rendering via `<FailureList>`. |
| `frontend/src/lib/utils.js` | Only `cn()` (`clsx`+`twMerge`). No cache. |
| `frontend/src/app/providers.jsx` (11 lines) | `ToastProvider > AuthProvider`. No query/store provider. |
| `frontend/src/app/auth.jsx` | `AuthProvider`: session `GET /api/me` on mount, `login/logout/refresh`. Not a data cache. |
| `frontend/src/app/router.jsx` (61 lines) | `createBrowserRouter` (`router.jsx:28`); no loaders/actions; all fetching in-component. Routes: `/login` public; guarded: `/`, `/config`, `/rooms`, `/faculty`, `/faculty/:fid/availability`, `/faculty/:fid/preferences`, `/programs`, `/enrollments`, `/enrollments/:eid/sections`, `/enrollments/:eid/specializations`, `/enrollments/:eid/specializations/:sid`, `/subjects`, `/assignments`, `/import`, `/overview`, `/timetable`, `/timetable/editor`, `/timetable/free`, `/timetable/locked-blocks`, `/timetable/:view/:id`, `/account/change-password`, `*`. |
| `frontend/src/components/feedback/toast.jsx` + `hooks/use-toast.js` | Ephemeral notifications only (max 4, 5 s auto-dismiss). No persistence. |
| `frontend/src/components/feedback/mutation.jsx` | `<FailureList>`, `<DeleteConfirmDialog>`, `<LoadWarning>`. Display only. |
| `frontend/src/components/feedback/data-states.jsx` | `<PageLoading>`, `<QueryError onRetry>`. Display only. |

**API service layer — `frontend/src/services/api/*.js` (16 files):**

| File | Exports (method → endpoint) |
|---|---|
| `auth.js` | `login` POST `/api/login[?next=]`; `logout` POST `/api/logout`; `me` GET `/api/me`; `changePassword` POST `/api/change-password` |
| `config.js` | `getConfig` GET `/api/config`; `saveConfig` POST `/api/config` |
| `dashboard.js` | `getDashboard` GET `/api/dashboard` |
| `rooms.js` | `getRooms` GET `/api/rooms`; `createRoom` POST `/api/rooms`; `deleteRoom` POST `/api/rooms/:id/delete` |
| `faculty.js` | `getFaculty` GET `/api/faculty`; `createFaculty` POST `/api/faculty`; `deleteFaculty` POST `/api/faculty/:id/delete`; `getFacultyAvailability` GET `/api/faculty/:fid/availability`; `saveFacultyAvailability` POST `/api/faculty/:fid/availability`; `getFacultyPreferences` GET `/api/faculty/:fid/preferences`; `createFacultyPreference` POST `/api/faculty/:fid/preferences`; `updateFacultyPreference` POST `/api/faculty/preferences/:pid`; `deleteFacultyPreference` POST `/api/faculty/preferences/:pid/delete` |
| `programs.js` | `getPrograms` GET `/api/programs`; `createProgram` POST `/api/programs`; `deleteProgram` POST `/api/programs/:id/delete` |
| `enrollments.js` | `getEnrollments` GET `/api/enrollments`; `getEnrollmentSections` GET `/api/enrollments/:eid/sections`; `createEnrollment` POST `/api/enrollments`; `deleteEnrollment` POST `/api/enrollments/:id/delete`; `setPreferredTheoryRoom` POST `/api/sections/:sid/preferred-room` |
| `specializations.js` | `getSpecializations` GET `/api/specializations`; `getSpecialization` GET `/api/specializations/:id`; `createSpecialization` POST `/api/specializations`; `deleteSpecialization` POST `/api/specializations/:id/delete`; `saveMembership` POST `/api/specializations/:sid/memberships`; `deleteMembership` POST `/api/specializations/:sid/memberships/delete` |
| `subjects.js` | `getSubjects` GET `/api/subjects`; `createSubject` POST `/api/subjects`; `deleteSubject` POST `/api/subjects/:id/delete` |
| `assignments.js` | `getAssignments` GET `/api/assignments`; `createAssignment` POST `/api/assignments`; `deleteAssignment` POST `/api/assignments/:id/delete`; `validateReassignFaculty` POST `/api/assignments/:aid/validate-reassign`; `reassignFaculty` POST `/api/assignments/:aid/reassign`; `validateFacultySwap` POST `/api/assignments/validate-swap`; `swapFaculty` POST `/api/assignments/swap` |
| `import.js` | `importRoomsCsv` POST `/api/import/rooms` (FormData); `importWorkloadCsv` POST `/api/import/workload` (FormData) |
| `overview.js` | `getOverview` GET `/api/overview` |
| `schedule.js` | `getScheduledClasses` GET `/api/schedule/classes`; `validateMove` POST `/api/schedule/classes/:id/validate-move`; `moveScheduledClass` POST `/api/schedule/classes/:id/move` |
| `timetable.js` | `getTimetableHome` GET `/api/timetable`; `getTimetableView` GET `/api/timetable/:view/:id` (`section\|faculty\|room`); `getFreeFaculty` GET `/api/timetable/free[?day=]`; `runScheduler` POST `/api/schedule/run`; `exportUrl` plain `<a href>` GET `/export/:view/:id/:fmt` (no `fetch`) |
| `lockedBlocks.js` | `getLockedBlocks` GET `/api/locked-blocks`; `createLockedBlock` POST `/api/locked-blocks`; `deleteLockedBlock` POST `/api/locked-blocks/:id/delete` |

**Pages — `frontend/src/pages/**/*.jsx` (18 files):** `Dashboard/DashboardPage.jsx`, `Config/ConfigPage.jsx`, `Rooms/RoomsPage.jsx`, `Faculty/FacultyPage.jsx` (3 routes: list, `:fid/availability`, `:fid/preferences`), `Programs/ProgramsPage.jsx`, `Enrollments/EnrollmentsPage.jsx` (`EnrollmentsPage`, `SectionsPage`), `Specializations/SpecializationsPage.jsx` (`SpecializationsPage`, `SpecializationDetailPage`), `Subjects/SubjectsPage.jsx`, `Assignments/AssignmentsPage.jsx`, `Import/ImportPage.jsx`, `Overview/OverviewPage.jsx`, `Timetable/TimetablePage.jsx` (`TimetablePage`, `TimetableViewPage`, `GeneratePanel`), `Timetable/TimetableEditorPage.jsx` (`TimetableEditorPage`, `MoveDialog`, `DetailsDialog`), `LockedBlocks/LockedBlocksPage.jsx`, `FreeFaculty/FreeFacultyPage.jsx`, `Login/LoginPage.jsx`, `Account/ChangePasswordPage.jsx`, `NotFoundPage.jsx`.

**Backend — `backend/*.py`:**

| File | Role |
|---|---|
| `backend/app.py` (197 lines) | Flask app, session auth, SPA fallback, CSV sample + export routes. No state. |
| `backend/api_routes.py` (1896 lines) | All 56 `/api/*` routes on `api_bp` (`api_routes.py:27`). No caching. |
| `backend/models.py` (384 lines) | `db = SQLAlchemy()` (`models.py:9`); `init_db` (`models.py:378-384`). No session management code. |
| `backend/__init__.py` (4 lines) | Package docstring only. |
| `backend/scheduler.py` (1075 lines) | Pure CP-SAT `run_scheduler`; locals only; solver per call. |
| `backend/manual_edits.py` (467 lines) | Move validate + atomic move. Never imports Flask. |
| `backend/faculty_reassignment.py` (587 lines) | Reassign validate + atomic reassign. |
| `backend/faculty_swaps.py` (483 lines) | Swap validate + atomic swap. |
| `backend/faculty_preferences.py` (566 lines) | Preference CRUD + scheduler-row query. |
| `backend/locked_blocks.py` (644 lines) | Locked-block validate + atomic create/delete + placement query. |
| `backend/specializations.py` (590 lines) | Specialization/membership CRUD + spec-info query. |
| `backend/schedule_validator.py`, `schedule_rules.py`, `validators.py`, `helpers.py`, `csv_import.py`, `export.py`, `seed_demo.py`, `migrate.py`, `backup.py`, `audit_schedule.py` | Validation/rules/import/export/ops helpers. No caches (verified by grep). |

**Dependencies proving absence of cache/store/query layers:**

- `frontend/package.json:12-31`: `react`, `react-dom`, `react-router`, Radix UI, `lucide-react`, `tailwindcss`, `clsx`, `class-variance-authority`, `tailwind-merge`. Absent: `react-query`, `@tanstack/*`, `zustand`, `redux`, `react-redux`, `@reduxjs/toolkit`, `swr`, `jotai`, `recoil`, `valtio`, `axios`. Repo grep for `tanstack|react-query|zustand|redux|swr|jotai|recoil|queryClient|QueryClient` → zero hits.
- `backend/requirements.txt:1-7`: `Flask`, `Flask-SQLAlchemy`, `Flask-Login`, `ortools`, `openpyxl`, `gunicorn`, `python-dotenv`. No `Flask-Caching` or any cache package.
- `localStorage|sessionStorage` in `frontend/src` → 2 comment-only hits, 0 calls (`app/auth.jsx:12`, `pages/Login/LoginPage.jsx:15` — both explicitly say "no localStorage").
- React contexts in `frontend/src` → exactly 2, neither a data cache: `AuthContext` (`hooks/use-auth.js:3`, session only) and `ToastContext` (`hooks/use-toast.js:3`, ephemeral toasts).
- Event buses/sockets in `frontend/src` → none. Only `addEventListener` in repo is `hooks/use-media-query.js:12-13` (`matchMedia change` for sidebar). No `CustomEvent`, `dispatchEvent`, `BroadcastChannel`, `socket`, `EventSource`.

---

## 3. Frontend Fetch / Cache Architecture

### 3.1 `useApi` (`frontend/src/hooks/use-api.js:1-42`) — verbatim behavior

```js
export function useApi(fetcher) {                       // :9
  const [data, setData] = useState(null);               // :10
  const [error, setError] = useState(null);             // :11
  const [isLoading, setIsLoading] = useState(true);     // :12
  const [attempt, setAttempt] = useState(0);            // :13
  const retry = useCallback(() => {                     // :15-19
    setError(null); setIsLoading(true); setAttempt((n) => n + 1);
  }, []);
  useEffect(() => {                                     // :21-39
    let cancelled = false;
    fetcher().then(
      (result) => { if (cancelled) return;               // :25
        setData(result); setError(null); setIsLoading(false); },  // :26-28
      (err) => { if (cancelled) return;                  // :31
        setError(err); setIsLoading(false); }            // :32-33
    );
    return () => { cancelled = true; };                  // :37
  }, [attempt, fetcher]);                                // :39
  return { data, error, isLoading, retry };              // :41
}
```

Answers with evidence:

1. **Does `useApi` cache? No.** `data` is plain component-local `useState(null)` (`use-api.js:10`). No `Map`, no module store, no `QueryClient`, no storage. Each mount starts `null` + `isLoading:true`.
2. **Does it deduplicate? No.** Every `useApi` instance fires its own `fetcher()` independently. Parallel examples: `SpecializationsPage.jsx:464,466` (2 parallel `useApi`s), `EnrollmentsPage.jsx:408-409` (`SectionsPage`: sections + rooms), `TimetableEditorPage.jsx:65-75` (composite `Promise.all([getScheduledClasses(), getRooms()])` inside one `useApi`), `LockedBlocksPage.jsx:49-58` (composite `Promise.all` of 4 reads inside one `useApi`).
3. **Does it expose `refetch`? Only manual `retry`.** `retry()` = clear error + `setIsLoading(true)` + bump `attempt` → effect re-runs (`use-api.js:15-19,39`). No `refetch` alias, no arguments, no force/bypass option.
4. **Does it refetch on mount? Yes — GET-on-mount once** (plus on `fetcher` identity change or `retry`). `useEffect([attempt, fetcher])`. Param-dependent pages stabilize with `useCallback`, e.g. `FacultyPage.jsx:333` (`getFacultyAvailability(fid)`), `TimetablePage.jsx:256` (`getTimetableView(view,id)`), `FreeFacultyPage.jsx:43` (`getFreeFaculty(day)`), `EnrollmentsPage.jsx:407`, `SpecializationsPage.jsx:465,685`.
5. **Does it refetch on window focus? No.** No `focus`/`visibilitychange`/`online` listeners anywhere in `src` (only `matchMedia` in `use-media-query.js:12`).
6. **Does it retain previous data? Partially — by accident of `retry` not clearing `data`.** `retry()` sets `isLoading:true` but leaves `data` intact (`use-api.js:16-18`). Pages branch `isLoading && !data → <PageLoading>` vs `error && !data → <QueryError>` (e.g. `DashboardPage.jsx:83,91`; `RoomsPage.jsx:177,185`; `FreeFacultyPage.jsx:115-116` keeps old table + inline loader during day-tab switch). There is no `keepPreviousData` option and no stale-while-revalidate beyond this.
7. **Does `useMutation` know affected reads? No.** `use-mutation.js:9-38`: `execute(args)` → `mutateFn(args)` → `{ ok:true,data }` or `{ ok:false,error }`, plus `isSubmitting/error/fieldErrors/reset`. No `onSuccess` option, no domain list, no invalidation call. Grep for `onSuccess|onUpdated|invalidate` in `src` → zero hook-option hits; cross-component signalling is done ad hoc by parent callbacks (see §7-adjacent §6… actually §7 in report numbering: "Already-Handled Propagation").
8. **Is there shared API response state? No.** No context/store/prop-drilled cache holds responses. Filters/dialog state are per-page `useState`; `useMemo` uses are pure UI derivations (e.g. `TimetableEditorPage.jsx:739-755`, `FreeFacultyPage.jsx:46-52`, `SpecializationsPage.jsx:326-330`).
9. **Are responses stored globally? No.** Responses live in the `useApi` instance that fetched them and die with the component.
10. **Does route navigation remount enough components to hide stale-state problems? Mostly yes for the navigated-to page, no for everything else.** React Router unmounts the old page and mounts the new one, so the *destination* page always performs a fresh GET (this masks staleness on arrival). But (a) any already-mounted page the user returns to via back-navigation without remount keeps old state only if the router reuses it — in this `createBrowserRouter` setup each navigation mounts fresh, so the practical staleness window is: *page A mutates DB → user navigates to page B that was already visited earlier in the session is fine (remount refetches), but any page currently holding derived schedule state that is NOT remounted (e.g. open in another tab, or the editor behind a dialog, or overview/dashboard counts fetched before generation) stays stale until manually retried.* There is no polling or focus refetch to close that window. See §6 for per-scenario classification.

### 3.2 `useMutation` (`frontend/src/hooks/use-mutation.js:1-39`)

Thin `isSubmitting/error/fieldErrors` tracker only. Caller-side contract everywhere:

```js
const result = await execute(args);          // e.g. RoomsPage.jsx:165-175
if (result.ok) { toast.success(...); retry(); }   // parent refetch = manual
else toast.error(...);                            // no refetch (correct)
```

No optimistic updates anywhere (the editor file header explicitly forbids it: `TimetableEditorPage.jsx:60-61` "never patches the timetable optimistically — the refetched schedule is the only source of truth").

### 3.3 Client, retry, and error shape

- `client.js:47` is the only `fetch` in `src`; `credentials:"same-origin"` (`client.js:50`); JSON in/out (`client.js:40-41`); `FormData` for CSV (`client.js:37-38`); `signal` supported (`client.js:52`) but no caller passes an `AbortController` — cancellation is only the boolean `cancelled` flag in `useApi`.
- Errors surface as `ApiError { message, status, fieldErrors, payload }` (`client.js:11-27,66-76`); `isAuth` = 401, `isValidation` = 422. 422 payloads carry `{ error, code, details, failures }`, rendered via `getFailures` + `<FailureList>` and `<LoadWarning>` on dry-run warnings.

---

## 4. Backend State / Cache Architecture

> No backend cache requiring invalidation was found.

Evidence of absence (all verified by read + grep over `backend/*.py`):

| Category | Verdict | Proof |
|---|---|---|
| `Flask-Caching` / `Cache()` | Absent | `requirements.txt:1-7` has no cache package; grep `import.*cache\|from.*cache\|Cache\(` → 0 prod hits. |
| `lru_cache` / `@cache` / `memoize` | Absent | Grep `lru_cache\|functools\.cache\|@cache\|memoiz` → 0 hits. Sole false positive is request-local `_spec_slots_cache` (see below). |
| Module-level mutable cache | Absent | `app.py`: only `app`, `login_manager`, `SAMPLE_DIR`/`DIST_DIR` constants. `api_routes.py:27-29`: only `api_bp` + `TIMETABLE_VIEWS`. `models.py:9`: only `db = SQLAlchemy()`. `scheduler.py`: zero module globals. |
| Background jobs / threads / Celery / APScheduler | Absent | Grep `threading\|Thread\|celery\|apscheduler\|BackgroundScheduler` → 0 hits. `POST /api/schedule/run` is synchronous `run_scheduler(..., time_limit_seconds=30)` (`api_routes.py:1338-1347`), OR-Tools `CpSolver(max_time_in_seconds)` + `num_search_workers=8` per call, then discarded. |
| SSE / WebSocket / SocketIO / streaming | Absent | Grep `websocket\|socketio\|EventSource\|Response(stream` → 0 hits. All responses are `jsonify(...)`. |
| Long-lived ORM objects / snapshots | Absent | Every handler builds snapshots per request and discards them (e.g. `manual_edits._load_snapshot` docstring "Read-only: issues SELECTs only"; `schedule_validator.snapshot_without` returns a copy). Post-commit `db.session.refresh(...)` only re-attaches the just-written row for serialization. |

The only cache-*named* identifier is request-local, not a cache:

```python
# backend/api_routes.py:1397-1418 — created fresh per POST /api/schedule/run, dies with the request
_spec_slots_cache = {}  # (spec_id, day, start, length) -> slot_id
```

**SQLAlchemy session lifecycle (stale-read risk: none found requiring changes):** `db = SQLAlchemy()` (`models.py:9`); `init_db` does `db.init_app(app)` + `db.create_all()` + seed `Config` (`models.py:378-384`). No `@app.teardown_*`, no `scoped_session` import, no `db.session.remove()` in prod code (only `tests/*` use `remove()`). Flask-SQLAlchemy 3.1.1 owns a request-scoped session with automatic teardown; handlers `query/add/delete` → `commit()` on success or `rollback()` in guarded services (preferred-room `api_routes.py:417-424`, preferences, move, reassign, swap, locked-blocks, specializations, schedule/run legacy path) → session torn down after response. Simple CRUD routes rely on commit-or-teardown. No evidence of cross-request session reuse; **no session change recommended.**

**Route inventory (method + path → handler):** full table in investigation; key rows: `POST /api/schedule/classes/<id>/move` → `api_move_class` (`api_routes.py:1683`); `POST …/validate-move` → `api_validate_move` (`1649`); `POST /api/assignments/<aid>/validate-reassign` (`1106`) / `POST …/reassign` (`1140`); `POST /api/assignments/validate-swap` (`1172`) / `POST …/swap` (`1213`); preferences `GET /api/faculty/<fid>/preferences` (`718`), `POST …/preferences` (`747`), `POST /api/faculty/preferences/<pid>` (`771`), `POST …/delete` (`793`); preferred room `POST /api/sections/<sid>/preferred-room` (`368`); specializations `GET /api/specializations` (`1754`), `GET /api/specializations/<sid>` (`1766`), `POST /api/specializations` (`1775`), `POST …/delete` (`1809`), `POST …/memberships` (`1824`), `POST …/memberships/delete` (`1850`); locked blocks `GET /api/locked-blocks` (`1458`), `POST /api/locked-blocks` (`1485`), `POST …/delete` (`1538`); assignments `GET /api/assignments` (`458`), `POST /api/assignments` (`931`), `POST …/delete` (`1033`); `POST /api/schedule/run` (`1281`); reads `GET /api/dashboard` (`279`), `GET /api/overview` (`500`), `GET /api/timetable` (`533`), `GET /api/timetable/<view>/<id>` (`545`), `GET /api/timetable/free` (`567`), `GET /api/schedule/classes` (`1558`).

---

## 5. Mutation → Read Dependency Matrix

Legend: ✅ surface exists and reads the affected state · — surface does not consume it · `retry-today` = only the mutating page refetches itself today.

Only surfaces actually present in code are listed.

### A. Manual timetable move — `POST /api/schedule/classes/<id>/move` (`schedule.js:49`, `api_routes.py:1683`)

Authoritative: rewrites `day/start_period/room_id` only; preserves `assignment/length/run_id/is_locked/slot_id/locked_block_id` (`api_routes.py:1684-1688`); atomic validate→flush→re-verify→commit/rollback (`manual_edits.py:410-467`); `noop:true` = zero writes (`api_routes.py:1700-1704`).

| Consumer (read endpoint) | Consumes moved placement? | Refetch after move today? |
|---|---|---|
| Editor `GET /api/schedule/classes` (`TimetableEditorPage.jsx:65-75,724`) | ✅ | ✅ Yes — `handleApplied → query.retry()` (`:774-778`); apply-failure also refetches via `onStale → query.retry()` (`:499,936`) |
| Timetable views `GET /api/timetable/:view/:id` (`TimetablePage.jsx:256-257`) | ✅ | ❌ No — view page has no mutation hook and no listener; fresh only on (re)mount |
| Timetable home `GET /api/timetable` | Indirect (`has_schedule` flag only) | ❌ No (only `GeneratePanel onGenerated → retry`) |
| Free faculty `GET /api/timetable/free` (`FreeFacultyPage.jsx:43-44`) | ✅ (occupancy derived) | ❌ No (refetch only on day-tab change / manual retry) |
| Overview `GET /api/overview` | ✅ if overview renders schedule-derived cells (verify: `api_overview` builds enrollment/faculty structure; schedule cells resolved client-side from timetable reads — treat as schedule-adjacent) | ❌ No |
| Dashboard `GET /api/dashboard` (counts incl. `scheduled`) | Weakly (count changes only if move is first/last class — normally unchanged) | ❌ No |
| Assignments `GET /api/assignments` | ✅ faculty label shown in editor via joined read, but move does not change assignment rows | N/A (no change) |
| Locked/spec representations | Move of locked/spec classes is rejected server-side (`LOCKED_BLOCK` / `SPECIALIZATION_SYNC`) | N/A |

### B. Faculty reassignment — `POST /api/assignments/<aid>/reassign` (`assignments.js:61`, `api_routes.py:1140`)

Authoritative: `faculty_id=` → flush → post-flush snapshot verify → commit+refresh, rollback on any path (`faculty_reassignment.py:541-587`); placements preserved (faculty via assignment join); locked-side rejected (`LOCKED_BLOCK`); soft weekly-load `warning` never blocks.

| Consumer | Consumes? | Refetch today? |
|---|---|---|
| Assignments `GET /api/assignments` (`AssignmentsPage.jsx:650`) | ✅ | ✅ Yes — `handleReassigned → retry()` (`:675-678`) |
| Timetable views / editor (`GET /api/timetable/:view/:id`, `GET /api/schedule/classes`) | ✅ (faculty label per class) | ❌ No cross-page emit |
| Faculty views `GET /api/faculty` (+ availability/preferences reads) | ✅ (load/name lists) | ❌ No |
| Specialization views | Only if the reassigned assignment is spec-linked (assignment row carries `specialization_id`) — then ✅ | ❌ No |
| Overview/dashboard | ✅ faculty-load derived | ❌ No |

### C. Faculty swap — `POST /api/assignments/swap` (`assignments.js:86`, `api_routes.py:1213`)

Atomic both-sides `A.faculty↔B.faculty` + single flush + verify + commit; rollback guarantees never half-swapped (`faculty_swaps.py:428-483`); rejects same-id (`INVALID_SWAP`), normal↔spec mix (`SPECIALIZATION_SWAP`), locked either side (`LOCKED_BLOCK`).

| Consumer | Consumes? | Refetch today? |
|---|---|---|
| Assignments | ✅ both rows | ✅ Yes — `handleSwapped → retry()` (`:680-683`) |
| Timetable / editor / faculty / spec / overview | ✅ same as reassignment ×2 | ❌ No cross-page emit |

### D. Faculty preferences — create `POST /api/faculty/<fid>/preferences` (`747`), update `POST /api/faculty/preferences/<pid>` (`771`), delete `POST …/delete` (`793`)

Authoritative config writes (`faculty_preferences.py:450-553`, `add+flush+commit+refresh`, `rollback` on error); success message explicitly "Future generations… current unchanged". Never touches `ScheduledClass`.

| Consumer | Consumes? | Refetch today? |
|---|---|---|
| `GET /api/faculty/:fid/preferences` (`FacultyPreferencesPage.jsx:800-801`) | ✅ | ✅ Yes — add/edit `onSaved → retry` (`:955,966`), delete `retry` (`:808-818`) |
| Generated schedule behavior | Future-generation-only (soft objective input to `run_scheduler` via `query_scheduler_rows`, `api_routes.py:1332-1336`) | Intentionally unchanged — correctly NOT refetched |

### E. Preferred/home theory room — `POST /api/sections/<sid>/preferred-room` (`enrollments.js:51`, `api_routes.py:368`)

Authoritative on `Section.preferred_theory_room_id` (`api_routes.py:417-424`, flush+commit+refresh, rollback on error; `warning` for lab/small room never rejects). Docstring: never touches timetable (`api_routes.py:369-376`).

| Consumer | Consumes? | Refetch today? |
|---|---|---|
| `GET /api/enrollments/:eid/sections` (`SectionsPage`, `EnrollmentsPage.jsx:407-409`) | ✅ | ✅ Yes — `PreferredRoomControl onSaved → retry` (`:338-353,559`) |
| Preference displays (rooms select in same page, `getRooms` parallel query `:409`) | ✅ | ✅ same retry (both queries are per-page; rooms list itself unchanged) |
| Generated schedule behavior | Future-generation-only soft objective (`preferred_theory_rooms`, `api_routes.py:1319-1326`) | Intentionally unchanged |

### F. Specialization administration — create (`1775`), delete (`1809`), membership upsert (`1824`), membership delete (`1850`)

Thin wrappers over `specializations.py` (`add+commit+refresh`, `rollback` on exception; `to_payload()` → `code/details/failures` preserved). Assignment-via-spec branch in `POST /api/assignments` (`api_routes.py:929,955-1002`).

| Consumer | Consumes? | Refetch today? |
|---|---|---|
| `GET /api/specializations` (list page `:464`) | ✅ | ✅ Yes — `refetchAll()` (both queries `:472-475`), create `onCreated → refetchAll` (`:648`), delete `→ refetchAll` (`:482-492`) |
| `GET /api/specializations/:sid` (detail `:685-688`) | ✅ | ✅ Yes — remove `→ refetchAll` (`:706-716`); delete navigates away (`:718-727 → navigate(/enrollments/:eid/specializations)`) |
| `GET /api/enrollments/:eid/sections` (membership context) | ✅ (section options) | ✅ Yes (second half of `refetchAll`) |
| Assignments / enrollments / timetable / editor / schedule output | ✅ where spec-linked (spec assignments, `SpecializationSlot` rows, synchronized placements) | ❌ No cross-page emit |

### G. Locked/fixed blocks — create `POST /api/locked-blocks` (`1485`), delete `POST …/delete` (`1538`)

Fully atomic pair (`LockedBlock` + `ScheduledClass(is_locked=True, run_id="locked")`): `add+flush+commit+refresh`, rollback or neither (`locked_blocks.py:517-547,564-575`); shared validator, no bypass.

| Consumer | Consumes? | Refetch today? |
|---|---|---|
| Fixed-block page composite (`GET /api/locked-blocks` + `GET /api/assignments` + `GET /api/rooms` + `GET /api/config`, `LockedBlocksPage.jsx:49-58,332`) | ✅ | ✅ Yes — create `onCreated → query.retry` (`:487`), delete `→ query.retry` (`:344-354`) |
| Timetable / editor (`GET /api/schedule/classes`, `GET /api/timetable/:view/:id`) | ✅ (locked rows are schedule rows) | ❌ No cross-page emit |
| Assignments (labels/context in locked-block page) | ✅ display join | ✅ Yes (same composite retry) |
| Rooms/faculty/sections where displayed | Rooms ✅ (room occupancy); faculty/sections indirectly via assignment | ❌ No outside the fixed-block page |

### H. Assignment mutations — create `POST /api/assignments` (`931`), delete `POST …/delete` (`1033`)

`add+commit` / `delete+commit` (`201`/`200`); spec branch validates pre-commit; load-warning soft (`category: success|warning`).

| Consumer | Consumes? | Refetch today? |
|---|---|---|
| `GET /api/assignments` (`AssignmentsPage.jsx:650`) | ✅ | ✅ Yes — create `onCreated → retry` (`:830`), delete `→ retry` (`:685-695`), reassign/swap (above) |
| Locked-block page (assignment options) | ✅ | ❌ No (only refetches on its own mutations) |
| Timetable/editor/overview (faculty/subject/group labels) | ✅ display-level; schedule rows themselves unchanged until next generation | ❌ No |
| Specialization detail (spec assignments) | ✅ if spec-linked | ❌ No |

### I. Schedule generation — `POST /api/schedule/run` (`timetable.js:42`, `api_routes.py:1281`)

Replaces all non-locked `ScheduledClass` rows in one commit; preserves locked rows in place; prunes/rebuilds `SpecializationSlot`s; per-run `run_id = uuid4().hex[:10]` stored on each new row (`api_routes.py:1380,1419-1422`) and returned (`:1448-1452`) but consumed by no frontend code (panel shows `message/status/placements` only). Failure (`INFEASIBLE`/`NO_SESSIONS`) writes nothing — previous schedule preserved (`api_routes.py:1349-1374`).

| Effect | Triggered today? |
|---|---|
| Explicit refetch of timetable home (`GET /api/timetable`) | ✅ Yes — `GeneratePanel onGenerated → retry` (`TimetablePage.jsx:51-72,168`), called on **both** success and failure (`:64,70`) |
| Navigation / local state replacement / page reload | ❌ None — no `navigate`, no `reload`; result shown in local `result` state (`:62,68`) |
| Editor / views / overview / dashboard / assignments / free-faculty / locked-block labels | ❌ No — all stay on pre-generation snapshots until remount/manual retry |

---

## 6. Confirmed Stale-Data Risks

Rule applied: a risk is *confirmed* only where the mutated DB state is read by another mounted (or later-visited-without-remount) surface that has no refetch path today. Separate fetch calls alone are not counted — lifecycle is traced.

| # | Scenario | Verdict | Evidence / reasoning |
|---|---|---|---|
| 1 | Move a class in `/timetable/editor`, then open another timetable view | **Confirmed stale risk** | Move commits (`api_routes.py:1683-1708`); editor refetches itself (`TimetableEditorPage.jsx:774-778`). `TimetableViewPage` (`TimetablePage.jsx:256-292`) has no mutation path and no subscription — it is fresh only if (re)mounted. SPA navigation to it remounts (fresh), but an already-open view tab, or return-via-history without remount, shows the old placement. Same for `FreeFacultyPage` occupancy. |
| 2 | Reassign faculty, then open timetable | **Confirmed stale risk** | Reassign commits both assignment + derived class faculty (`faculty_reassignment.py:541-587`); assignments page refetches (`AssignmentsPage.jsx:675-678`). No emit to timetable/editor/faculty/overview. Destination timetable page is fresh on remount, stale otherwise (second tab, back-navigation edge, embedded overview). |
| 3 | Swap faculty assignments, then inspect both assignments/timetable | **Confirmed stale risk (timetable side); already handled (assignments side)** | Assignments list refetches (`:680-683`). Timetable/faculty/spec/overview consumers have no path — same staleness window as #2 ×2 rows. |
| 4 | Change preferred room; config updates vs existing timetable | **Already handled (config side); intentionally unchanged (schedule side — not a bug)** | `PreferredRoomControl onSaved → retry` refetches sections (`EnrollmentsPage.jsx:349,559`). Backend never touches timetable by design (`api_routes.py:369-376`); success message + `warning` semantics confirm. Future generations use it as soft objective (`:1319-1326`). No invalidation of schedule domains is correct here. |
| 5 | Change specialization membership; admin views vs schedule behavior | **Already handled (admin side); correctly understood (schedule side)** | List+detail `refetchAll()` covers both queries (`SpecializationsPage.jsx:472-475,696-699`). Existing generated classes are schedule output (`SpecializationSlot` + `slot_id`-linked rows, `api_routes.py:1376-1447`); membership edits do not rewrite them until next generation — correct, not stale. Cross-page spec-assignment labels (assignments/locked-block pages) are **confirmed stale** (no emit). |
| 6 | Create/delete locked block; fixed-block page vs timetable/editor | **Already handled (fixed-block page); confirmed stale (timetable/editor/assignments elsewhere)** | Page composite retry covers its own 4 reads (`LockedBlocksPage.jsx:350,487`). Editor/timetable read the same `ScheduledClass(is_locked)` rows (`GET /api/schedule/classes`, `GET /api/timetable/:view/:id`) with no path — stale until remount. |
| 7 | Generate a new schedule; all schedule-dependent views | **Confirmed stale risk (broadest fan-out)** | Only timetable home refetches (`TimetablePage.jsx:64,168`). Editor, all views, free-faculty, overview, dashboard counts, locked-block assignment context: all stale until remount/manual retry. Failure path also calls `onGenerated` (`:70`) — harmless (backend wrote nothing, `api_routes.py:1349-1374`) but causes one wasted home refetch. |

**Not applicable:** validation-only staleness (validate endpoints write nothing by construction — see §10); `Login`/`NotFound`/`Import` (no schedule reads); change-password (no domain overlap).

**Unclear / runtime verification needed:** whether React Router back/forward navigation in this `react-router@8.4.0` + React 19 setup always remounts page components (expected: yes for distinct routes, but bfcache-like reuse or `<StrictMode>` double-effects could alter timing); whether two tabs open on different pages is in scope for 6P.2 (recommend: same-tab only; cross-tab via storage events explicitly out of scope); exact overview schedule-derivation (whether `OverviewPage` joins timetable reads client-side or renders `GET /api/overview` alone — code read says the latter plus timetable-adjacent cells; runtime check with a generated schedule recommended before finalizing the overview domain mapping).

---

## 7. Already-Handled Propagation

All patterns are **local/manual refetch** (no shared invalidation, no optimistic update, no route refresh, no full-page reload anywhere — grep `window.location.reload` → 0 hits; `navigate` → 3 uses only: login `LoginPage.jsx:41,54`, post-delete `SpecializationsPage.jsx:723`, post-logout `sidebar.jsx:15`).

| Location | Pattern | Classification |
|---|---|---|
| Every CRUD list page (rooms `:171`, faculty `:208`, programs `:117`, enrollments `:159`, subjects `:226`, assignments `:691`, config `:55`) | `await execute(…); if ok { toast.success; retry() } else toast.error` | Local/manual refetch ✅ consistent |
| Add-dialogs (`AddRoomDialog :64`, `AddFacultyDialog :108`, `AddProgramDialog :43`, `AddEnrollmentDialog :65`, `AddSubjectDialog :72`, `AddAssignmentDialog :115`, `CreateSpecializationDialog :110`, `CreateLockedBlockDialog :157`) | `onCreated → parent retry()` + dialog `key={…}` remount | Local/manual refetch ✅ consistent |
| `ConfigPage.jsx:209` | `onSaved → retry` + `key={config.id}` form reset | Local/manual refetch ✅ |
| `FacultyAvailabilityPage.jsx:354-364` | `execute([...active]) → setSelected(new Set(result.data.unavailable)) + retry()` | Local/manual refetch + local state sync ✅ |
| `FacultyPreferencesPage.jsx:808-818,955,966` | delete/add/edit `→ retry()` | Local/manual refetch ✅ |
| `SectionsPage PreferredRoomControl` (`EnrollmentsPage.jsx:338-353`) | `execute → toast.success (+warning) → onSaved → retry` | Local/manual refetch ✅ |
| `SpecializationsPage.jsx:472-475,696-699` | `refetchAll() = specsQuery.retry() + sectionsQuery.retry()` (covers composite membership writes) | Local/manual refetch (2-query coalesced) ✅ |
| `SpecializationDetailPage.jsx:718-727` | delete `→ navigate(/enrollments/:eid/specializations)` | Route refresh (only delete-navigates case) ✅ appropriate |
| `AssignmentsPage.jsx:675-683` | `handleReassigned/handleSwapped → retry()` via `onApplied` | Local/manual refetch ✅ |
| Reassign/swap dialogs (two-phase validate→confirm, `AssignmentsPage.jsx:314-343,490-514`) | `validate.*` (dry-run, no emit) then `apply.* → onApplied` | Local/manual refetch; validation correctly side-effect-free ✅ |
| `MoveDialog` (`TimetableEditorPage.jsx:461-501`) | validate-before-apply with `validatedPayload` snapshot; success `→ onApplied → query.retry`; apply-failure `→ onStale → query.retry` | Local/manual refetch incl. failure-recovery refetch ✅ (only failure-refetch in the app besides generation) |
| `GeneratePanel` (`TimetablePage.jsx:57-72`) | `execute() → onGenerated → retry` on **both** branches | Local/manual refetch; failure-branch refetch is wasted-but-harmless (backend preserved schedule) — minor inconsistency, see §11 |
| `FreeFacultyPage.jsx:101` | day-tab `setSearchParams({day})` → `fetcher` identity change → auto-refetch | Route-param-driven refetch ✅ (no manual retry needed) |
| `ImportPage.jsx:56-67` | `await upload(file) → setResult/toast`, no `retry` (nothing to refetch — page has no `useApi`) | No refresh — correctly N/A ✅ |
| Delete dialogs everywhere | `deletion.reset()` on close (e.g. `RoomsPage.jsx:272`) | Error-state hygiene, not propagation ✅ |

**Duplicated/inconsistent patterns (minor, not bugs):** (a) composite-`Promise.all`-in-one-`useApi` (editor, locked-blocks) vs parallel `useApi`s (sections, specializations) — failure semantics differ (all-or-nothing vs partial; `SectionsPage` handles partial rooms failure gracefully `:444-445,548-561`, composite pages fail whole); (b) failure-branch refetch exists in editor-apply and generation but nowhere else — defensible (those two have server-side "state may have moved under you" semantics) but should be codified in the contract; (c) `GeneratePanel` refetching on generation *failure* is the only known wasted refetch.

---

## 8. Resource Domains

Derived strictly from actual endpoints and consumers (potential-only names excluded; `rooms`/`faculty`/`config` included because code proves schedule-adjacent consumption: editor rooms join, faculty-load joins, locked-block page config join).

| Domain | Source endpoints (GET) | Consumers (pages) | Mutations that invalidate it | Immediate vs future-generation-only |
|---|---|---|---|---|
| `schedule` | `GET /api/schedule/classes`; `GET /api/timetable`; `GET /api/timetable/:view/:id`; `GET /api/timetable/free` | Editor, timetable home/views, free-faculty, (overview schedule cells) | move; locked-block create/delete; generation (replace); reassign/swap (faculty label on classes) | Immediate |
| `assignments` | `GET /api/assignments` | Assignments page; locked-block page (options/labels); editor (via schedule join) | assignment create/delete; reassign; swap; locked-block create/delete (paired class); generation (placements reference assignments — labels, not rows) | Immediate (rows); generation = display-context only |
| `faculty` | `GET /api/faculty`; `GET /api/faculty/:fid/availability` | Faculty list/availability; assignments (options/load); locked-block options | faculty create/delete; availability save; reassign/swap (load) | Immediate |
| `preferences` | `GET /api/faculty/:fid/preferences` | Preferences page | preference create/update/delete | Immediate (config); schedule = future-only |
| `sections` | `GET /api/enrollments/:eid/sections`; `GET /api/enrollments` | Sections page; specializations (membership context); enrollments list | preferred-room set; enrollment create/delete; specialization membership (context) | Immediate (config); schedule = future-only |
| `specializations` | `GET /api/specializations`; `GET /api/specializations/:sid` | Spec list/detail | spec create/delete; membership upsert/delete; spec-assignment create | Immediate (config); schedule output = next generation |
| `lockedBlocks` | `GET /api/locked-blocks` | Fixed-block page; editor/timetable (as schedule rows) | locked-block create/delete | Immediate (both config record and schedule row) |
| `rooms` | `GET /api/rooms` | Rooms page; editor (destinations); sections (preferred-room select); locked-block page | room create/delete | Immediate |
| `overview` | `GET /api/overview` | Overview page | generation; reassign/swap (load); assignment create/delete | Immediate after generation; load-derived otherwise |
| `dashboard` | `GET /api/dashboard` | Dashboard | generation (counts, esp. `scheduled`); entity create/delete (counts) | Immediate but low-urgency (counts) |
| `config` | `GET /api/config` | Config page; locked-block page (day/period labels) | config save | Immediate |
| `programs` / `subjects` / `enrollments` / `import` | Their own GETs | Their own pages | Their own CRUD | Immediate, own-page only (no cross-domain fan-out found) |

**Confirmed mutation→domain matrix (code-confirmed relationships only):**

| Mutation | Resource(s) invalidated | Reason |
|---|---|---|
| Move class (`POST …/move`) | `schedule` | placement (day/start/room) changed |
| Reassign faculty (`POST …/reassign`) | `assignments`, `schedule`, `faculty`, `overview` | ownership + class faculty label + load changed |
| Swap faculty (`POST …/swap`) | `assignments`, `schedule`, `faculty`, `overview` | two ownerships + labels + loads changed |
| Preferred room (`POST /api/sections/:sid/preferred-room`) | `sections` | preference changed; current schedule intentionally unchanged |
| Faculty preference create/update/delete | `preferences` | config changed; current schedule intentionally unchanged |
| Specialization create/delete | `specializations` | config changed |
| Membership upsert/delete | `specializations`, `sections` | membership + section context changed; schedule output changes only at next generation |
| Spec-assignment create (`POST /api/assignments` spec branch) | `assignments`, `specializations` | new assignment row + spec linkage |
| Locked-block create/delete | `lockedBlocks`, `schedule`, `assignments` (labels) | config record + paired `is_locked` schedule row + assignment display context |
| Assignment create/delete | `assignments`, `overview` | rows + derived load/counts |
| Generate schedule (`POST /api/schedule/run`, success) | `schedule`, `overview`, `dashboard`, `assignments` (display context), `lockedBlocks` (context), `specializations` (slots output) | non-locked schedule rows replaced; slots pruned/rebuilt; counts/loads derived |
| Faculty/room/program/enrollment/subject/config/availability CRUD | own domain only (`faculty`, `rooms`, `programs`/`enrollments`/`subjects`, `config`) | no cross-domain consumption found beyond locked-block page joins (`rooms`/`config`/`assignments` already covered) |

Successful mutation alone is sufficient to invalidate — no version handshake needed (backend commits synchronously before responding; see §10).

---

## 9. Schedule Generation Propagation

- **Changed API-visible state:** all `ScheduledClass` rows with `is_locked=False` deleted and re-inserted with a fresh per-run `run_id` (`api_routes.py:1380-1383,1419-1422`); `is_locked=True` rows preserved untouched (`:1376-1377`); `SpecializationSlot` rows pruned/rebuilt to equal the new schedule (`:1423-1446`); `run_id` returned (`:1448-1452`) but consumed by no frontend code.
- **Run/generation identifier:** per-run `run_id = uuid4().hex[:10]` exists on rows + response (`api_routes.py:1380,1421,1450`). There is **no** global schedule-version counter, no `GET /api/schedule/version`, no generation timestamp endpoint. The frontend does not need one under the recommended design (invalidation is event-driven on the success response, not version-polled) — see §12.
- **Whether components know generation completed:** only `TimetablePage` (via `GeneratePanel onGenerated`). No other component observes it.
- **Whether timetable pages refetch:** home yes (`TimetablePage.jsx:64,168`); editor/views/free-faculty no.
- **Whether overview/dashboard is schedule-derived:** dashboard counts include `scheduled` (`api_dashboard`, `api_routes.py:279`); overview builds enrollment/faculty structure with schedule-adjacent cells — both change on generation. Neither refetches today.
- **Whether assignment data itself changes:** no rows rewritten by generation (assignments are solver *inputs*, `api_routes.py:1288`); only display context (placements referencing them) changes.
- **Exact domains to invalidate after successful generation:** `schedule`, `overview`, `dashboard` (primary); `assignments`, `lockedBlocks`, `specializations` as display-context refresh where mounted (cheap GETs, avoids stale labels/slots). `preferences`, `sections`, `rooms`, `faculty`, `config` do **not** invalidate on generation (inputs, unchanged).

---

## 10. Failure / Rollback Semantics

**Required rule (adopted for 6P.2+): only successful authoritative mutations trigger invalidation. Validation-only endpoints never invalidate.**

| Mutation category | Success boundary | Backend atomicity / rollback | Frontend on failure today | Refetch after failure today? |
|---|---|---|---|---|
| Simple CRUD (rooms/faculty/programs/enrollments/subjects/config/availability/change-password/import) | `200/201 {ok:true,…}` | `add/delete + commit`; no explicit rollback block (relies on request teardown) | `toast.error`, dialog stays open | ❌ No (correct) |
| Preferred room | `200 {ok, section, warning?}` | `flush+commit+refresh`, `rollback` on exception (`api_routes.py:417-424`) | `toast.error` | ❌ No (correct) |
| Preferences CRUD | `200/201 {ok, preference}` | `add+flush+commit+refresh`, `rollback` on any exception (`faculty_preferences.py`) | `toast.error` + `<FailureList>` | ❌ No (correct) |
| Specialization admin | `200/201 {ok,…}` | `add+commit+refresh`, `rollback` on exception (`specializations.py`) | `toast.error` + `<FailureList>` | ❌ No (correct) |
| Locked-block create/delete | `201/200 {ok, locked_block, scheduled_class}` | paired-row atomic: both or neither (`locked_blocks.py:517-547,564-575`) | `toast.error` + `<FailureList>` | ❌ No (correct) |
| Assignment create/delete | `201/200 {ok,…}` (create may be `category:warning`) | `add/delete + commit` | `toast.error` | ❌ No (correct) |
| Move (`POST …/move`) | `200 {ok, noop, scheduled_class}` | validate→flush→re-verify→commit, rollback on any path (`manual_edits.py:410-467`) | `toast.error` + `<FailureList>` **+ authoritative refetch** (`onStale → query.retry`, `TimetableEditorPage.jsx:495-500,936`) | ✅ Yes — justified (concurrent-move recovery), codify in contract |
| Reassign (`POST …/reassign`) | `200 {ok, noop, assignment, result}` | validate→set→flush→post-flush verify→commit+refresh, rollback (`faculty_reassignment.py:541-587`) | `toast.error` + failures/warnings | ❌ No (correct) |
| Swap (`POST …/swap`) | `200 {ok, noop, assignments[2], result}` | validate both→swap→flush once→verify→commit+refresh both, rollback = never half-swapped (`faculty_swaps.py:428-483`) | `toast.error` + side-grouped failures | ❌ No (correct) |
| Generation (`POST /api/schedule/run`) | `200 {ok, status, placements, run_id, locked_preserved, specializations_scheduled}` | success: single-commit replace (`api_routes.py:1376-1447`); failure: zero writes, previous schedule preserved (`:1349-1374`) | `toast.error` + alert **+ home refetch** (`TimetablePage.jsx:65-70`) | ✅ Yes — wasted-but-harmless (recommend: keep or drop; either is safe since backend wrote nothing) |
| Validation-only: `validate-move` (`1649`), `validate-reassign` (`1106`), `validate-swap` (`1172`) | `200 {ok, noop, …}` dry-run (may be `noop:true`) | **Zero mutation by construction** (`validate_move_candidate` "No database mutation" `manual_edits.py:268`; same for reassign `:409`, swap `:237`; only `SELECT`s) | inline phase (`valid/noop/invalid`), no close, no parent callback | ❌ No — and **must never** invalidate (contract §14) |

`noop:true` (already-there) is a success with zero writes — safe to treat as "invalidate optional": refetching is harmless but unnecessary; recommend emitting anyway for uniformity (idempotent GETs) or skipping — either is correct; document the choice in 6P.2.

---

## 11. Request Fan-Out / Performance Risks

Pages already making parallel reads (normal, healthy):

| Page | Parallel reads today |
|---|---|
| Editor | 1 `useApi` × `Promise.all` of 2 (`TimetableEditorPage.jsx:65-75`) |
| Fixed-block page | 1 `useApi` × `Promise.all` of 4 (`LockedBlocksPage.jsx:49-58`) |
| Sections page | 2 parallel `useApi`s (sections + rooms, `EnrollmentsPage.jsx:408-409`) |
| Spec list / detail | 2 parallel `useApi`s (`SpecializationsPage.jsx:464-466,686-688`) |
| Everything else | 1 `useApi` each |

Centralized invalidation risks, assessed against evidence:

1. **Request storms:** low risk. Fan-out per event is bounded: the largest realistic emit (generation → `schedule+overview+dashboard+assignments+lockedBlocks+specializations`) refetches only *mounted* consumers — in this router exactly one page is mounted at a time (plus none in background), so worst case ≈ the already-existing composite reads (2–4 GETs). No page mounts more than 2 `useApi`s. No change needed.
2. **Duplicate fetches:** possible where two mounted queries read the same endpoint (spec list: `getSpecializations` + sections; locked-block page composites). Mitigation is already the local `refetchAll()` pattern — the central mechanism should reuse it (one emit → one `refetchAll`, not two emits). Codify: emit *domains*, let pages coalesce to a single retry per `useApi` instance.
3. **Repeated refetches / render loops:** avoidable by design — invalidation flows one way (mutation success → emit → `retry()` → GET). There is no mutation-on-fetch anywhere, so no mutation→refetch→mutation loop is constructible. Guard: subscribers must be `useEffect`-driven on an event counter, never emitting during render.
4. **Mutation→refetch→mutation loops:** none found; no `retry()` callback triggers a mutation in any page.
5. **Unnecessary schedule reloads:** the real cost center — `GET /api/schedule/classes` + `GET /api/timetable/:view/:id` are the heaviest reads. Rule: only `schedule`-domain emits refetch them (move, locked-block change, generation, reassign/swap-label). Preference/config-only emits (`preferences`, `sections`, `rooms`, `config`) must NOT touch schedule reads. The domain matrix in §8 encodes exactly this.
6. **Coalescing:** needed only in one place — rapid successive emits (e.g. swap immediately followed by move) should collapse to one retry per mounted query (microtask/debounce or generation-counter dedup). Recommend the smallest form: subscriber ignores duplicate emits within the same tick; no batching library.

No overengineering: no request queue, no dedup cache, no polling, no prefetch.

---

## 12. Architecture Options Considered

| # | Option | Justified by architecture? | Complexity | Regression risk | Cross-page freshness | New dependency? | Necessary now? |
|---|---|---|---|---|---|---|---|
| 1 | Keep local refetch, fill missing cases | Partially — fixes nothing cross-page without a listener; would require threading callbacks through unrelated pages (prop-drilling across routes = infeasible) | Low | Low | ❌ No (same-page only) | No | Insufficient alone |
| 2 | **Lightweight central invalidation/event mechanism (recommended)** | **Yes — matches "independent fetches + manual retry" exactly: keep `useApi`/`useMutation` untouched, add emit/subscribe** | **Low (~1 small module + ~1 hook addition)** | **Low (additive; existing `retry` paths keep working)** | **✅ Yes (mounted consumers refetch once)** | **No** | **Yes** |
| 3 | Shared React context holding responses | No — would duplicate server state into context, requires cache semantics the app deliberately avoids ("backend stays authoritative" `use-mutation.js:4-6`) | Medium | Medium (stale-context bugs worse than stale-fetch) | Partial (only if context actually caches) | No | No |
| 4 | Custom query cache | No — building a cache to solve a non-cache problem; evidence shows no read is expensive enough to need memoization | Medium-high | Medium-high | Yes but overkill | No | No |
| 5 | TanStack Query / React Query | No — full cache+GC+devtools for ~20 GETs with no polling/pagination/optimistic needs; migration touches every page | High | High (rewrite of all fetch/mutation call sites) | Yes | Yes | No |
| 6 | Zustand/Redux/global store | No — no client state needs globalizing; server state stays server-owned | Medium-high | Medium | Partial (store ≠ freshness without invalidation anyway) | Yes | No |
| 7 | WebSockets / SSE | No — backend has no push infra, mutations are synchronous request/response, no multi-user realtime requirement in evidence | High (server + client + deploy) | High | Yes but unjustified | Yes (server deps) | No |

---

## 13. Recommended Phase 6P.2 Architecture

**Option 2: tiny domain-event invalidation bus + `useApi` subscription, `retry()` retained as the execution primitive.**

- New module (suggested `frontend/src/lib/invalidation.js`, ~50–80 lines): `emit(domains[])`, `subscribe(domains[], handler)` returning unsubscribe, backed by `EventTarget` or a minimal subscriber set. No storage, no caching, no async queue beyond same-tick coalescing.
- `useApi` gains an opt-in subscription (e.g. second arg `domains` or a wrapper `useInvalidatedApi(fetcher, domains)`): on emit intersecting its domains → call its existing `retry()`. Unmounted pages auto-unsubscribe via effect cleanup; only mounted consumers refetch (bounds fan-out, §11).
- `useMutation` stays unaware; call-site success handlers `emit()` the domains from the §8 matrix after `result.ok` (and only then). Failure/validation paths emit nothing.
- `noop:true` successes: emit anyway (uniformity, idempotent GETs) — document once in 6P.2.
- Generation success: emit `schedule+overview+dashboard+assignments+lockedBlocks+specializations`; generation failure: emit nothing (drop today's wasted home refetch, or keep — either safe; recommend dropping for contract purity).
- Same-tab scope only. Cross-tab, polling, focus-refetch, versioning explicitly out of scope.

Why smallest-safe: additive (no fetch/mutation call-site rewrites), no dependency, no backend change (§12… see § "Backend/API changes" below — conclusion: none), directly fixes every confirmed risk in §6 while leaving already-handled paths (§7) behaviorally identical.

---

## 14. Proposed Invalidation Contract

### Successful authoritative mutation

```text
mutation succeeds ({ ok:true })
    ↓
emit affected resource domains (§8 matrix; generation emits schedule+overview+dashboard+assignments+lockedBlocks+specializations)
    ↓
mounted consumers subscribed to those domains call retry() once (coalesced per tick)
```

### Failed mutation

```text
mutation fails ({ ok:false } / ApiError 4xx/5xx / network error)
    ↓
show structured error (toast + FailureList/fieldErrors; editor-apply may additionally retry own query for concurrent-move recovery — the sole codified exception)
    ↓
NO invalidation (no emit)
```

### Validation-only

```text
validate-move / validate-reassign / validate-swap succeeds or fails
    ↓
advance dialog phase only (valid/noop/invalid); never close parent, never refetch
    ↓
NO invalidation (no emit) — endpoints perform zero writes by construction (§10)
```

### Schedule generation

```text
POST /api/schedule/run succeeds ({ ok:true })
    ↓
emit schedule-dependent domains (schedule, overview, dashboard + assignments/lockedBlocks/specializations display context)
    ↓
mounted consumers refetch once
(generation failure → structured error, previous schedule preserved, NO invalidation)
```

Additional rules: `noop:true` emits like success (uniformity); preference/config-only mutations emit their config domain only (never `schedule`); emits carry domain names only (no payloads, no versioning).

---

## 15. Test Strategy for Future Phases

Design only — no tests implemented in this phase. All tests are frontend-behavioral (mock `fetch` or MSW-style service mocks) plus backend atomicity tests where noted. Every successful-mutation test asserts: (a) correct domains emitted exactly once, (b) subscribed consumers refetch once, (c) unsubscribed domains do not refetch. Every failure/validation test asserts: (a) structured error shown, (b) **zero** emits, (c) **zero** refetches (except the single codified editor-apply recovery path).

### Successful mutations (emit + coalesced refetch)

1. Move (`POST …/move` ok, incl. `noop:true`) → emits `schedule`; editor refetches; timetable-view subscriber refetches; `preferences`/`sections` subscribers do not.
2. Reassignment (ok, incl. warning-carrying ok) → emits `assignments+schedule+faculty+overview`; assignments + subscribed timetable/overview refetch once each.
3. Faculty swap (ok, both rows) → same as reassign; assert both assignment rows updated in one render pass.
4. Preference create/update/delete (ok) → emits `preferences` only; preferences page refetches; schedule subscribers do NOT refetch (future-generation-only proof).
5. Preferred-room set/clear (ok, incl. `warning` variant) → emits `sections` only; sections page refetches; schedule subscribers do NOT refetch.
6. Specialization membership upsert/delete (ok) → emits `specializations+sections`; list+detail refetch; schedule subscribers do NOT refetch (output changes only at next generation).
7. Locked-block create/delete (ok) → emits `lockedBlocks+schedule+assignments`; fixed-block page + subscribed schedule views refetch.
8. Schedule generation (ok) → emits `schedule+overview+dashboard+assignments+lockedBlocks+specializations`; all mounted subscribers refetch once; assert single retry per query under back-to-back emits (coalescing).

### Failed mutations (no invalidation)

Same 7 categories with backend `422/404` (and one network-error case): assert error UI (toast + `FailureList`/fieldErrors where applicable), no emit, no refetch — except editor-apply failure which refetches its own query once (recovery path).

### Validation-only (never invalidates)

`validate-move`, `validate-reassign`, `validate-swap` — each in success, `noop`, and failure variants: assert dialog phase transitions only, zero emits, zero refetches, parent data untouched.

### Cross-surface propagation

Mount two consumers (e.g. assignments page store + timetable-view store, or editor + fixed-block page) in one test harness; perform one mutation; assert each affected consumer refetches exactly once and unaffected consumers refetch zero times. Include the rapid-double-mutation coalescing case (swap then move in the same tick → one retry per consumer).

Backend (already covered by existing suites `test_manual_edits_6g/6n`, `test_faculty_reassignment_6h`, `test_faculty_swap_6h`, `test_locked_blocks_6e`, `test_specializations_6f`, `test_preferred_room_*`, `test_faculty_preferences_*`): no new backend tests required beyond asserting `run_id` presence and failure-preserves-schedule where already asserted.

---

## 16. Files Likely to Change in 6P.2+

- **New (1):** `frontend/src/lib/invalidation.js` (or equivalent) — domain bus (`emit`/`subscribe` + same-tick coalescing). Only new file in the phase.
- **Modified (minimal, additive):** `frontend/src/hooks/use-api.js` — opt-in domain subscription wired to existing `retry()` (or a thin `useInvalidatedApi` wrapper to leave `useApi` byte-identical; 6P.2 to decide).
- **Modified (call sites — emit on success only):** `pages/Timetable/TimetableEditorPage.jsx` (move), `pages/Timetable/TimetablePage.jsx` (generation), `pages/Assignments/AssignmentsPage.jsx` (create/delete/reassign/swap), `pages/LockedBlocks/LockedBlocksPage.jsx` (create/delete), `pages/Specializations/SpecializationsPage.jsx` (all spec/membership writes), `pages/Enrollments/EnrollmentsPage.jsx` (preferred-room; sections domain only), `pages/Faculty/FacultyPage.jsx` (preferences + availability + faculty CRUD), plus trivially `Rooms/Programs/Subjects/Config/Dashboard/Overview` subscriptions for their own domains (subscribe-only, no emit change beyond existing retry).
- **Explicitly unchanged:** `frontend/src/services/api/client.js`, `frontend/src/hooks/use-mutation.js` (stays unaware), `frontend/src/app/providers.jsx` / `router.jsx` (no new provider needed if bus is module-level), all `backend/*.py` (no backend change — § "Backend/API changes" conclusion below), all `backend/instance/*.db` (never written by frontend work).
- **Tests (new, 6P.3/6P.4):** `frontend/src/lib/__tests__/invalidation.test.*`, per-page propagation tests per §15.

---

## 17. Explicit Non-Goals

1. No application source changes in this phase (none made — verified §19).
2. No database writes, migrations, seeding, or scheduler runs against real/reference DBs (none performed).
3. No TanStack Query / store / context-cache / custom-query-cache adoption.
4. No WebSocket/SSE/polling/focus-refetch.
5. No backend endpoint (no version/generation-poll endpoint — genuinely unneeded: success-response-driven emit suffices, §12 option analysis + §9).
6. No optimistic updates (codebase explicitly forbids: `TimetableEditorPage.jsx:60-61`).
7. No cross-tab synchronization.
8. No refactor/cleanup of existing `retry`/`onCreated` patterns (they become the execution layer, not legacy).
9. No 6P.2 implementation (this report only), no commits, no pushes.

### Backend/API changes — conclusion: **no backend changes required for Phase 6P.**

All freshness signals the frontend needs are already in success responses (`{ok, noop, …}`, generation `{ok, status, placements, run_id, …}`). The existing per-row `run_id` (`api_routes.py:1380,1421,1450`) is sufficient provenance without a version endpoint; the frontend consumes nothing version-like today and needs nothing new under event-driven invalidation.

---

## 18. Open Questions / Runtime Verification Needed

1. **Router remount semantics:** confirm in the running SPA that navigating between the schedule surfaces always remounts (fresh GET) vs any reuse — determines the exact user-visible staleness window wording for 6P.2 docs. Static evidence says remount (distinct route elements, `router.jsx:36-59`); runtime check with React DevTools recommended.
2. **Overview schedule-derivation exactness:** `GET /api/overview` (`api_routes.py:500`) vs client-side timetable joins in `OverviewPage.jsx:127` — one runtime pass (generate → inspect overview without remount) settles whether `overview` domain must include timetable-cell payloads or counts/loads only.
3. **`noop:true` emit choice:** harmless either way (idempotent GETs); 6P.2 to document emit-vs-skip once and test accordingly.
4. **Generation-failure refetch:** keep today's wasted home retry or drop for contract purity — recommend drop, negligible UX difference either way.
5. **Cross-tab scope:** explicitly out for 6P.2; if multi-tab freshness later required, prefer `storage`-event trigger on the same bus over any server push.
6. **SQLAlchemy teardown:** Flask-SQLAlchemy default teardown suffices per evidence; no action unless a stale-read reproduction implicates sessions (none found).

---

## 19. Final Recommendation

**Adopt the lightweight central domain-invalidation bus (option 2) in Phase 6P.2 — and nothing larger.**

- It is the only option both justified by the evidence (independent fetches + manual retry + zero caches) and sufficient for every confirmed risk (§6).
- It is additive and low-risk: `useApi.retry()` stays the single refetch primitive; `useMutation` stays unaware; no dependency; no backend change; no store/cache to keep coherent.
- Contract (§14) and domains (§8) are fully specified above from code-confirmed relationships; test strategy (§15) covers success/failure/validation/cross-surface cases for 6P.2–6P.4.
- Everything else evaluated (TanStack, stores, context cache, sockets, backend versioning) is unjustified complexity for the proven problem size.

**Phase 6P.1 status: COMPLETE. Stop here — do not begin Phase 6P.2 automatically.**
