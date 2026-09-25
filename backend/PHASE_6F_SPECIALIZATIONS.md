# Phase 6F — Specializations (backend/domain/scheduler foundation)

> Specialization scheduling currently uses conservative originating-section
> occupancy rather than individual student-level scheduling.

From ~Semester 3 a program/cohort (enrollment) may offer several
specializations (e.g. Cyber Security, AI, Full Stack). Students stay members
of their normal sections (BCA-3-A/B/C) and select one specialization.
Specialization teaching is an additional footprint scheduled at synchronized
times across the cohort.

## Data model

Existing Phase 6C tables are reused (no recreation):

* `specialization(id, name, enrollment_id, session_type, block_length,
  periods_per_week)` — one row per specialization; `name+enrollment` unique.
* `specialization_membership(id, specialization_id, section_id,
  student_count)` — headcount per originating section; `student_count > 0`
  CHECK preserved; `spec+section` unique.
* `specialization_slot(id, specialization_id, day, start_period, length)` —
  synchronized time windows (scheduler output in 6F, one row per spec per
  session with identical day/start/length across the cohort).
* `scheduled_class.slot_id` — links a spec class to its slot;
  `ScheduledClass` stays the timetable source of truth.

Phase 6F additive change (`6f_specializations`, depends on `6e`, chain
`6C → 6E → 6F`, reversible):

* `teaching_assignment.specialization_id` (nullable FK → specialization) +
  index `ix_teaching_assignment_specialization`. When set, `section_id` /
  `lab_group_id` stay NULL; faculty/subject/periods/block live on the
  assignment (existing assignment model, no parallel system). Pre-6F rows
  keep NULL (normal teaching unchanged).

## Membership semantics

* `student_count > 0` (`SPECIALIZATION_MEMBERSHIP` otherwise).
* Section must belong to the specialization's enrollment
  (`SPECIALIZATION_ENROLLMENT` otherwise; cross-cohort merges rejected).
* `student_count <= section.student_count`
  (`SPECIALIZATION_CAPACITY` with `{section, capacity, requested,
  existing, remaining}`).
* Aggregate: `sum(student_count across the section's specializations)
  <= section enrollment` (`SPECIALIZATION_CAPACITY`, never silently
  reduced). Example: 40-cap section with 15+15+10 = 40 valid, 20+15+10 = 45
  rejected.
* Duplicate `spec+section` rejected (`SPECIALIZATION_MEMBERSHIP`).
* Empty specialization (no memberships) may exist during configuration but
  produces no sessions (skipped by the scheduler). Single-spec cohorts work.

## Synchronization semantics

* Active specs = specs with memberships (and assignments for scheduling).
* All active specs in one enrollment share identical slot patterns:
  same count, same sorted `[(day, start, length)]`
  (`SPECIALIZATION_SYNC` otherwise; rooms/faculty deliberately ignored).
* Slot `length` must equal the cohort's block pattern; demand signatures
  `[(length, session_type)]` per spec must match
  (`SPECIALIZATION_SYNC` on count/length/type mismatch).
* Scheduler enforces explicitly (never by hope):
  `start(Cyber,i) = start(AI,i) = start(Full,i)` and `day` equal per `i`
  via `sum_rooms x == sum_rooms x` equalities; lengths validated equal.

## Scheduling behavior

* One CP-SAT solver (no second scheduler). Unchanged: 30s limit, 8 workers,
  minimize-starts objective (now over normal+spec sessions), breaks,
  working days, faculty availability, H5/H6/H7, H8, H12, HN1, locked blocks.
* Spec session: `total = sum(memberships)`, compatible room by
  `session_type` + `total` (different rooms allowed, different faculty
  allowed; same room/faculty at the same synchronized time conflicts).
* Section occupancy (conservative): a synchronized slot blocks every
  participating section for normal teaching (`SPECIALIZATION_OVERLAP`).
  Counted ONCE per cohort per period (representative indicator, never
  triple-counted). Unrelated sections may coexist. Lab-group practicals of
  participating sections are also blocked.
* Cohort internal: at most one synchronized session covers a cell.
* Locked blocks: spec candidates prune on locked room/faculty/section
  occupancy (including `__parent__` lab footprint); locked theory/faculty
  constants apply to HN1/H12; `POST /api/schedule/run` preserves locked rows
  and rebuilds spec slots. Locking a specialization assignment as an
  interdepartment block is rejected (`SPECIALIZATION_OVERLAP`).
* No compatible room → `SPECIALIZATION_CAPACITY`. No legal slot →
  `SPECIALIZATION_OVERLAP`. Demand mismatch → `SPECIALIZATION_SYNC`.
* `POST /api/schedule/run` persists spec classes with `slot_id` and prunes
  stale slots; failure writes nothing.

## Room capacity

Room must hold the whole specialization headcount
(`total = A+B+C`, e.g. 12+10+8 = 30). Undersized rooms are never used;
audit reports `SPECIALIZATION_ROOM_CAPACITY`.

## Section occupancy

See above: union of participating sections blocked per synchronized slot,
once per cohort. Student-level timetables are out of scope.

## HN1 interaction

* Spec theory participates once per section in
  `MAX_TWO_THEORY` (shared `schedule_rules.check_max_two_theory`; practicals
  contribute 0).
* Example: `P1 DBMS theory + P2 AI theory + P3 spec theory = 3 in a window`
  rejected.
* Breaks/free periods reset (windows never cross the break).
* Synchronized specs never multiply-count: representative indicator + set
  unions in validator/audit/scheduler.

## Locked-block interaction

Spec scheduling respects room/faculty/section locked occupancy, break/day
geometry, availability, HN1/H12 constants. Phase 6E lifecycle untouched.

## API endpoints

Session-cookie auth, POST-style mutations (like the rest of the API).
Errors use `ApiError {error, code, details, failures}`.

* `GET /api/specializations` — list with memberships, totals, slots,
  scheduled classes (rooms, faculty).
* `GET /api/specializations/<id>` — single with schedule.
* `POST /api/specializations` — `{name, enrollment_id, session_type?=theory,
  block_length?=1, periods_per_week?=2}` → 201 or structured 422.
* `POST /api/specializations/<id>/memberships` — upsert
  `{section_id, student_count}`.
* `POST /api/specializations/<id>/memberships/delete` — `{section_id}`.
* `POST /api/specializations/<id>/delete` — removes spec + memberships +
  slots + its assignments/classes.
* `POST /api/assignments` extended with optional `specialization_id`
  (subject must match the spec cohort; section/lab must be omitted).
* `POST /api/schedule/run` — includes cohorts automatically; structured
  `SPECIALIZATION_*` errors on failure; `specializations_scheduled` on
  success.

## Validation codes

* `SPECIALIZATION_CAPACITY` — aggregate/room capacity exceeded.
* `SPECIALIZATION_SYNC` — slots or demand patterns differ.
* `SPECIALIZATION_OVERLAP` — spec vs normal teaching collision (or locking
  a spec assignment).
* `SPECIALIZATION_ENROLLMENT` — cross-cohort section/subject.
* `SPECIALIZATION_MEMBERSHIP` — bad count/duplicate/config.
* `SPECIALIZATION_ORPHAN`, `SPECIALIZATION_MEMBERSHIP_INVALID`,
  `SPECIALIZATION_ROOM_CAPACITY` — audit findings (read-only).
* Reused: `MAX_TWO_THEORY`, `ROOM_CONFLICT`, `FACULTY_CONFLICT`,
  `LOCKED_BLOCK`, `SCHEDULING_INFEASIBLE`, etc.

## Migration

`backend/migrations/versions/6f_specializations.py` (`revision =
6f_specializations`, `down_revision = 6e_locked_assignment`):
`ADD COLUMN teaching_assignment.specialization_id` + index; downgrade drops
both. Additive, reversible, old rows NULL, IDs stable, new tables empty on
baseline. Tested `upgrade → audit → downgrade` on an isolated copy.

## Test strategy

`backend/tests/test_specializations_6f.py` (isolated temp DBs, never
`timetable_v2.db`): configuration (10), synchronization (8), scheduling
(10), HN1 (6), migration (2), API (3), audit (5). Plus full regression
(6C/6D/6D.2/6E), frontend `npm run lint` + `npm run build`, and baseline
SHA/size/row-count verification before/after.

## Known limitations

* No frontend UI; no drag-drop/manual editing/swapping/reassignment.
* No preferred-room optimization or faculty soft preferences.
* No student-level scheduling (conservative section blocking).
* One teaching pattern per cohort (all specs share count/length/type);
  multiple assignments per spec must share the pattern.
* Slots are scheduler output (no manual slot editor in 6F).
* No audit history/logging or automatic student-preference assignment.
