# UniSchedule — Phase 6T Final Audit (Full Validation)

## 1. Scope

System-wide correctness, integrity, compatibility, and regression audit of
the Phase 5B–6S build. No feature development, no objective redesign, no new
UX. Priority: the known 6S issue — the scheduler wrapper folding
`UNKNOWN`/time-limit outcomes into `"INFEASIBLE"`.

## 2. Environment

* Branch `frontend` (commit `85c148a` at start; working tree clean).
* Backend: Flask 3.0.3 + SQLAlchemy + OR-Tools 9.10.4067
  (`OPTIMAL=4, FEASIBLE=2, INFEASIBLE=3, UNKNOWN=0, MODEL_INVALID=1`).
* Frontend: React 19 + Vite + vitest 5.0.2.
* No commits/pushes/resets/checkouts/rebases/stashes performed; tree preserved.

## 3. Baseline

Pre-6T: backend 579 passing; frontend 93 passing; scheduler 30-session
OPTIMAL ~2s class / 60-session ~9s class; objective unchanged (kept so —
no 6T change touches it).

## 4. Validation matrix

See `backend/PHASE_6T_VALIDATION_MATRIX.md` (21 areas, 15 cross-feature
combos, every cell evidence-cited). Headline: all areas VERIFIED except
the two documented limitations in §19.

## 5. Scheduler status audit (priority item — defect found and fixed)

Full path inspected: `run_scheduler` (`scheduler.py:1074-1116`) →
`api_schedule_run` (`api_routes.py:1338-1513`) → `GeneratePanel`
(`TimetablePage.jsx:66-165`) + `failures.js`/`propagation.js`.

* **Confirmed:** every non-OPTIMAL/FEASIBLE solver outcome returned
  `"INFEASIBLE"` (`scheduler.py:1079` pre-fix), and the API failure branch
  only recognized `INFEASIBLE`/`NO_SESSIONS` — so a timeout was both
  mislabeled and one refactor away from being persisted as a success.
* **Fix (6T-1):** solver `INFEASIBLE` → `"INFEASIBLE"` (message unchanged);
  `UNKNOWN`/other → `"UNKNOWN"` with a time-limit message that never says
  "infeasible"; `MODEL_INVALID` → `"MODEL_INVALID"`. API: `UNKNOWN` → 422
  `SCHEDULING_FAILED` + `{status:UNKNOWN, timeout:true}` (existing stable
  code — no new code invented, frontend label/category already correct);
  `MODEL_INVALID` → sanitized 500 `INTERNAL_ERROR`. Failure branch still
  writes nothing (atomicity + previous-schedule preservation intact).
  Success shape `{ok,message,status,placements,run_id,…}` byte-identical.
* **Regression tests:** `backend/tests/test_scheduler_status_6t.py`
  (7 tests, all pass).

| Outcome | Before 6T | After 6T |
|---|---|---|
| OPTIMAL | "OPTIMAL" | "OPTIMAL" (unchanged) |
| FEASIBLE | "FEASIBLE" | "FEASIBLE" (unchanged) |
| INFEASIBLE (proven) | "INFEASIBLE" | "INFEASIBLE" (unchanged) |
| UNKNOWN / TIME_LIMIT | "INFEASIBLE" ❌ | "UNKNOWN" → 422 `SCHEDULING_FAILED` ✅ |
| MODEL_INVALID | "INFEASIBLE" ❌ | "MODEL_INVALID" → 500 `INTERNAL_ERROR` ✅ |

## 6. API audit

* Every error path returns `{ok:false, error, code}` (`errors.py` single
  choke point; `ApiError` + 404/405/400/sanitized-500 handlers).
* No bare/codeless/HTML/raw-exception leaks found (probed: validation,
  persistence failure with SQL/secret text, unhandled exception with
  traceback/path tokens, 401/404/405/400).
* Success shapes inventoried and left untouched (6T does not normalize
  successes); the intentional `200 {ok:true, errors[]}` import shape is
  documented, not a defect.
* Protected families verified: auth-first, 401 JSON contract, no HTML.

## 7. Database integrity audit

Per-mutation transaction behavior verified via before/after snapshots and
post-flush-failure rollback tests across rooms/faculty/sections/
assignments/specializations/memberships/locked blocks/preferences/
reassignment/swap/manual moves/generation. No orphans, FKs/uniques intact,
unrelated rows unchanged. Generation: failed runs (all statuses) preserve
the prior schedule; successful runs replace only non-locked rows (+ spec
slot prune/rebuild) with locked rows surviving exactly once.

## 8. Cross-feature audit

All 15 §20 combos VERIFIED — see matrix. No desynchronization, no stale
faculty ownership, no silent rewrites, soft preferences never hardening.

## 9. 6P audit

Single gate `emitOnSuccess` (success + non-noop only); per-mutation frozen
domain constants; validation/failure/no-op paths contain zero emits;
generation emits all schedule-dependent domains; preferred-room and
faculty-preference mutations emit config domains only (existing schedule
untouched until next generation). No duplicate-GET/infinite-loop/stale-view
defects found.

## 10. 6Q audit

Unified contract holds on every probed path; `normalizeFailure()` is the
single frontend boundary; unknown codes/network/malformed shapes degrade
safely; `FAILURE_LABELS` covers all backend codes (6T reused
`SCHEDULING_FAILED` — no label gap created).

## 11. Frontend integration audit

93/93 pass (7 files). Login/session, dashboard, timetable views + editor,
fixed blocks, specializations, preferences, reassignment, swaps, preferred
rooms, imports, errors, and refetch behavior verified via component +
contract + static path inspection. **Limitation:** no live browser
click-through (no automation available); API-contract + component +
static-path evidence instead.

## 12. Migration audit

`6c → 6e → 6f → 6j` linear chain verified on temp DBs (upgrade preserves +
adds, downgrade removes, idempotent re-upgrade, FKs intact, 6C-owned rows
preserved, revision links correct). Live-DB guard (`--allow-live`)
confirmed. Reference DBs untouched.

## 13. Defects found

| # | Severity | Defect |
|---|---|---|
| 6T-1 | HIGH | Solver UNKNOWN/timeout (and MODEL_INVALID) surfaced as "INFEASIBLE" |
| — | LOW (deferred) | Stale 6S-harness docstring describing the pre-6T folding (fixed as drive-by comment update, no behavior change) |

No CRITICAL defects found. No other HIGH/MEDIUM defects found.

## 14. Defects fixed

* **Defect:** scheduler timeout/UNKNOWN misreported as proven INFEASIBLE.
* **Root cause:** `scheduler.py` mapped every non-OPTIMAL/FEASIBLE outcome
  to `"INFEASIBLE"`; the API failure branch only knew
  `INFEASIBLE`/`NO_SESSIONS`.
* **Fix:** status-distinguishing return (`INFEASIBLE`/`UNKNOWN`/
  `MODEL_INVALID`) + API mapping (422 `SCHEDULING_FAILED` with timeout
  details / sanitized 500), preserving atomicity and the 6Q contract.
* **Regression test:** `backend/tests/test_scheduler_status_6t.py` (7 tests).

## 15. Deferred issues

None carried forward as defects. Accepted non-defect notes: demo DB's
pre-existing HN1 violations (illustrative data, README-disclosed);
`200-with-errors[]` import shape (intentional); production-readiness work
belongs to Phase 6V.

## 16. Test results

* Backend: **586 passed, 10 subtests passed** (579 baseline + 7 new; full
  runs pre- and post-fix, plus targeted reruns of 6Q/6E/6G/6N/migration/
  readonly suites — all green).
* Frontend: **93 passed** (7 files).
* `npm run lint`: clean. `npm run build`: succeeds (chunk-size warning only).
* Python: `py_compile` on touched files clean (no other Python
  lint/type tooling installed — reported, not pretended).

## 17. Lint/build

See §16. No new tooling installed.

## 18. Database safety

* `backend/instance/timetable.db` SHA256 `8D7AF21E…42071D` — identical
  before, during, and after all test campaigns (matches pre-6T value).
* `backend/instance/timetable_v2.db` SHA256 `171D57AC…D85641` — identical.
* Read-only proof: `audit_schedule` (SQLite `mode=ro`) executed against
  the reference DB with zero hash movement.
* No test/probe database was placed in production paths; temp files live
  under the OS temp dir or `TemporaryDirectory` (auto-cleaned).

## 19. Known limitations

1. No live browser click-through (no automation available) — frontend
   verified via component/contract/static-path evidence.
2. No Python lint/type tooling installed — `py_compile` minimum applied.
3. Demo reference DB carries pre-existing HN1 violations (pre-6T data
   condition, README-disclosed) — audit findings, not regressions.
4. Solver FEASIBLE and large-model timeout paths are covered by contract
   tests and benchmarks, not by an exhaustive soak matrix.

## 20. Final verdict

```text
COMPLETE WITH DOCUMENTED LIMITATIONS
```

All critical/high-risk areas verified; the one HIGH defect found was fixed
with regression tests; remaining limitations (above) are explicitly
accepted and do not hide correctness gaps.
