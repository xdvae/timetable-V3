# Phase 6S — Scheduler Objective Audit

Date: 2026-09-27. Code inspected: `backend/scheduler.py` (objective lines
1012–1045, helpers 117–199), `backend/faculty_preferences.py` (normalize +
penalty), `backend/schedule_rules.py`, `backend/schedule_validator.py`,
`backend/api_routes.py` (solver call site), `backend/models.py`
(`FacultyPreference` weight CHECK), existing tests `test_preferred_room_6i.py`
/ `test_faculty_preferences_6j.py`. All benchmarks below were re-run on the
current tree (OR-Tools 9.10.4067); historical numbers quoted in the 6S brief
were reproduced, not assumed.

## A. Current objective formula (actual code)

Per candidate placement variable `x[(s, day, start, room)]`, `run_scheduler`
minimizes (`scheduler.py` 1035–1045):

```text
min  SUM_over_chosen_placements( start * K + room_pen + fac_pen )
```

where for one placement:

- `start` = 0-based start-period index (NOT length-weighted, NOT day-weighted).
- `room_pen` = `preferred_room_penalty(session, room_id, preferred_map)` in {0,1}.
- `fac_pen` = `faculty_time_penalty(faculty_id, day, start, length, faculty_map)`
  in {0,1} (binary cap `MAX_FACULTY_PENALTY_PER_SESSION = 1` by construction).
- `K = time_scale` chosen once per solve:

```text
faculty_map non-empty  ->  K = 2*N + 1   (faculty_time_scale)
otherwise              ->  K = N + 1     (preferred_time_scale)
N = len(sessions) = normal sessions + specialization sessions
```

`preferred_map = normalize_preferred_rooms(...)`, `faculty_map =
normalize_faculty_preferences(...)`. Locked placements are pre-solve constants
and contribute no objective term. Domains and every hard constraint are built
before/without the maps, so feasibility is identical with or without either
map (verified by backward-compat tests in 6I.2 / 6J).

Total objective = `K * (sum of chosen starts) + (sum of room pens) + (sum of
fac pens)`. Secondary sums are each bounded by N (see C), combined by 2N.

## B. Objective components

| # | Name | Source | Unit | Range (per session / total) | Hard/soft | Active when | Normal | Lab/practical | Spec | Locked |
|---|------|--------|------|-----------------------------|-----------|-------------|--------|---------------|------|--------|
| 1 | start cost `start*K` | `run_scheduler` | start-period index points x K | per session `0..(P-1)*K`; total `0..N*(P-1)*K` | soft | always (N>0) | yes | yes | yes | never (constants) |
| 2 | preferred-room penalty | `preferred_room_penalty` + `normalize_preferred_rooms` | 0/1 per session | per session {0,1}; total `0..N` (in practice only whole-section theory with a live mapping can score 1) | soft | `preferred_map` non-empty AND session is theory AND `group_key == "section:<id>"` AND section has a mapped room | theory-only | always 0 | always 0 (`specialization:<id>` key never matches) | never |
| 3 | faculty-preference penalty | `faculty_time_penalty` + `normalize_faculty_preferences` | 0/1 per session (capped over all of a faculty's surviving rows) | per session {0,1}; total `0..N` | soft | `faculty_map` non-empty AND faculty has >=1 surviving row AND placement violates >=1 of them | yes | yes | yes (through the spec session's own faculty; sync equalities are hard so the penalty only ranks synchronized alternatives) | never |

Normalizer behavior (both neutral on missing/stale input):

- Preferred rooms: drops None values, unknown room ids (deleted rooms),
  non-integer junk. A dropped entry == no preference. An incompatible-but-known
  room (e.g. a lab mapped for a theory section) survives normalization but can
  never be chosen (hard `compatible_rooms` filters it), so that section scores
  a uniform +1 on every feasible candidate — a constant offset that cannot
  change the optimum (see E).
- Faculty prefs: drops disabled rows (incl. `False/0/"false"/"no"` spellings),
  unknown/deferred kinds (`SUBJECT_AFFINITY`, anything else), unknown faculty
  ids, days outside working days (`TIME_WINDOW` blank days = all working days;
  `DAY_OFF` with no usable day is dropped), impossible ranges
  (`0 <= start < end <= num_periods` enforced). `is_hard`/`weight` are
  deliberately not consulted: even a legacy `is_hard=True` row scores as soft.
  `weight` (1–10, DB CHECK + API validation) is stored/returned but never
  enters the penalty — equal weighting is intentional per the 6J product
  decision (see §11 below).

`TIME_WINDOW` semantics: satisfied only when the day is listed AND every
covered period lies in `[start_period, end_period)`; partial overlap still
violates (binary 1). `DAY_OFF_PREFERENCE`: violated (1) on any placement whose
day is listed.

## C. Scaling (why K dominates, and the proof)

`preferred_time_scale(N) = N + 1`. Maximum possible total room penalty is N
(one per session, and only a subset of sessions can ever score 1). Hence one
start-period unit (`K = N+1`) strictly exceeds every achievable room-penalty
improvement (`<= N`): `N < N+1` for all `N >= 0` (unit-tested for N in
0,1,2,7,40 in `test_preferred_room_6i.py::TestTimeScale`).

`faculty_time_scale(N) = 2*N + 1`. Maximum combined secondary is
`N (room) + N (faculty) = 2N`, so one start unit (`2N+1`) strictly exceeds any
combined secondary improvement: `2N < 2N+1` (unit-tested in
`test_faculty_preferences_6j.py::TestFacultyTimeScale`). The two secondaries
share equal footing: each is bounded by N, so neither can systematically
dominate the other; among time-equal alternatives they trade 1-for-1 (documented
intent, verified by `TestRoomCoexistence`).

Scale-selection subtlety (verified, safe): the branch is `if faculty_map:`
— i.e. it keys on *surviving normalized* prefs, not raw input rows. Junk-only
input yields `{}` and keeps `K = N+1`, which is correct because there is no
active secondary to dominate. When the faculty map is active but the room map
is empty, `K = 2N+1` still dominates (room part is uniformly 0); the
coefficients are marginally larger than the theoretical minimum (`N+1` would
suffice) but the hierarchy proof still holds with zero behavior change.

Coefficient growth / overflow: per-term max is `(P-1)*K + 2` with
`K = 2N+1`. For realistic sizes (P <= ~12, N <= ~300) the total objective is
below ~2M, deep inside CP-SAT's int64 domain. No overflow plausibility; all
coefficients are small non-negative integers (integer-safe by construction).

## D. Objective equivalence (lexicographic proof + concrete examples)

The objective is effectively lexicographic `start > (room, faculty)`:

- With faculty prefs inactive: improving total start by 1 (worth `N+1`) beats
  *any* room-penalty change (at most N). Verified live: with R101 preferred but
  pinned at Mon P0 by a lock, the solver places the normal session at Mon P0
  R102 (start 0, room_pen 1, cost `0*(N+1)+1 = 1`) rather than waiting for
  Mon P1 R101 (start 1, room_pen 0, cost `1*(N+1)+0 = N+1`).
  (`TestStartDominance`, re-run green.)
- With faculty prefs active: improving total start by 1 (worth `2N+1`) beats
  any combined secondary change (at most 2N). Verified live: a `TIME_WINDOW`
  `[2,4)` on a 4-period day still yields start 0 (cost `0*3+1 = 1`) over start
  2 inside the window (cost `2*3+0 = 6`) for N=1, K=3.
  (`test_time_dominance_over_preference`, re-run green.)
- Day indifference (documented, intended): days carry no cost, so equal starts
  on different days tie at the primary tier and secondaries decide the day
  (e.g. single session, Mon P0 vs Tue P0 tie -> Tue-only window pulls to Tue;
  re-run OPTIMAL). Consequence: for one section needing 3 sessions, Mon0/Tue0/
  Wed0 (start sum 0) beats Mon0/Mon1/Mon2 (start sum 3) — the objective spreads
  early periods across days rather than packing one day. The module docstring's
  "pack each group's day" holds *within* a day (no gaps, early finish); across
  days the solver prefers parallel-early. This matches all shipped behavior and
  tests; no change proposed.
- Length indifference: a length-2 block at start 0 costs the same as length-1
  at start 0. Lengths affect feasibility/occupancy only. Documented; no change.
- Room/faculty tie-breaks are 1-for-1 with no priority between them (by
  design): `test_room_and_faculty_prefs_combine` shows both applying on a
  three-way tie (Tue + R101). No counterexample to the start-dominance claim
  was found; the `K > max-secondary` proof is valid for every N >= 0,
  including N = 0 (K = 1, empty model returns NO_SESSIONS before solving).

## E. Dead or weak objective terms

- No never-active term was found: each of the three terms binds in an
  important case (start always; room when a live theory mapping exists;
  faculty when a surviving row exists).
- Uniform-constant case (weak but harmless): a section whose mapped room is
  hard-incompatible scores +1 on *every* feasible candidate. The term is then a
  constant offset with zero ranking effect; presolve absorbs it. Same when all
  feasible alternatives violate (or all satisfy) a faculty preference. Left as
  is — removing it would require per-section domain analysis for zero gain.
- `weight` (1–10) is stored, validated, defaulted (5), and returned, but does
  not enter the objective. Verified intentional (6J product decision); see §11.
- `SUBJECT_AFFINITY` rows (and any unknown kind) are dropped by the normalizer
  and rejected by the API with `PREF_INVALID_KIND`. Verified neutral; see §12.
- Stale preferred-room ids (room deleted) are dropped by the normalizer and
  behave exactly like no preference (covered by `test_unknown_room_id`).
- Nothing was removed: there is no provably-influential-term deletion
  available (Strategy D evaluated, no candidate).

## F. Solver performance (re-run on current tree)

Harness: `backend/tests/test_scheduler_objective_6s.py` (isolated, fake
objects, no DB). Machine: Windows, OR-Tools 9.10.4067, `max_time 30s`,
`num_search_workers 8`, default presolve/search, no seed. Representative
results (OPTIMAL in every row; single-run wall times, noisy ±0.5s):

| Scenario | Sessions | Scale K | Status | Wall | Objective (recomputed) | Notes |
|----------|----------|---------|--------|------|------------------------|-------|
| A baseline (15 asg x2ppw, 3 rooms, 5 days x7, HN1+H12) | 30 | 31 | OPTIMAL | ~2.3s | 465 (= 15 start-points x 31) | Reproduces the historical baseline (465 / ~3.6s class) |
| B preferred rooms (same + 4 section maps) | 30 | 31 | OPTIMAL | ~2.2s | 465 + room misses | Same scale/optimum shape; room term only re-ranks ties |
| Combined (same + room maps + 5 faculty TIME_WINDOWs) | 30 | 61 | OPTIMAL | ~2.8s | 931 | Reproduces the historical ~925–933 / scale-61 class; 6 fac violations accepted to keep starts low |
| C TIME_WINDOW micro (1 session, 2 days) | 1 | 3 | OPTIMAL | <0.1s | — | Tue-only window pulls Mon P0 tie -> Tue P0 |
| D DAY_OFF micro | 1 | 3 | OPTIMAL | <0.1s | — | Mon-off pulls tie -> Tue |
| Late-window vs early-start | 1 | 3 | OPTIMAL | <0.1s | start 0 kept (cost 1 < 6) | Start dominance, concrete numbers |
| G larger model (2x assignments) | 60 | 61/121 | OPTIMAL | ~8–12s (noisy) | scales linearly | No disproportionate blowup observed at this size; 30s limit untouched |

Model-size reporting: `run_scheduler` exposes no variable/constraint counters
(diagnostic intentionally not plumbed through the production API per §25), so
the harness reports assignment/session/candidate-estimate counts plus wall
time, status, and recomputed objective — sufficient to judge quality/time
tradeoffs without an API change. No timeout occurred in any scenario; per §7 a
timeout would be reported as TIME_LIMIT/UNKNOWN, never as INFEASIBLE, by the
harness (the solver wrapper's conflation is a separate documented limitation,
see §18).

## Solver configuration (§18)

`max_time_in_seconds = 30` (production call site passes 30; tests use 10–15),
`num_search_workers = 8`, presolve/search/symmetry/linearization all OR-Tools
defaults, no `random_seed` set, no solution hints. Consequences:

- Live re-runs show arbitrary but valid tie-breaking among equal-cost optima
  (e.g. a single unconstrained session lands in R102 vs R101 depending on room
  input order/search). Deterministic *cost* but not deterministic *placement*
  among ties. Unchanged: setting a seed / reducing workers would trade speed
  for reproducibility and needs its own benchmark per §18 — explicitly NOT done
  in 6S.
- 30s limit retained without change (§19). All benchmark models solve OPTIMAL
  well inside it; the limit was never the binding constraint here.

Known wrapper limitation (documented, deferred, NOT changed in 6S):
`scheduler.py` 1052–1059 maps every non-OPTIMAL/FEASIBLE solver outcome to the
string `"INFEASIBLE"`, which conflates a genuine proof of infeasibility with a
time-limit/UNKNOWN outcome that simply produced no solution yet. The 6S
harness distinguishes them (it never calls a timeout INFEASIBLE); fixing the
wrapper return contract would change the `api_routes` failure path (which keys
on `"INFEASIBLE"`), so it is deferred to 6T with this note rather than fixed
silently here.

## Preference hierarchy (§10) and weight (§11) and affinity (§12)

- Hierarchy `start placement > preferred room == faculty preference` is
  intentional (6I.2 / 6J design docs + code comments at 1012–1034), technically
  enforced by the `K` proofs above, and covered by dominance tests. No change.
- `weight` equal-treatment is intentional (6J: "reserved for future
  prioritization"; needs a separate product decision before activation). 6S
  leaves it stored-but-unused. No change.
- `SUBJECT_AFFINITY` stays deferred (API-rejected, normalizer-neutral,
  validator-untouched). No change.

## Hard-constraint regression posture (§13–§17)

Every objective term is additive ranking over identical domains and identical
hard constraints (room/faculty/group occupancy, H8 hierarchy, H12 windows,
HN1 windows, capacity/equipment/type, availability, geometry/break/day,
coverage, locked constants, specialization equalities + conservative section
blocking). The 6S test module re-asserts HN1/H12/occupancy/availability/
locked-immovability/spec-sync on optimized outputs, and the full pre-existing
scheduler suites (`test_preferred_room_6i`, `test_faculty_preferences_6j`,
`test_hn1`, `test_locked_blocks_6e`, `test_specializations_6f`,
`test_schedule_rules`, `test_schedule_validator`) must stay green.

## 6S conclusion

Strategies evaluated: A (retain) — adopted. B (safer scaling) — unnecessary:
current K values already equal the exact dominance bounds (`N+1`, `2N+1`), so
there is no tighter safe integer. C (staged solving) — rejected without
prejudice: single objective already expresses the hierarchy with proof, and
staged solves would cost 2–3x wall time for no quality gain. D (simplification)
— no removable term found. Residual 6S code work is therefore limited to (1)
this audit, (2) the reproducible harness + quality tests, and (3) an optional
zero-behavior explicitness refactor of the objective arithmetic into named
helpers (§20) — no coefficient, hierarchy, solver-config, API, schema, or
frontend change.

## Traceability (request -> result path, current code)

`POST /api/schedule/generate` (`api_routes.py` ~1290–1406: load config/rooms/
faculty/assignments/locks/specs/room-maps/pref-rows) -> `run_scheduler(...)`
-> locked pre-checks + demand subtraction -> normal/spec split + session
expansion -> candidate generation (`compatible_rooms`, `valid_starts`,
availability/HN1/H12/locked pruning) -> hard constraints (H1/H5–H8/H12/HN1 +
spec equalities/blocking) -> soft penalties (`preferred_room_penalty`,
`faculty_time_penalty`) -> `model.Minimize(sum((start*K + room + fac) * x))`
-> `CpSolver.Solve` (30s, 8 workers) -> status mapping -> placements ->
atomic persistence around locked rows (non-locked replaced, locked untouched).
