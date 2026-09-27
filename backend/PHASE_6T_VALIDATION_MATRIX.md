# UniSchedule — Phase 6T Validation Matrix

Evidence-based audit of every feature area. Verdicts use exactly one of
`VERIFIED`, `PARTIALLY VERIFIED`, `NOT VERIFIED`, `FAILED`, `DEFERRED`.
Nothing is marked verified because code exists — each cell cites the test,
probe, or inspection that proves it. All mutation tests ran against
throwaway SQLite files in temp dirs (or duck-typed fakes with no IO);
the reference databases were never written (hash-proof in §DB Safety).

Backend suite at sign-off: **586 passed, 10 subtests passed**
(579 pre-6T baseline + 7 new `test_scheduler_status_6t.py`).
Frontend suite: **93 passed**. `npm run lint` clean, `npm run build` succeeds.

## Legend

* R = read test, M = mutation test, F = failure test, A = atomicity,
  D = DB safety (temp DBs only), X = cross-feature evidence.

## Matrix

| Area | Feature | R | M | F | A | D | X | Verdict | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| Auth | login/logout/session | ✓ | ✓ | ✓ | ✓ | ✓ | | VERIFIED | `test_errors_6q.py::test_auth_failures_distinguishable`; 401 uses unified `{ok:false,code:AUTH_REQUIRED}` (`api_routes.py`, `errors.py`); login/logout round-trip in every API test `setUp` |
| Auth | unauthenticated/invalid session | ✓ | ✓ | ✓ | ✓ | ✓ | | VERIFIED | 6Q suite: anon client gets 401 JSON (never HTML); no mutation before auth (`login_required` on all `/api/*` except login/shell) |
| Config | configuration read/write | ✓ | ✓ | ✓ | ✓ | ✓ | | VERIFIED | CRUD + validation-failure + rollback paths in backend suite; `CONFIG_DOMAINS` single-domain emit (`propagation.js`) |
| Rooms | room CRUD | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | create/delete, duplicate-name normalization (`validators.py`), import row warnings (`test_import_row_errors_preserved`); `ROOMS_DOMAINS` |
| Faculty | faculty CRUD + availability | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | create/delete, availability grid read/write, invalid-slot rejection; availability feeds solver pruning (`scheduler.py` H9) |
| Programs | program data | ✓ | ✓ | ✓ | ✓ | ✓ | | VERIFIED | create/delete + workload-import fan-out (`csv_import.py`); `PROGRAMS_DOMAINS` |
| Enrollments | enrollment data + auto sections | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | create/delete, section auto-generation, import path; `ENROLLMENTS_DOMAINS`; workload import emits `IMPORT_WORKLOAD_DOMAINS` |
| Sections | sections + preferred theory room | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | `test_preferred_room_6i*.py` + `test_preferred_room_api_6i.py` (set/clear/stale/lab/unknown); preference affects future generation only, emits `["sections"]` only — never `schedule` (`propagation.js:PREFERRED_ROOM_DOMAINS`) |
| Subjects | subjects | ✓ | ✓ | ✓ | ✓ | ✓ | | VERIFIED | create/delete + import matching; `SUBJECTS_DOMAINS` |
| Assignments | teaching assignments | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | create/delete, coverage/count validation (`test_faculty_assignment_api_6h.py`); `ASSIGNMENT_WRITE_DOMAINS` |
| Specializations | specialization admin | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | `test_specializations_6f.py`: create/duplicate/membership bounds/enrollment match/aggregate; `SPECIALIZATION_DOMAINS`, `MEMBERSHIP_DOMAINS` |
| Faculty preferences | TIME_WINDOW / DAY_OFF hints | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | `test_faculty_preferences_6j*.py`: invalid kind/days/period/weight rejected, hard prefs unsupported, disabled/malformed rows neutral; soft-only (never hard infeasibility); emits `["preferences"]` only |
| Locked blocks | fixed blocks | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | `test_locked_blocks_6e.py` (35 tests): create/list/delete, every conflict class (room/faculty/section/geometry/availability/HN1/H12/capacity), `is_locked=True` + `locked_block_id` linkage, `run_id="locked"`, generation preserves exactly once, delete removes both rows, failed creation leaves neither row |
| Schedule generation | OPTIMAL path | ✓ | ✓ | | ✓ | ✓ | ✓ | VERIFIED | `test_scheduler_objective_6s.py` benchmarks (30-session OPTIMAL ~2s class, 60-session ~9s class); run metadata (`status/placements/run_id`) correct; success atomically replaces non-locked rows + rebuilds spec slots, preserves locked rows |
| Schedule generation | FEASIBLE path | ✓ | ✓ | | ✓ | ✓ | | VERIFIED | `run_scheduler` returns `"FEASIBLE"` distinctly (never upgrades to OPTIMAL); API success shape carries real `status` string; GeneratePanel displays it verbatim |
| Schedule generation | INFEASIBLE path | ✓ | | ✓ | ✓ | ✓ | ✓ | VERIFIED | `test_24_infeasible_generation_preserves_schedule`; failure branch writes nothing; 422 structured (`SCHEDULING_FAILED` / `SCHEDULING_INFEASIBLE` / spec codes); frontend renders `FailureList`, emits nothing |
| Schedule generation | UNKNOWN / TIMEOUT path (6T fix) | ✓ | | ✓ | ✓ | ✓ | | VERIFIED | NEW `test_scheduler_status_6t.py` (7 tests): solver UNKNOWN → `"UNKNOWN"` (message names the time limit, never "infeasible"); API → 422 `SCHEDULING_FAILED` + `{status:UNKNOWN, timeout:true}`; previous schedule byte-identical |
| Schedule generation | MODEL_INVALID path (6T fix) | ✓ | | ✓ | ✓ | ✓ | | VERIFIED | NEW: solver MODEL_INVALID → `"MODEL_INVALID"`; API → sanitized 500 `INTERNAL_ERROR` (no solver internals leak); schedule preserved |
| Schedule generation | unexpected exception | ✓ | | ✓ | ✓ | ✓ | | VERIFIED | `test_unhandled_exception_sanitized_500` (patched `run_scheduler` raising): 500 `INTERNAL_ERROR`, no traceback/SQL/path/secret tokens in body |
| Manual editor | validate-move dry-run | ✓ | | ✓ | ✓ | ✓ | | VERIFIED | `api_validate_move` calls `validate_move_candidate` only (no writes); `test_move_conflict_preserves_db`; `test_view_read_is_read_only` |
| Manual editor | move apply | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | `test_manual_edits_6g.py` + `test_manual_edits_6n.py`: success moves only intended placement (footprint contiguous, ownership preserved), failure rolls back, locked/spec classes immovable, HN1/H12 enforced, scheduler never invoked, no-op move returns `noop` and emits nothing |
| Faculty reassignment | validate + reassign | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | `test_faculty_reassignment_6h.py` + API tests: dry-run validation, scheduled classes derive faculty from assignment, conflicts/locked/spec restrictions enforced, atomic commit-or-rollback (post-flush failure test proves rollback) |
| Faculty swaps | validate + swap | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | `test_faculty_swap_6h.py` + API tests: simultaneous both-side validation, common-snapshot conflict detection, atomic both-or-neither, locked + normal↔spec restrictions, no stale ownership (`run_ids` preserved — no regeneration) |
| Preferred rooms | section preference lifecycle | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | set/clear/stale/lab/unknown covered; soft 0/1 objective term only (`preferred_room_penalty` pure); existing timetable untouched; `PREFERRED_ROOM_DOMAINS == ["sections"]` asserted in propagation tests |
| Exports/imports | CSV flows | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | VERIFIED | malformed type/missing fields/duplicates/invalid refs covered; partial-row success stays **200 `{ok:true, errors[]}` by design** (documented, not a defect — `normalizeFailure` surfaces `errors[]` as `importErrors`); sanitized 422s (`test_import_missing_file`) |
| Timetable UI | views/editor | ✓ | ✓ | ✓ | | | ✓ | VERIFIED | `timetable-6r.test.jsx` (12) + `test_timetable_cells_6r.py` (shape keys untouched, lock/spec linkage surfaced, view-read read-only); editor never calls `schedule/run`; no browser click-through performed (limitation, see audit §19) |
| Error system | 6Q contract | ✓ | ✓ | ✓ | | | ✓ | VERIFIED | `test_errors_6q.py` + `errors-6q.test.js` + `error-components-6q.test.jsx` (23+12): every error `{ok:false, error, code}`; no bare/codeless/HTML/raw-`str(exc)` responses; unknown codes + network + malformed shapes degrade safely |
| Invalidation | 6P domains | ✓ | ✓ | ✓ | | | ✓ | VERIFIED | `propagation.test.js` + `invalidation.test.js` + `use-api.test.jsx` + `cross-surface.test.jsx` (46): `emitOnSuccess` gate (success + non-noop only); validation/failure/no-op paths emit nothing; generation emits `GENERATION_DOMAINS`; no GET-triggered emits; no subscription leaks in tests |

## Cross-feature combos (spec §20)

| Combo | Verdict | Evidence |
|---|---|---|
| A. Locked block + HN1 | VERIFIED | `test_14_hn1_violation_rejected`, `test_22_hn1_still_applies_with_locked_theory` |
| B. Locked block + room conflict | VERIFIED | `test_09_room_conflict_rejected` (+ atomic neither-row proof `test_5`) |
| C. Locked block + generation | VERIFIED | `test_16/17/18_locked_*`, `test_24_infeasible_generation_preserves_schedule` |
| D. Specialization + HN1 | VERIFIED | `test_theory_contributes`, `test_spec_theory_plus_two_normal_triggers` |
| E. Specialization + manual move | VERIFIED | spec classes immovable (6F + 6G suites; `locked_blocks`/manual-edit guards) |
| F. Specialization + faculty swap | VERIFIED | swap restriction tests (`test_faculty_swap_6h.py`, spec-invalid cases) |
| G. Reassignment + existing schedule | VERIFIED | `test_faculty_reassignment_6h.py` placement revalidation |
| H. Swap + existing schedules | VERIFIED | `test_faculty_swap_6h.py` common-snapshot tests |
| I. Preferred room + generation | VERIFIED | `test_preferred_room_api_6i.py` two-generation test; no silent rewrite |
| J. Faculty preference + generation | VERIFIED | 6J suites: optimization-only effect, soft-only |
| K. Manual move + preferred room | VERIFIED | hard validation governs moves; soft preference never consulted in `manual_edits.py` (static inspection + 6I/6N suites) |
| L. Generation failure + previous schedule | VERIFIED | `test_24_*`, 6T UNKNOWN/MODEL_INVALID preservation tests |
| M. Generation success + 6P | VERIFIED | `GENERATION_DOMAINS` emit asserted; schedule/dependent views refetch (`cross-surface`) |
| N. Mutation failure + 6P | VERIFIED | `emitOnSuccess` returns false for `ok:false` (propagation tests, all domains) |
| O. No-op move + 6P | VERIFIED | `noop:true` → no emit (propagation tests for move/reassign/swap) |

## DB Safety

* Reference DBs `backend/instance/timetable.db` (`8D7AF21E…20

...[truncated 2085 chars]