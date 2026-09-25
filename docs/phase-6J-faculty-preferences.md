# Phase 6J — Faculty Custom Preferences (design note)

## What they are

Optional per-faculty scheduling hints stored on the existing
`faculty_preference` table (added in 6C, first consumed here). An
administrator can express, per faculty member:

- `TIME_WINDOW` — prefers teaching inside `[start_period, end_period)`
  on `days` (blank = every working day);
- `DAY_OFF_PREFERENCE` — prefers no teaching on `days`.

Every 6J preference is **soft**: it nudges the scheduler objective but
can never forbid a placement. Hard unavailability stays exclusively on
the faculty availability grid (`unavailable_slots`, rule H9).

## Audit outcome (why only these two kinds)

| Candidate | Verdict | Reason |
|---|---|---|
| `TIME_WINDOW` | SAFE, implemented | Per-placement 0/1 penalty, precomputable, pure |
| `DAY_OFF_PREFERENCE` | SAFE, implemented | Same encoding (a placement on a listed day costs 1) |
| `SUBJECT_AFFINITY` | DEFERRED (API rejects) | Assignment-level affinity, not a per-placement property; no clean solver encoding |
| Per-faculty soft max-consecutive | DEFERRED | Non-linear day-run reasoning; global hard H12 limit already protects faculty |
| `is_hard = true` | UNSAFE (API rejects) | Would convert soft hints into feasibility risks |
| `weight` (1–10) | Stored, reserved | Accepted/validated/returned; the 6J scheduler counts all enabled prefs equally so the objective hierarchy stays provable |

## Objective math

Per session placement cost:

```
cost = start * K + room_penalty(0/1) + faculty_penalty(0/1)
```

- `room_penalty` — Phase 6I home-room term (unchanged).
- `faculty_penalty` — 1 when the placement violates any surviving
  preference of the session's faculty
  (`TeachingAssignment.faculty_id`; never duplicated onto
  `ScheduledClass`), else 0. Binary cap = `MAX_FACULTY_PENALTY_PER_SESSION`.
- `K = N + 1` (`preferred_time_scale`) when no faculty prefs survive
  normalization — the model is then exactly the 6I model.
- `K = 2N + 1` (`faculty_time_scale`) when any survive: one start-period
  unit outweighs room + faculty improvements combined (max `2N`), so
  time-compactness stays strictly dominant while the two secondary
  categories share equal footing (each bounded by `N`).

Consequences: an earlier start always beats any preference combination;
preferences only arbitrate among time-equal alternatives. Domains and
hard constraints are untouched — feasibility is identical with or
without preferences.

## Interaction notes (all verified by tests)

- **Manual edits / reassignment / swaps**: validate hard rules only;
  moving away from (or into) a preference is valid, and preference
  mismatches never block ownership changes.
- **Locked blocks**: constants in the solver, never re-emitted; a locked
  placement outside a window stays exactly where it is.
- **Specializations**: cohort synchronization is enforced by hard
  equality constraints, so per-faculty penalties can only rank
  synchronized alternatives, never split a cohort.
- **Missing/malformed data**: no rows → zero penalty (6I-identical
  model); disabled/unknown/deferred/out-of-range rows are dropped by
  `normalize_faculty_preferences`, never crash the solver.
- **Migration** (`6j_faculty_preferences`): `CREATE TABLE IF NOT EXISTS`
  + faculty lookup index; downgrade drops only the index (the table is
  6C-owned). No schedule row is touched.
- Preference edits mutate only `faculty_preference` rows and apply to
  **future generations**; the current timetable is never moved.
