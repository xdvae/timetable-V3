# UniSchedule — Phase 6U Final Audit (Frontend Integration Testing)

> Branch: `frontend` · No commit, no push.
> Baseline (pre-6U, verified on the working tree before any change):
> backend `586 passed + 10 subtests`, frontend `93 passed across 7 files`,
> ESLint clean, production build succeeds, reference DB hashes
> `8D7AF21E…42071D` / `171D57AC…D85641`.

## 1. Status

```text
COMPLETE WITH DOCUMENTED LIMITATIONS
```

Limitations (§13): no live browser click-through (no browser-capable
runner exists in this repo — documented, not substituted); Python has no
lint/type tooling beyond `py_compile` (pre-existing).

## 2. Scope

What was tested (working tree as source of truth, not summaries):

- Frontend API clients (`frontend/src/services/api/*.js`) against the
  real Flask contracts: HTTP method, URL, JSON body, success keys,
  failure envelopes — network boundary stubbed, everything else real
  (client, normalizer, hooks, invalidation, components).
- Authentication/session behavior (`auth.js`, `auth.jsx` contract).
- Loading/success/error/empty states on representative pages.
- Unified 6Q error normalization end-to-end (all 16 scenarios in §6).
- 6P invalidation/propagation for all 14 domains and the full
  mutation→domain matrix.
- Cross-feature workflows A–H (§8) with real `useMutation` +
  `emitOnSuccess` + `useApi` + bus.
- Mutation failure/no-op behavior, read-only safety (frontend GET-only
  + backend byte-identical snapshots + scheduler never invoked).
- Backend contract drift for every critical mutation route.
- Regression: full backend + frontend suites, ESLint, production build.

What was NOT done: no features, no redesigns, no behavior changes to
make tests pass — except defect 6U-1 (§10), the smallest
compatibility-preserving fix, which is additive JSON for a path that
previously returned HTML.

## 3. Baseline (exact, pre-6U)

| Check | Result |
|---|---|
| Backend (`venv\Scripts\python.exe -m pytest backend\tests\ -q`) | `586 passed, 10 subtests passed` (~326 s); warnings are pre-existing `LegacyAPIWarning`/`Query.get` notices only |
| Frontend (`npm test` / `npx vitest run`) | `7 files, 93 passed` (~8.75 s) |
| Lint (`npm run lint`) | 0 errors, 0 warnings |
| Build (`npm run build`) | success, `2094 modules transformed`, `✓ built in 11.86s`; only the pre-existing >500 kB chunk-size advisory |
| `backend/instance/timetable.db` SHA256 | `8D7AF21E9140C4730EBCFEA2C0014C842FF42565423737E586231A31ED42071D` |
| `backend/instance/timetable_v2.db` SHA256 | `171D57AC8471ACAFEE32FDBC3589EE6AA4302B83A5DB7C34026B2C2950D85641` |
| Working tree | clean (`git status` empty before changes) |

## 4. Integration matrix

| Area | Frontend | Backend contract | Integration tested | Result |
|---|---|---|---|---|
| Auth | `auth.js` login/me/logout, `ApiError.isAuth`, `QueryError` auth hint | login 200 shape, 401 `INVALID_CREDENTIALS`, 401 `AUTH_REQUIRED` JSON (never HTML) | login success/failure, session, logout, unauthorized render, expiry hint | PASS |
| Timetable | `timetable.js` home/view/free reads | GET keys, 404 JSON for unknown view/id | GET-only, no scheduler touch, shapes | PASS |
| Editor move | `schedule.js` validate/move + `MoveDialog` phase gate (inspected) | validate dry-run keys + zero writes; move relocates one class; noop; locked rejection | validate→apply→emit; failures silent; noop silent; footprint preserved server-side | PASS |
| Faculty reassignment | `assignments.js` validate/reassign | dry-run vs authoritative, noop, `LOCKED_BLOCK` rejection | 4-domain emission; failure silent; ownership change | PASS |
| Faculty swap | `assignments.js` validate/swap | atomic exchange; `INVALID_SWAP`; spec-guard code preserved | same fan-out as reassign; failed swap atomic + silent | PASS |
| Specialization | `specializations.js` CRUD + membership | create 201, detail, membership upsert/delete, delete | CRUD round-trip; membership emits `specializations+sections`, schedule silent | PASS |
| Locked blocks | `lockedBlocks.js` list/create/delete | create 201 with paired class; delete removes both; 404 on missing; conflict 422 | emits `lockedBlocks+schedule+assignments`; failure silent | PASS |
| Preferred rooms | `enrollments.js` set/clear | set/clear, `UNKNOWN_SECTION`/`UNKNOWN_ROOM` 404s, lab-room warning accepted, schedule untouched | emits `sections` only | PASS |
| Faculty preferences | `faculty.js` list/create/update/delete | 201/create, update, delete, `PREF_HARD_UNSUPPORTED`, `PREF_INVALID_KIND`, 404 unknown | emits `preferences` only; rejections silent | PASS |
| Generation | `runScheduler` + `GeneratePanel` | OPTIMAL/FEASIBLE 200 shape; INFEASIBLE 422; UNKNOWN 422 `SCHEDULING_FAILED`/timeout; MODEL_INVALID 500 sanitized; failures preserve schedule | success fan-out; failure silent + data preserved; UNKNOWN never infeasible | PASS |
| Errors | `failures.js` normalizer + `MutationError`/`MutationFailure`/`FailureList`/`QueryError`/`FieldError` | unified `{ok:false,error,code,details?,field_errors?,failures?}` on all probed paths; 405 JSON (after 6U-1 fix) | all 16 scenarios (§6) | PASS |
| Propagation | `invalidation.js` bus + `propagation.js` matrix + `useApi` subscriptions | n/a (frontend-only architecture, backend unchanged) | all 14 domains; matrix rows; race/duplication tests | PASS |

Contract drift check (§13): every critical mutation was asserted for
method + URL + body + response handling on the frontend side, and for
route + method + response keys on the backend side. No drift found
(methods/URLs match `api_routes.py`; see also defect 6U-1 for the one
envelope gap found and fixed).

## 5. Cross-feature matrix

| Workflow | Path exercised | Result |
|---|---|---|
| A — Manual move | validate (dry-run, no emit) → apply (emit `schedule`) → editor refetch; locked move rejected; footprint intact server-side; noop silent; failed apply silent (local stale-recovery retained) | PASS |
| B — Reassignment | validate (no emit) → reassign → `assignments+schedule+faculty+overview`; invalid/locked rejected, silent | PASS |
| C — Swap | validate (no emit) → swap → same 4 domains; failed swap atomic (both unchanged) + silent | PASS |
| D — Generation | success → `GENERATION_DOMAINS` fan-out; failure → silent, previous schedule object identity preserved (no optimistic replace); OPTIMAL/FEASIBLE success; INFEASIBLE proven; UNKNOWN timeout (never "infeasible"); MODEL_INVALID internal | PASS |
| E — Locked block | create → `lockedBlocks+schedule+assignments`; delete removes both rows consistently; failed create silent | PASS |
| F — Specialization admin | CRUD + membership round-trips; membership emits `specializations+sections`, schedule provably silent; failures silent | PASS |
| G — Preferred room | set/clear; emits `sections` only; existing schedule byte-identical | PASS |
| H — Faculty preference | create/update/delete; emits `preferences` only; hard/unsupported rejected, silent; no schedule mutation | PASS |

Duplicate-Apply note: the "apply only when valid/current" guard is the
page-local `phase !== "valid"` gate in `MoveDialog` (inspected,
unchanged); the integration suite pins the adjacent contract — one
success emits exactly once (bus dedup) and a noop emits nothing.

## 6. Error contract

All 16 required scenarios verified through the real
`request()` → `ApiError` → `normalizeFailure()` → component chain:

1. structured backend failure (code + failures preserved)
2. field errors (inline `FieldError`; generic box suppressed)
3. failures array (`FailureList` with labels + context)
4. scheduler failure (`SCHEDULING_FAILED`, category `scheduler`)
5. scheduler UNKNOWN (timeout details; message never says "infeasible")
6. scheduler INFEASIBLE (proven-infeasibility message intact)
7. scheduler MODEL_INVALID (sanitized `INTERNAL_ERROR`, no leak tokens)
8. HTTP 401 (category `auth` + session-expired hint)
9. HTTP 404 (category `not_found`, `NOT_FOUND` code)
10. HTTP 400 (safe message, `BAD_REQUEST` code)
11. HTTP 405 (JSON `METHOD_NOT_ALLOWED` after 6U-1 fix; HTML tolerated safely before)
12. non-JSON response (HTML stripped to readable text, ≤200 chars)
13. malformed JSON (safe retryable message, never a crash)
14. network failure (category `network`, status 0, distinct hint)
15. unknown JS error (generic safe message, never `[object Object]`)
16. unknown future backend code (code preserved verbatim, message kept, label falls back to the code token)

Assertions held everywhere: no `[object Object]`, no `undefined`,
no raw traceback, no SQL/constraint text, no secret-like values, stable
codes preserved, safe user-facing messages, correct categories. Every
error component renders through `normalizeFailure()` (verified by
inspection + render tests; no ad-hoc envelope parsing remains).

## 7. Propagation contract

Domains (all 14, frozen in `invalidation.js`, each with ≥1 consumer and
≥1 emitter — re-verified by grep + test):

```text
schedule, assignments, faculty, preferences, sections, enrollments,
specializations, lockedBlocks, rooms, overview, dashboard, config,
programs, subjects
```

Emitters (all via the single `emitOnSuccess` gate — success + non-noop
only; validation/failure/noop paths contain zero emits):

| Mutation | Emits |
|---|---|
| move | `schedule` |
| reassign / swap | `assignments, schedule, faculty, overview` |
| assignment create/delete | `assignments, overview` |
| preference write | `preferences` (schedule untouched) |
| preferred room | `sections` (schedule untouched) |
| specialization create/delete | `specializations` |
| membership write | `specializations, sections` (schedule untouched) |
| locked-block write | `lockedBlocks, schedule, assignments` |
| generation success | `schedule, overview, dashboard, assignments, lockedBlocks, specializations` |

Races/duplication (explicit tests): one emission → one refetch per
mounted subscriber (even across overlapping domains); same-tick double
emission collapses to one GET (documented batching, no leak/loop);
unmount → zero stale callbacks; failed mutation → zero emissions;
noop → zero central emissions. Generation failure removed nothing and
refetched nothing (previous schedule preserved).

## 8. Read-only safety

- Frontend: representative read flows assert every `fetch` call is a
  GET and no call targets `/api/schedule/run`.
- Backend: all 16 read endpoints + all 3 dry-run endpoints executed
  against temp DBs with before/after table-count + schedule-row
  snapshots — byte-identical in every case; `run_scheduler` mocked and
  asserted never called during reads/dry-runs.
- Reference DB hashes unchanged (§12). No scheduler invocation from
  any read-only path. Failed reads emit no invalidation (frontend +
  backend both pinned).

## 9. Browser verification

```text
Live browser click-through: NOT VERIFIED
Reason: no existing browser-capable test environment was available
(no Playwright/Cypress/puppeteer in package.json, no browser tests in
the repo). Per the phase rules, no heavyweight browser stack was
installed for this phase; the strongest existing infrastructure
(Vitest + jsdom component/contract tests + real Flask test-client
contracts) was used instead. Nothing below is labeled browser
verification.
```

Covered without a browser: login/session contract, timetable/editor
load contracts, move validate/apply contracts, one propagation workflow
per mutation family, one structured-error workflow per error family —
all at the network-boundary + component level.

## 10. Defects found

### 6U-1 — Wrong-method `/api/*` requests returned HTML 405 (LOW, FIXED)

- Evidence: `GET /api/schedule/run` (logged in) → `405 text/html`
  (Flask default page). The blueprint 405 handler in `api_routes.py`
  never fires for routing-level 405s, and unlike 404 there was no
  app-level `/api/*` handler. Frontend impact was contained (the
  client strips HTML to safe text), but the unified 6Q contract
  (`{ok:false,error,code}`) did not hold on this path.
- Root cause: missing app-level 405 handler in `init_api` (the 404
  precedent existed; 405 was overlooked).
- Fix (smallest compatible, additive only): app-level 405 handler in
  `init_api` returning `METHOD_NOT_ALLOWED` JSON for `/api/*` paths
  and re-raising Werkzeug's default otherwise
  (`backend/api_routes.py`, +14/−1 lines). No route, status, message,
  or success shape touched; previously-HTML responses cannot have
  API consumers.
- Regression test: `TestReadOnlyAndMethodSafety::test_wrong_method_is_405_json`
  (fails before the fix with `get_json() is None`, passes after).
- Also fixed adjacent test-only defect (not a product bug): the new
  login-failure test posted wrong credentials on the already-logged-in
  harness client and got 200 "Already signed in." — now uses a fresh
  anonymous client.

No other defects found. No CRITICAL/HIGH/MEDIUM issues. Stale test
assumptions were fixed in-test (same-tick emission batching; harness
remount semantics); product code was not adjusted for them.

## 11. Regression results (exact, final)

| Check | Result |
|---|---|
| Backend (`venv\Scripts\python.exe -m pytest backend\tests\ -q`) | `626 passed, 10 subtests passed` (586 baseline + 40 new 6U; ~322 s); warnings are the pre-existing `LegacyAPIWarning` notices only |
| Frontend (`npm test`) | `9 files, 152 passed` (93 baseline + 59 new 6U; ~8–17 s) |
| Lint (`npm run lint`) | 0 errors, 0 warnings (3 test-harness findings fixed during the phase: unused prop + 2 render-purity reassignments) |
| Build (`npm run build`) | success, `2094 modules transformed`, `✓ built in 14.46s`; only the pre-existing >500 kB chunk-size advisory |
| Python compile on touched backend file | clean (`py_compile`; no other Python lint tooling installed — pre-existing limitation) |

## 12. Database integrity

- All backend 6U tests use throwaway SQLite files under `TemporaryDirectory`
  (auto-cleaned); no test points at `backend/instance/*`.
- Reference hashes, before → after (baseline run, new-test runs, full
  regression run):
  - `backend/instance/timetable.db`: `8D7AF21E9140C4730EBCFEA2C0014C842FF42565423737E586231A31ED42071D` — unchanged.
  - `backend/instance/timetable_v2.db`: `171D57AC8471ACAFEE32FDBC3589EE6AA4302B83A5DB7C34026B2C2950D85641` — unchanged.

## 13. Limitations

1. Live browser click-through NOT VERIFIED (§9) — no browser-capable
   runner exists; jsdom contract/component coverage is the strongest
   available substitute, and is not labeled otherwise.
2. No Python lint/type tooling installed — `py_compile` only
   (pre-existing, reported not pretended).
3. Duplicate-Apply click guard verified by inspection of the
   page-local phase gate, not by a rendered double-click test
   (the emission contract around it is tested).
4. Solver FEASIBLE and large-model timeout paths are covered by
   contract tests with a mocked scheduler (as in 6T), not by live
   OR-Tools soak runs.
5. `RequireAuth` redirect behavior verified by inspection of
   `auth.jsx` (401→`ApiError.isAuth`→`out` status is tested; router
   navigation itself has no test renderer in this repo).

## 14. Final verdict

```text
COMPLETE WITH DOCUMENTED LIMITATIONS
```

All §5–§13 objectives verified: frontend clients match backend
contracts with no drift; the unified error contract holds end-to-end
across all 16 scenarios; 6P propagation holds for all 14 domains with
race/duplication safety; workflows A–H behave per contract; read-only
paths are scheduler-safe and DB-identical; the one LOW defect found
(HTML 405) was fixed minimally with a regression test; full regression
(626 backend + 152 frontend, lint, build) is green; reference databases
are byte-identical. Changes are tightly scoped to Phase 6U (2 new
frontend test files, 1 new backend test file, 1 fourteen-line backend
fix, this audit). **Stop here — do not begin Phase 6V automatically.
No commit, no push.**
