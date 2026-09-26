# Phase 6Q — Unified Error System Final Audit

> Branch: `frontend` · Baseline: `backend/PHASE_6P1_PROPAGATION_AUDIT.md` + `backend/PHASE_6P_FINAL_AUDIT.md`
> (Phase 6P complete, no backend contract change).
> This report audits the actual Phase 6Q implementation: error-architecture audit,
> unified contract, backend integration, frontend normalization, error-system tests,
> regression. No commit, no push.

---

## 1. Executive Summary

1. **Audited before changing anything.** Backend shapes (`api_routes.py:33-79`,
   service `except Exception` sites, scheduler/import/auth paths) and frontend
   handling (`failures.js`, `client.js`, `use-mutation.js`, `MutationError` /
   `FailureList` / `QueryError` / `FieldError` + all consumers) were inventoried
   with file:line evidence (§2–§3). No public code was renamed; no success shape changed.
2. **One additive contract.** New `backend/errors.py` produces the existing flat shape
   plus an `"ok": false` marker and a guaranteed stable `code`
   (`{ ok, error, code, details?, field_errors?, failures? }`). Pre-6Q clients keep
   working byte-identically on every previously-coded error; previously codeless
   errors gained codes only (messages/statuses unchanged).
3. **Backend integrated through one function.** `ApiError` handling, 404/405/400
   handlers, login/unauthorized responses, and the codeless scheduler failure all
   route through `error_response()`; a new blueprint `Exception` handler sanitizes
   unknown exceptions to `INTERNAL_ERROR` 500; seven service modules no longer
   interpolate raw `str(exc)` (SQL/constraint text) into user-facing messages.
   Atomic/rollback guarantees untouched.
4. **Frontend normalized at one boundary.** `failures.js` gained `normalizeFailure()`
   (`{ code, message, details, fieldErrors, status, category }`) covering structured,
   field, scheduler, import, non-JSON, malformed, network, and unknown-JS failures;
   `client.js` guarantees safe strings + normalized field errors + retryable errors
   for unreadable 2xx bodies; `MutationError` / `FailureList` / `QueryError` /
   `FieldError` render through the normalizer; new `MutationFailure` replaced 19
   page-specific guard/branch duplications; scheduler failures render structured
   `FailureList`; import row errors are coerced safely with counts/summary intact.
5. **59 error-system tests green; full regression green.** Backend `539 passed`
   (515 pre-existing + 24 new) + 10 subtests; frontend `81/81` (46 pre-existing +
   35 new); `eslint` 0/0; `vite build` succeeds. Reference DBs byte-identical.
6. Verdict: **COMPLETE WITH DOCUMENTED LIMITATIONS** (§18–§19).

---

## 2. 6Q.1 Baseline Error Architecture

Backend (all via `ApiError(message, status, field_errors, code, details, failures)`
+ handler omitting unset keys; default status 422):

| Shape | Example producers |
|---|---|
| S1 `{"error"}` only | plain 404s (`api_routes.py:204,322,1036`), login 401 (`:238`), bare scheduling failure (`:1374`), blueprint 404/405/400 (`:67-79`) |
| S2 `+ field_errors` | missing/invalid inputs (`:95,107,117,263,622,904,945`), change-password (`:263-270`), import missing file (`:1256,1269`) |
| S3 `+ code/details/failures` | preferred-room unknowns (`:392-410`), reassign/swap/manual/spec/preference/locked mappers, scheduler infeasibility (`:1349-1373`) |
| S4 S2+S3 combined | locked-create placement errors (`:1513-1524`), manual-edit (`:1615-1631`), preferences (`:696-713`) |
| S6 import success-with-errors | `200 {ok:true, message, counts, errors:["Row i: …"]}` (`:1258-1260,1274-1275`) — never an HTTP error |
| S7 HTML (non-API) | `abort(404)` in `app.py`, `helpers.py`, unmatched non-`/api` routes |

No `app.errorhandler(500)`, no `Exception` handler, no `traceback` import existed:
unhandled exceptions fell through to Werkzeug HTML 500s, and every persistence
rollback path interpolated raw `str(exc)` into the user message (26 sites, incl.
`uq_specialization_name_enrollment` constraint text in `specializations.py:393`).

Frontend baseline: single `fetch` (`client.js:47`) → `ApiError { message, status,
fieldErrors, payload }`; `getFailures()` read only `payload.failures`;
`FAILURE_LABELS` (41 keys) consumed only by `FailureList`; `MutationError` /
`QueryError` rendered `error.message` unguarded (`[object Object]` /
`undefined` possible); 12× duplicated `error && !error.fieldErrors` guards and 3
branching dialects across pages; `GeneratePanel` showed scheduler failures as a
bare message; `ImportPage` rendered row errors without coercion.

---

## 3. Existing Error Code Inventory

Definitive literal inventory from the repository (all preserved verbatim; none
renamed, none merged). Producers cited once each:

| Code | Producer(s) | HTTP |
|---|---|---|
| `ROOM_TYPE_MISMATCH`, `ROOM_CAPACITY`, `ROOM_EQUIPMENT`, `BREAK_SPAN`, `PERIOD_OUT_OF_RANGE`, `UNKNOWN_DAY`, `FACULTY_UNAVAILABLE`, `BLOCK_LENGTH_INVALID`, `FACULTY_CONSECUTIVE`, `COVERAGE_MISMATCH`, `MAX_TWO_THEORY`, `SPECIALIZATION_ENROLLMENT`, `SPECIALIZATION_MEMBERSHIP`, `SPECIALIZATION_CAPACITY`, `SPECIALIZATION_SYNC`, `SPECIALIZATION_OVERLAP` | `schedule_rules.py` | 422 |
| `LOCKED_BLOCK`, `UNKNOWN_ROOM`, `GROUP_CONFLICT` (remapped, never surfaces), `SECTION_HIERARCHY_CONFLICT`, `ROOM_CONFLICT`, `FACULTY_CONFLICT` | `schedule_validator.py` | 422 |
| `LOCKED_BLOCK_INVALID` (fallback), `UNKNOWN_ASSIGNMENT`, `ASSIGNMENT_MISMATCH`, `BLOCK_GEOMETRY`, `ROOM_REQUIRED`, `UNKNOWN_KIND`, `KIND_NOT_ENABLED`, `PERSISTENCE_FAILED`, `UNKNOWN_LOCKED_BLOCK` | `locked_blocks.py` | 422 (delete-miss 404 by message sniff) |
| `SPECIALIZATION_INVALID` (fallback) | `specializations.py` | 422 |
| `MANUAL_EDIT_INVALID` (fallback), `SECTION_CONFLICT`, `SECTION_HIERARCHY_CONFLICT` | `manual_edits.py` | 422; 404 when "does not exist" |
| `REASSIGNMENT_INVALID` (fallback), `UNKNOWN_ASSIGNMENT`, `UNKNOWN_FACULTY`, `SECTION_CONFLICT` | `faculty_reassignment.py` | 404 for unknown ids else 422 |
| `INVALID_SWAP` (fallback), `SPECIALIZATION_SWAP` | `faculty_swaps.py` | 404 for unknown ids else 422 |
| `PREFERENCE_INVALID` (fallback), `PREF_INVALID_KIND`, `PREF_HARD_UNSUPPORTED`, `PREF_INVALID_DAYS`, `PREF_INVALID_PERIOD`, `PREF_INVALID_WEIGHT`, `UNKNOWN_FACULTY`, `UNKNOWN_PREFERENCE` | `faculty_preferences.py` | 404 for unknowns else 422 |
| `UNKNOWN_SECTION`, `UNKNOWN_ROOM`, `SCHEDULING_INFEASIBLE` | `api_routes.py` direct | 404 / 404 / 422 |
| `INFEASIBLE` / `NO_SESSIONS` | `scheduler.py` statuses (message prefixes, not codes) | via 422 mapping |

New gap-filling codes only (messages/statuses unchanged): `INVALID_CREDENTIALS`
(login 401), `AUTH_REQUIRED` (session 401), `NOT_FOUND` (404s), `METHOD_NOT_ALLOWED`
(405), `BAD_REQUEST` (400), `SCHEDULING_FAILED` (codeless scheduler failure),
`INTERNAL_ERROR` (sanitized 500). Stable meanings verified: no code has two
meanings; `UNKNOWN_ROOM` 404-vs-422 and `UNKNOWN_ASSIGNMENT` 404-vs-422 reflect
endpoint semantics (lookup miss vs placement validation), documented not unified.

---

## 4. Implemented Error Contract

`backend/errors.py` (new, ~150 lines, zero third-party deps):

```json
{
  "ok": false,
  "error": "<safe user-facing message>",
  "code": "<STABLE_UPPER_SNAKE>",
  "details": {},
  "field_errors": {},
  "failures": [{ "code": "...", "message": "...", "details": {} }]
}
```

`details` / `field_errors` / `failures` omitted when empty (pre-6Q omission
semantics kept). Guarantees: `ok:false` on every error; `code` always present;
message always a plain string (≤2000 chars); details scrubbed of
traceback/stack/secret/password/SQLAlchemy-ish keys; field errors coerced to
`{ field: string }` (objects/arrays dropped, never `[object Object]`);
`category_for()` maps status+code → `auth/forbidden/not_found/conflict/
validation/scheduler/internal/error` without overriding status semantics.
Success shapes untouched. Nested-shape tolerant on the read path
(`error.code` object form also accepted by the frontend normalizer).

---

## 5. Backend Error Handling

`backend/api_routes.py`: `ApiError` handler routes through
`error_response()` (flat keys byte-identical for previously-coded errors);
404/405/400 blueprint handlers + app-level `/api/*` 404 + unauthorized handler
emit `NOT_FOUND` / `METHOD_NOT_ALLOWED` / `BAD_REQUEST` / `AUTH_REQUIRED`;
login failure emits `INVALID_CREDENTIALS` (message unchanged); codeless
`SCHEDULING_FAILED` carries `details.reason`; preferred-room persistence error
no longer embeds `str(exc)`. New `@api_bp.errorhandler(Exception)`:
`ApiError`/404/405/400 keep specific handlers; other `HTTPException`s keep
status with generic messages; everything else → sanitized `INTERNAL_ERROR` 500
with no payload/exception logging (no secret risk, no noise).
Services (`manual_edits`, `faculty_reassignment`, `faculty_swaps`,
`locked_blocks`, `faculty_preferences`, `specializations`): persistence-failure
messages reduced to safe base strings; codes/details/failures/rollback
semantics unchanged. The `specializations.py:392` unique-constraint sniff stays
server-side only (raised messages are safe literals). `audit_schedule.py:890`
CLI print is not user-facing, untouched.

---

## 6. Frontend Error Normalization

`frontend/src/lib/failures.js` (+218): `safeMessage()` (never
`undefined`/`null`/`[object Object]`), `labelFor()` (known label; safe
`[A-Z0-9_]` code passthrough; else "Validation failed"), `categoryFor()`
(status 0 → `network`, 401 → `auth`, 422+`SCHEDULING_*` → `scheduler`, …),
`normalizeFieldErrors()` / `getFieldErrors()` (flat + nested envelopes),
`normalizeFailure()` → `{ code, message, details, fieldErrors, failures,
importErrors, status, category }` handling structured / field / scheduler /
import-row / non-JSON / malformed / network / unknown-JS inputs (idempotent),
`hasFieldErrors()`, `getImportRowErrors()`. 15 new `FAILURE_LABELS` close every
§3 gap. `client.js` (+79): object-message extraction, HTML-body text stripping,
field-error scalar coercion, `ApiError.code` getter (flat+nested), and a
retryable `ApiError` for unreadable 2xx bodies (null-data crash class removed).
`use-mutation.js`: field errors normalized at the source.

---

## 7. Error Presentation Architecture

```text
Backend error_response / ApiError
            ↓  HTTP JSON (flat keys + ok:false + code)
client.js request() boundary (safe strings, normalized fieldErrors)
            ↓  ApiError (message/status/fieldErrors/payload/code)
normalizeFailure() (failures.js — single representation)
            ↓
MutationFailure → FailureList | MutationError | null (field-inline)
FieldError (safe text) · QueryError (normalized + status-aware hint)
GeneratePanel FailureList (scheduler) · ImportPage (rows + counts)
```

`MutationError`/`DeleteConfirmDialog`/`QueryError` render normalized messages;
`FailureList` accepts string entries (import rows) and unknown codes (code
passthrough label + verbatim message + context). Field validation shows beside
the field; mutation conflicts show concise messages; scheduler failures keep
infeasibility/conflict details + a dedicated list; query failures are retryable;
network vs validation vs auth stay visually distinguishable; internal failures
show the safe generic message.

---

## 8. Field Error Handling

Preserved end-to-end: backend `field_errors` → contract (coerced, never dropped
for having a general message) → `client.js` → `useMutation` →
`getFieldErrors()` → inline `FieldError` beside inputs (all existing consumers
intact, now object-safe) with `aria-describedby` wiring untouched. `MutationFailure`
suppresses the generic box exactly when field errors exist (the 12× dominant
pattern, now in one place); two formerly-unconditional sites (preferred-room,
membership dialogs) adopt it with no information loss (inline errors remain).

---

## 9. Scheduler Error Handling

Preserved, not collapsed: `SCHEDULING_INFEASIBLE` keeps `locked_block_ids` +
reason + per-failure entries; specialization-coded infeasibility keeps its
stable code; codeless `NO_SESSIONS` is now `SCHEDULING_FAILED` with
`details.reason`. `GeneratePanel` keeps the verbatim alert and additionally
renders `FailureList` ("Why scheduling failed") when structured failures exist.
Success still emits `GENERATION_DOMAINS`; failure still emits nothing and writes
nothing (previous schedule preserved). Frontend `categoryFor()` routes both
codes to `scheduler` presentation.

---

## 10. CSV Import Error Handling

Backend unchanged by design (success-with-row-errors is the contract):
`200 {ok:true, message, counts, errors:["Row i: …"]}` plus 422 `field_errors.file`
when no file is chosen. Frontend: `getImportRowErrors()` coerces entries;
`ImportPage` renders summary + counts + up-to-10 rows + overflow count exactly
as before, with `safeMessage` on message/rows/keys and the `file` field error.
`normalizeFailure()` also surfaces `errors[]` as `importErrors` so import
problems survive generic handling. Row-level, count, and summary information
all preserved; no parser traceback can reach the UI (backend never emitted one).

---

## 11. Authentication / Authorization Errors

`401 INVALID_CREDENTIALS` "Incorrect username or password." (login, message
unchanged) vs `401 AUTH_REQUIRED` "Authentication required." (session guard)
vs 422 validation vs 404 lookup — all distinguishable by status+code and
covered by tests. `auth.jsx` 401-vs-network routing untouched; `QueryError`
shows the expired-session hint only for `auth` category; login redirect/session
behavior unchanged (no `login_view`, no token/CORS change, no 403/roles added —
none existed).

---

## 12. Error Code / HTTP Status Semantics

Actual (documented, preserved): 400 malformed, 401 auth, 404 missing (plain or
`UNKNOWN_*`), 405 method, 422 validation/domain (incl. conflicts, infeasibility,
persistence), 500 internal (new sanitized handler), 200/201 successes (import
200-with-`errors[]` intentional). Normalized only where safe: codeless errors
gained codes; `UNKNOWN_*` 404-vs-422 duality kept (lookup vs placement
semantics); delete-miss message-sniffing (`"does not exist"`) left as-is
(pre-existing fragility, out of scope); validation-only endpoints
(`validate-move/reassign/swap`) keep 200 dry-run semantics and never mutate
(pinned by test).

---

## 13. Unknown / Internal Error Safety

Unknown structured codes: code preserved, label falls back to the code token or
"Validation failed", backend message/defensive generic shown — tested. Unknown
JS exceptions / null / malformed JSON / non-JSON HTTP: safe generic or
status-aware message, retryable where appropriate — tested. Internal exceptions:
`INTERNAL_ERROR` 500 with zero leakage (test asserts absence of
traceback/RuntimeError/SQL fragments/paths/secrets); persistence rollbacks no
longer embed `str(exc)` (test asserts absence of `UNIQUE`/constraint text);
no stack frames, module paths, env vars, or filesystem paths in any response;
no new logging (nothing to leak, nothing noisy).

---

## 14. Test Results

- **Backend (`venv\Scripts\python.exe -m pytest backend\tests\ -q`): 539 passed,
  10 subtests passed** (~287 s). 515 pre-existing + 24 new
  (`backend/tests/test_errors_6q.py`: 6 contract unit + 18 surface/safety tests
  covering structured, field errors, details, known codes, 500 sanitization,
  persistence sanitization, auth, not-found, status semantics, validation-vs-
  mutation, scheduler, manual-edit, reassign, swap, specialization, locked-block,
  preference, import-missing-file, import-row-errors). Warnings are the
  pre-existing `LegacyAPIWarning`/`Query.get` notices only.
- **Frontend (`npx vitest run`): 6 files, 81/81 passed** (~8 s). 46 pre-existing
  (6P invalidation/propagation/cross-surface) + 35 new: `errors-6q.test.js` (23:
  safe text, full code-label coverage incl. all 6Q codes, unknown-code fallback,
  categories, field errors, all 8 fallback branches, idempotency) and
  `error-components-6q.test.jsx` (12 jsdom: all four components, scheduler
  details, string entries, network/auth QueryError, no `[object Object]` /
  `undefined` / `null` primary text).

---

## 15. Lint / Build Results

- **`npm run lint` (eslint incl. react-hooks + react-compiler): clean, 0 errors,
  0 warnings**, incl. the two new test files. Two unused-import cleanups from the
  `MutationFailure` migration were caught and fixed via lint during the phase.
- **`npm run build` (vite production): succeeds** (~16 s). Only the pre-existing
  >500 kB chunk-size advisory remains; unrelated, untouched.
- **Dependencies: zero added** (no error framework, per constraints).

---

## 16. Database Safety

- Changed: `NO`. No schema change, no migration, no seed, no generation run,
  no mutation API call against reference DBs; backend suite used its own
  temp-file fixtures; `test_errors_6q.py` uses throwaway temp SQLite files.
- Reference hashes, before → after (incl. full pytest + all API tests):
  - `backend/instance/timetable.db`: `8D7AF21E9140C4730EBCFEA2C0014C842FF42565423737E586231A31ED42071D` — unchanged.
  - `backend/instance/timetable_v2.db`: `171D57AC8471ACAFEE32FDBC3589EE6AA4302B83A5DB7C34026B2C2950D85641` — unchanged.

---

## 17. Files Changed

**Created (4):**

| File | Why |
|---|---|
| `backend/errors.py` | 6Q unified contract (`error_response`, sanitizers, `category_for`, gap codes) |
| `backend/tests/test_errors_6q.py` | 24 error-system tests |
| `frontend/src/lib/__tests__/errors-6q.test.js` | 23 normalization tests |
| `frontend/src/lib/__tests__/error-components-6q.test.jsx` | 12 presentation tests |
| `backend/PHASE_6Q_FINAL_AUDIT.md` | this report |

**Modified (24, per `git diff --stat`: +492/−156):**

| File(s) | Change |
|---|---|
| `backend/api_routes.py` | contract routing, gap codes, `Exception` sanitizer, safe persistence message |
| 6 service modules (`manual_edits`, `faculty_reassignment`, `faculty_swaps`, `locked_blocks`, `faculty_preferences`, `specializations`) | raw `str(exc)` removed from user messages; codes/rollbacks intact |
| `frontend/src/lib/failures.js` | normalizer + helpers + 15 labels |
| `frontend/src/services/api/client.js` | safe messages, field coercion, unreadable-2xx error, `code` getter |
| `frontend/src/hooks/use-mutation.js` | normalized field errors |
| `frontend/src/components/feedback/mutation.jsx` | normalizer rendering, string entries, `MutationFailure` |
| `frontend/src/components/feedback/data-states.jsx` | normalizer `QueryError` |
| 11 page files | `MutationFailure` migration (guards/pairs collapsed, orphan vars/imports removed) |
| `frontend/src/pages/Import/ImportPage.jsx` | safe coercions (behavior intact) |
| `frontend/src/pages/Timetable/TimetablePage.jsx` | scheduler `FailureList` + safe messages |

---

## 18. Remaining Error Inconsistencies

1. Delete-miss 404s detected by message substring (`"does not exist"` /
   `"No membership"` in locked/spec/membership deletes) — pre-existing,
   untouched (normalizing it would change status semantics; flagged, not fixed).
2. `UNKNOWN_ROOM` / `UNKNOWN_ASSIGNMENT` carry 404 in lookup endpoints but 422
   in placement validation — intentional per-endpoint semantics (§3), kept.
3. `toast.error(result.error.message || "<op fallback>")` call sites (~30) still
   exist per page, but now consume client-guaranteed safe strings; category-aware
   fallbacks live in the shared components, not the toasts. Cosmetic only.
4. `LoginPage` keeps its custom alert (auth-specific copy); message now always
   safe via the client. Intentional, not migrated.
5. `GROUP_CONFLICT` is remapped to `SECTION_CONFLICT` before surfacing (label
   retained for completeness). Pre-existing, kept.

---

## 19. Remaining Technical Debt

1. Swap-side failure grouping (`AssignmentsPage.jsx:renderFailureGroups`) and
   `TimetableEditorPage` phase-gated failure UI intentionally stay bespoke —
   specialization UX, not duplication (documented §7-adjacent decision).
2. No server-side request logging exists; the 500 handler deliberately logs
   nothing (phase constraint). Diagnosing rare 500s requires reproducing with
   server logs attached out-of-band.
3. Non-API HTML 404s (`/export`, sample downloads, SPA fallback) unchanged —
   correct (downloads, not API).
4. Vitest single-forks-worker pin and the >500 kB chunk advisory are
   pre-existing, untouched.
5. `frontend/dist/` regenerated locally by the build verification; gitignored,
   not in the change set.

---

## 20. Explicit Non-Goals

Respected: no commit, no push, no history rewrite; no schema/migration change;
no reference-DB writes; no API success-shape redesign; no public-code renames;
no generic-message collapse of specific errors; no field-error hiding; no
stack/SQL/path/secret exposure; no third-party error framework; no new test
framework; validation-only operations still side-effect-free and
distinguishable; atomic/rollback guarantees intact; no unrelated roadmap work;
Phase 6R not started.

---

## 21. Final Phase 6Q Verdict

```text
COMPLETE WITH DOCUMENTED LIMITATIONS
```

Every meaningful backend error producer conforms to the unified contract (or is
safely normalized at the frontend boundary); every frontend-visible structured
code has label handling with a safe unknown-code fallback; field errors and
scheduler/import/conflict details survive end-to-end; unknown and internal
failures are safe and retryable where appropriate; status/code semantics are
coherent without breaking compatibility; regression (539 backend + 81 frontend,
lint, build) is green; reference databases are byte-identical; the change set
is minimal and scoped. Limitations (§18–§19) are cosmetic or intentional and
affect no error surface's safety or structure. **Stop here — do not begin
Phase 6R automatically.**
