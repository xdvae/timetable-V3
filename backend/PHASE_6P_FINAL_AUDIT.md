# Phase 6P — Final Live Propagation Audit

> Branch: `frontend` · Baseline: `backend/PHASE_6P1_PROPAGATION_AUDIT.md` (commit `a370992`, audit-only, no source modified).
> This report audits the actual Phase 6P implementation (6P.2–6P.5): central invalidation mechanism, mutation integration,
> propagation tests, regression/performance verification. No commit, no push.

---

## 1. Executive Summary

1. **Implemented exactly the 6P.1 recommendation (option 2): a lightweight domain invalidation/event mechanism integrated with the
   existing `useApi`/`retry()` model.** No query-cache framework, no store, no context cache, no sockets, no backend change.
2. **New code (3 modules):** `frontend/src/lib/invalidation.js` (domain bus: `emitInvalidation`/`subscribeInvalidation`),
   `frontend/src/lib/propagation.js` (single-source mutation→domain matrix + `emitOnSuccess` gate), and a minimal `useApi`
   subscription (`useApi(fetcher, ["domain"])` or `{ invalidateOn: [...] }`) that reuses the existing `retry()` path.
3. **All 22 `useApi` consumers subscribed; all 22 authoritative success paths emit through `emitOnSuccess`.** Validation-only
   endpoints and failed mutations emit nothing — verified by test and by code inspection.
4. **Contract enforced in one function:** `emitOnSuccess(result, domains)` emits iff `result.ok === true` **and** `data.noop !== true`.
   True no-ops, failures, and validation flows are silent by construction, not by convention at 20 call sites.
5. **46/46 frontend propagation tests pass; 515 backend tests + 10 subtests pass; `eslint` clean; production build succeeds.**
   Reference databases byte-identical before/after.
6. **No duplicate requests:** local `retry()` + central emit in the same tick batch into one GET (proven by test); one emission
   notifies each subscriber once even across overlapping domains (proven by test); no GET-triggered emits exist, so no loops.
7. **One deliberate behavior fix:** generation *failure* no longer refetches timetable home (backend preserves the previous schedule,
   so the old failure-branch retry was a wasted request). Everything else preserves existing local behavior.

---

## 2. Phase 6P.1 Baseline

The 6P.1 audit established, and this phase re-verified before changing anything (`use-api.js`/`use-mutation.js` byte-identical to
the audited text; `package.json` had no query/store libs; backend routes/atomicity unchanged):

- No API response cache; `useApi` = component-local GET-on-mount + manual `retry()`; `useMutation` unaware of reads.
- No React Query/TanStack/Zustand/Redux/SWR/Jotai; only contexts are session-auth and ephemeral toasts; no storage/event-bus usage.
- Backend: no cache of any kind (explicit 6P.1 finding, still true — `requirements.txt` unchanged); every GET a fresh SELECT;
  authoritative POSTs commit synchronously or roll back atomically; `validate-move/reassign/swap` provably zero-write;
  `POST /api/schedule/run` failure preserves the previous schedule.
- Propagation model was "independent fetches + same-page `retry()`", leaving the confirmed cross-page stale risks of 6P.1 §6.

One baseline extension found during implementation: **CSV import** (`POST /api/import/rooms`, `POST /api/import/workload`) commits
`Room` rows and `Program`/`Enrollment`/`Section`/`Subject`/`Faculty`/`TeachingAssignment` rows (`backend/csv_import.py:18-185`) but the
6P.1 matrix did not assign it domains. It is integrated here (`IMPORT_WORKLOAD_DOMAINS`, rooms-card reuses `ROOMS_DOMAINS`).

---

## 3. Implemented Architecture

```text
successful authoritative mutation ({ ok:true }, non-noop)
        ↓  emitOnSuccess(result, *_DOMAINS)      [propagation.js — single gate]
emit affected domains
        ↓  subscribeInvalidation                 [invalidation.js — sync bus]
mounted useApi consumers subscribed to those domains
        ↓  existing retry()                      [use-api.js — unchanged fetch path]
fresh GET → state update
```

**`frontend/src/lib/invalidation.js`** (~140 lines): module-level `Map<domain, Set<callback>>`; `subscribeInvalidation(domains, cb)`
returns an idempotent unsubscribe (effect cleanup on unmount); `emitInvalidation(domains)` synchronously invokes each matching
subscriber **exactly once** (Set-deduped, receives the frozen emitted list); empty/unknown/non-function inputs are safe no-ops;
no page/endpoint/network/backend knowledge; `resetInvalidationForTests()` is the only test-only export.

**`frontend/src/lib/propagation.js`** (~120 lines): frozen per-mutation domain constants plus `emitOnSuccess(result, domains)`,
which returns `true`+emits only when `result?.ok === true` and `result.data?.noop !== true`. All pages import these constants —
no string-literal domains at call sites.

**`frontend/src/hooks/use-api.js`** (+~30 lines): optional second parameter — array shorthand or `{ invalidateOn }`. A sorted,
deduplicated string key drives one subscription effect (`[domainsKey, retry]`, `retry` stable so no resubscription churn);
inline literals do not resubscribe per render; cleanup unsubscribes on unmount; fetch/error/loading logic untouched.

Deliberately **not** built: query cache, global store, context-held responses, polling/focus-refetch, WebSockets/SSE, backend
version endpoint, optimistic updates (still forbidden per editor design).

---

## 4. Invalidation Domains

Definitive list (`INVALIDATION_DOMAINS`, frozen, in `invalidation.js`):

```text
schedule        GET /api/schedule/classes, /api/timetable, /api/timetable/:view/:id, /api/timetable/free
assignments     GET /api/assignments
faculty         GET /api/faculty, /api/faculty/:fid/availability
preferences     GET /api/faculty/:fid/preferences
sections        GET /api/enrollments/:eid/sections
enrollments     GET /api/enrollments
specializations GET /api/specializations[/:sid]
lockedBlocks    GET /api/locked-blocks
rooms           GET /api/rooms
overview        GET /api/overview
dashboard       GET /api/dashboard
config          GET /api/config
programs        GET /api/programs
subjects        GET /api/subjects
```

Every domain has at least one subscribed consumer and at least one emitter; no unused/reserved domains exist. (`import` and
auth endpoints have no GET consumer and correctly own no domain.)

---

## 5. Mutation → Invalidation Matrix

Final matrix = `propagation.js` constants (asserted value-for-value by `__tests__/propagation.test.js`). All gates are
`emitOnSuccess` (success + non-noop); validation and failure paths contain no emit call (verified §8).

| Mutation (authoritative POST) | Emits | Reason |
|---|---|---|
| `…/schedule/classes/<id>/move` | `MOVE_DOMAINS` = `schedule` | placement changed |
| `…/assignments/<aid>/reassign` | `REASSIGN_DOMAINS` = `assignments, schedule, faculty, overview` | ownership + class labels + loads |
| `…/assignments/swap` | `SWAP_DOMAINS` = `assignments, schedule, faculty, overview` | both ownerships + labels + loads |
| `POST /api/assignments` / `…/<aid>/delete` | `ASSIGNMENT_WRITE_DOMAINS` = `assignments, overview` | rows + derived loads/counts; schedule rows untouched |
| Preference create/update/delete | `PREFERENCE_DOMAINS` = `preferences` | config only; live schedule intentionally untouched |
| `POST /api/sections/<sid>/preferred-room` | `PREFERRED_ROOM_DOMAINS` = `sections` | config only; live schedule intentionally untouched |
| Specialization create/delete | `SPECIALIZATION_DOMAINS` = `specializations` | config record |
| Membership upsert/delete | `MEMBERSHIP_DOMAINS` = `specializations, sections` | membership + section context; schedule output changes at next generation |
| Locked-block create/delete | `LOCKED_BLOCK_DOMAINS` = `lockedBlocks, schedule, assignments` | record + paired `is_locked` row + assignment labels |
| `POST /api/schedule/run` (success) | `GENERATION_DOMAINS` = `schedule, overview, dashboard, assignments, lockedBlocks, specializations` | non-locked rows replaced; slots rebuilt; derived counts/labels |
| Rooms/faculty/programs/subjects/enrollments/config/availability CRUD | own domain only (`ROOMS/FACULTY/PROGRAMS/SUBJECTS/ENROLLMENTS/CONFIG_DOMAINS`) | no cross-domain consumption beyond covered joins |
| Rooms CSV import | `ROOMS_DOMAINS` | committed room rows |
| Workload CSV import | `IMPORT_WORKLOAD_DOMAINS` = `programs, enrollments, sections, subjects, faculty, assignments, overview` | everything `csv_import.py` writes |

---

## 6. Consumer → Domain Subscription Matrix

All 22 `useApi` call sites (exhaustive; verified by grep):

| Consumer | Subscription |
|---|---|
| `DashboardPage` (`GET /api/dashboard`) | `dashboard` |
| `ConfigPage` (`GET /api/config`) | `config` |
| `RoomsPage` (`GET /api/rooms`) | `rooms` |
| `FacultyPage` (`GET /api/faculty`) | `faculty` |
| `FacultyAvailabilityPage` | `faculty` |
| `FacultyPreferencesPage` | `preferences` |
| `ProgramsPage` | `programs` |
| `EnrollmentsPage` | `enrollments` |
| `SectionsPage` sections query | `sections` |
| `SectionsPage` rooms query | `rooms` |
| `SpecializationsPage` specs query | `specializations` |
| `SpecializationsPage` sections query | `sections` |
| `SpecializationDetailPage` spec query | `specializations` |
| `SpecializationDetailPage` sections query | `sections` |
| `SubjectsPage` | `subjects` |
| `AssignmentsPage` | `assignments` |
| `OverviewPage` | `overview` |
| `TimetablePage` home | `schedule` |
| `TimetableViewPage` | `schedule` |
| `TimetableEditorPage` (classes + rooms composite) | `schedule, rooms` |
| `LockedBlocksPage` (4-read composite) | `lockedBlocks, assignments, rooms, config` |
| `FreeFacultyPage` | `schedule` |

No page subscribes to every domain; composite queries subscribe to exactly the domains of the reads they compose. `ImportPage`,
`LoginPage`, `ChangePasswordPage`, `NotFoundPage` own no `useApi` and correctly subscribe to nothing.

---

## 7. Cross-Surface Propagation Results

`src/lib/__tests__/cross-surface.test.jsx` mounts one consumer per domain plus a 4-domain composite mirroring `LockedBlocksPage`,
emits each matrix row, and asserts the exact refetch set (each exactly once, all others zero). All 11 rows pass:

| Emission | Refetched (exactly once) | Proving |
|---|---|---|
| Move | `schedule` | editor/views/free-faculty converge |
| Reassign / swap | `assignments, schedule, faculty, overview` (+ composite via `assignments`) | both assignments + all label/load surfaces |
| Assignment create/delete | `assignments, overview` (+ composite) | rows + derived data; schedule rows untouched |
| Membership | `specializations, sections` | config converges; **schedule provably untouched** |
| Spec create/delete | `specializations` | — |
| Locked create/delete | `lockedBlocks, schedule, assignments` (+ composite) | record + paired row + labels |
| Preferred room | `sections` | **schedule provably untouched** |
| Faculty preference | `preferences` | **schedule provably untouched** |
| Workload import | `programs, enrollments, sections, subjects, faculty, assignments, overview` (+ composite) | all importer-written domains |
| Generation | `schedule, overview, dashboard, assignments, lockedBlocks, specializations` (+ composite); `preferences/sections/rooms/faculty/config` silent | full schedule fan-out, no config-domain noise |

---

## 8. Validation / Failure Semantics

- **Validation-only never invalidates.** `handleValidate` in `MoveDialog` (`TimetableEditorPage.jsx:462-484`),
  `ReassignFacultyDialog` (`AssignmentsPage.jsx:318-330`), `SwapFacultyDialog` (`AssignmentsPage.jsx:497-…`) advance dialog phase
  only; none contains an emit call (verified by inspection + grep). `propagation.test.js` pins the gate shape so a validation-shaped
  result could never emit through `emitOnSuccess` unless a caller passed it — and no validation path calls it.
- **Failed mutations never invalidate.** Every `else if (result.error)` / `catch` branch shows structured UI only
  (`toast.error` + `FailureList`/field errors); grep confirms zero emit calls in any failure branch. `emitOnSuccess` returns
  `false` for `{ ok:false }`, nullish, and malformed results (tested).
- **No-op successes never invalidate.** `emitOnSuccess` returns `false` for `data.noop === true` (tested for move/reassign/swap
  shapes). Local same-page `retry()` on noop is retained (harmless single GET, pre-existing behavior).
- **Codified exceptions (local recovery, not invalidation):** editor apply-failure still refetches its own query via
  `onStale → query.retry()` (concurrent-move recovery, pre-existing, documented in 6P.1 §10).

---

## 9. Schedule Generation Propagation

- Success (`{ ok:true }` from `POST /api/schedule/run`) → `emitOnSuccess(res, GENERATION_DOMAINS)` in `GeneratePanel`
  (`TimetablePage.jsx:57-76`), covering `schedule, overview, dashboard, assignments, lockedBlocks, specializations` — i.e. every
  6P.1-confirmed schedule-dependent consumer. Verified by the generation cross-surface test.
- Failure → no emit and **no refetch**: the old failure-branch `onGenerated()` (a wasted home GET, since the backend preserves the
  previous schedule per `api_routes.py:1349-1374`) was deliberately removed. This is the only pre-existing local behavior changed
  in Phase 6P, mandated by "generation failure emits nothing".
- `run_id` semantics unchanged (per-row UUID, returned but unconsumed); no version endpoint was or is needed — the success
  response itself is the invalidation signal.

---

## 10. Configuration vs Generated Schedule Semantics

Enforced by domain selection (tested: config constants exclude `schedule`) and confirmed in UI copy:

- Faculty preferences (`FacultyPage.jsx:680,751,824` → `PREFERENCE_DOMAINS`): dialogs state "future generations only";
  backend message "Future generations… current unchanged" preserved.
- Preferred room (`EnrollmentsPage.jsx:355` → `PREFERRED_ROOM_DOMAINS`): control comment "Never touches the timetable" retained.
- Specialization membership (`SpecializationsPage.jsx:251,719` → `MEMBERSHIP_DOMAINS`): persisted schedule output changes only at
  the next generation (slots rebuilt in `api_routes.py:1423-1446`).
- Cross-surface tests assert `schedule` stays silent for all three rows. `GENERATION_DOMAINS` likewise excludes
  `preferences/sections/rooms/faculty/config` (tested).

---

## 11. Duplicate Refetch / Request Fan-Out Analysis

- **Local retry + central emit, same tick → one GET.** Emits are synchronous and adjacent to the existing local `retry()`; React
  batches both state updates into one render/effect run. Proven by `use-api.test.jsx` ("local retry and central emission in the
  same tick collapse to one GET"). Hence existing `retry()` calls were intentionally retained, not removed.
- **One emission → one GET per subscriber**, even when several subscribed domains match (bus-level Set dedup + single `retry()`),
  proven by bus and hook tests. Multi-`useApi` pages (`SectionsPage`, spec list/detail) refetch each query once — identical to
  their pre-existing `refetchAll()` behavior.
- **No subscription leaks/churn:** unsubscribe on unmount (tested: emit after unmount performs zero GETs); rerenders do not
  resubscribe (stable `domainsKey`; tested across 3 rerenders); domain-set changes resubscribe exactly once (tested).
- **No render/refetch/mutation loops:** the only subscriber action is `retry()` → GET → `setData`; no emit exists in any fetch,
  render, or effect path (grep-verified; `use-api.js` contains only `subscribeInvalidation`, in comments plus the one call).
  There is no mutation-on-fetch anywhere, so mutation→refetch→mutation is unconstructible.
- **No request storms:** fan-out is bounded by mounted queries (one page mounted at a time in this router; max composite is the
  pre-existing 4-GET locked-blocks read). No polling, prefetch, or batching library added; same-tick batching is the only
  coalescing, and the evidence requires no more.

---

## 12. Test Results

- **Backend (`venv\Scripts\python.exe -m pytest backend\tests\ -q`): 515 passed, 10 subtests passed** (~314 s). Warnings are
  pre-existing `LegacyAPIWarning` (SQLAlchemy `Query.get`) and deprecation notices, none introduced by this phase (no backend file changed).
- **Frontend (`npx vitest run`): 4 files, 46/46 passed** (~4–7 s):
  - `src/lib/__tests__/invalidation.test.js` — 14 tests (subscribe/emit/unsubscribe, multi-subscriber, multi-domain single-notify,
    unrelated ignored, idempotent cleanup, double-subscribe dedup, empty/invalid inputs, domain-list freeze/contents).
  - `src/lib/__tests__/propagation.test.js` — 11 tests (matrix values asserted literally against 6P.1; success/noop/failure/
    malformed gating; config-vs-schedule exclusions; generation domain inclusion/exclusion).
  - `src/hooks/__tests__/use-api.test.jsx` (jsdom) — 11 tests (mount fetch, subscribed refetch, unrelated silence, multi-domain
    single GET, unmount safety, rerender no-dup, domain change resubscribe, manual retry, same-tick collapse, error/retry,
    object form, domain-less backward compatibility).
  - `src/lib/__tests__/cross-surface.test.jsx` (jsdom) — 11 tests (the §7 matrix incl. workload import; each row asserts the exact
    refetch set with all counts ≤ 1).
- Test infra notes: parallel jsdom workers exceeded the fork-startup budget on this machine, so `vitest.config.js` (new, test-only)
  pins a single forks worker; one jsdom test initially looped on an inline fetcher identity and was fixed with `useCallback`
  (test-only bug, caught by the 10 s hook timeout, never in app code — all app fetchers were already stable per 6P.1).

---

## 13. Lint / Build Results

- **`npm run lint` (eslint, incl. react-hooks + react-compiler rules): clean, 0 errors, 0 warnings.** Two Phase-6P findings were fixed
  during the phase: ref-assignment-during-render in `use-api.js` (replaced with stable-`retry` effect dep) and prop mutation in a test
  consumer (restructured to a callback). No warnings suppressed.
- **`npm run build` (vite production): succeeds** (`✓ built in ~12–18 s`). Only the pre-existing >500 kB chunk-size advisory remains;
  unrelated to this phase, left untouched.
- **New dependencies: two dev-only packages** (`vitest`, `jsdom`) + `"test": "vitest run"` script. Zero production dependencies added;
  no React Query/store/socket library introduced per the phase constraints.

---

## 14. Backend Changes

**None.** `git diff --stat` shows zero backend source modifications; no routes, models, validators, scheduler, session handling, error
envelopes, or API contracts touched. `git status` backend entries are report files only
(`PHASE_6P1_PROPAGATION_AUDIT.md` pre-existing + this file). No migration/seed/cache/queue/version-endpoint/worker added, as required.

---

## 15. Database Safety

- Temporary/test databases only for the backend suite (its own fixtures); no manual migration, seeding, scheduler run, or mutation
  API call against reference DBs was performed in this phase.
- Reference hashes, before → after (all runs incl. full pytest):
  - `backend/instance/timetable.db`: `8D7AF21E9140C4730EBCFEA2C0014C842FF42565423737E586231A31ED42071D` — unchanged.
  - `backend/instance/timetable_v2.db`: `171D57AC8471ACAFEE32FDBC3589EE6AA4302B83A5DB7C34026B2C2950D85641` — unchanged.

---

## 16. Remaining Stale-Data Risks

None classified above "negligible" within the phase scope (same-tab SPA):

1. **Cross-tab staleness** (two tabs open on different pages): out of scope by design; each tab remounts fresh on navigation.
   If ever required, prefer a `storage`-event trigger into the same bus — no server push.
2. **Dashboard counts after entity CRUD elsewhere**: dashboard subscribes `dashboard`, emitted only by generation. A mounted dashboard
   cannot observe another page's mutation in this single-route SPA (only one page mounted at a time); navigation remounts fresh.
   Same reasoning covers all "emit X while page Y mounted" combinations not in the matrix.
3. **Back/forward remount semantics** (6P.1 open question): static evidence (distinct route elements, `router.jsx:36-59`) indicates
   remount-with-fresh-GET; even in the worst case (router reuse without remount) the new subscription layer now refreshes mounted
   consumers on the next relevant mutation, strictly reducing the window.
4. **Overview schedule-cell derivation** (6P.1 open question): `overview` is emitted by generation/reassign/swap/assignment-writes/import,
   covering both the counts/loads and any schedule-adjacent cells; no finer distinction proved necessary.

---

## 17. Remaining Technical Debt

1. `GeneratePanel` failure-branch `onGenerated` removal (intended, §9) — one line; flagged here for reviewer visibility.
2. `noop:true` successes keep their pre-existing local `retry()` (harmless single GET) while skipping central emit — documented choice;
   unifying to skip both is a trivial follow-up if desired.
3. `api.del` in `services/api/client.js` remains exported-but-unused (pre-existing; deletes are `POST …/delete`) — untouched.
4. `frontend/dist/` build output regenerated locally; gitignored, not part of the change set.
5. Vitest single-worker pin (`vitest.config.js`) is a machine-performance accommodation; safe to relax on faster CI.

---

## 18. Files Changed

**Created (7):**

| File | Why |
|---|---|
| `frontend/src/lib/invalidation.js` | 6P.2 central domain bus (no cache, no network, no backend dep) |
| `frontend/src/lib/propagation.js` | 6P.3 single-source mutation→domain matrix + `emitOnSuccess` gate |
| `frontend/src/lib/__tests__/invalidation.test.js` | 6P.4 bus unit tests (14) |
| `frontend/src/lib/__tests__/propagation.test.js` | 6P.4 matrix + gating tests (11) |
| `frontend/src/hooks/__tests__/use-api.test.jsx` | 6P.4 subscription behavior tests (11) |
| `frontend/src/lib/__tests__/cross-surface.test.jsx` | 6P.4 cross-surface matrix tests (11) |
| `frontend/vitest.config.js` | test-only runner config (isolated from dev/prod pipeline) |
| `backend/PHASE_6P_FINAL_AUDIT.md` | this report (14) |

**Modified (17 source + manifests):**

| File | Change |
|---|---|
| `frontend/src/hooks/use-api.js` | opt-in domain subscription reusing `retry()` (+~30 lines, fetch path untouched) |
| 13 page files (`Dashboard, Config, Rooms, Faculty, Programs, Enrollments, Specializations, Subjects, Assignments, Import, Overview, Timetable×2, LockedBlocks, FreeFaculty` — `TimetablePage`+`TimetableEditorPage` counted under Timetable) | subscribe reads; `emitOnSuccess` on authoritative success only |
| `frontend/src/pages/Timetable/TimetablePage.jsx` | additionally: failure branch no longer refetches (intended fix, §9) |
| `frontend/package.json` / `frontend/package-lock.json` | `vitest`+`jsdom` devDeps, `test` script (zero prod deps) |

Full list per `git diff --stat`: 18 tracked files (incl. manifests), +929/−30; 8 untracked (7 above + pre-existing 6P.1 report).
No backend source, no migration, no schema, no test-fixture change.

---

## 19. Explicit Non-Goals

Respected without exception: no React Query/TanStack/Redux/Zustand/Jotai/SWR (none installed); no WebSockets/SSE/polling/focus-refetch;
no backend cache/queue/worker/trigger/version endpoint; no schema or migration change; no reference-DB writes; no API contract or
error-envelope change (`{ error, code, details, failures, field_errors }` semantics intact); no optimistic updates; no cross-tab sync;
no unrelated refactor (all diffs are subscribe/emit/test/config lines); no commit; no push; Phase 6Q not started.

---

## 20. Final Phase 6P Verdict

```text
COMPLETE
```

Every 6P.1-confirmed stale path now propagates through the central mechanism (proven by 46 green tests and the §7 matrix);
validation-only and failed mutations provably never invalidate; generation success fans out to all schedule-dependent consumers
while failure stays silent; configuration writes provably leave the live schedule alone; no duplicate requests or loops were found;
backend suite, lint, and build are green; reference databases are byte-identical; the change set is minimal and scoped. Phase 6P.1
remains the architecture record; this file is the implementation record. **Stop here — do not begin Phase 6Q automatically.**
