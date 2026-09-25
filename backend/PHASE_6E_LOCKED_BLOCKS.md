# Phase 6E — Locked Interdepartment Blocks (architecture note)

> Interdepartment classes are entered as preselected locked blocks.
> The scheduler treats them as immutable and builds all remaining
> classes around them.

## Lifecycle

```
TeachingAssignment (+ day/start/length/room)
  -> validate (shared rules, no bypass)
  -> persist LockedBlock + ScheduledClass atomically
     (ScheduledClass.is_locked=1, locked_block_id set)
  -> scheduler sees locked occupancy BEFORE solving
  -> audit detects inconsistencies (read-only)
  -> delete/cancel removes both rows atomically
```

`ScheduledClass` stays the timetable source of truth (helpers/views never
query `LockedBlock` for display). `LockedBlock` is constraint metadata.

## Schema

Phase 6C created `locked_block` (kind/subject/faculty/section/lab-group/
day/start/length/room/room_locked/…) plus
`ScheduledClass.is_locked/slot_id/locked_block_id`. Phase 6E adds exactly
one additive column via `6e_locked_assignment`:

- `locked_block.assignment_id` (nullable FK) — unambiguous demand link so
  the scheduler can subtract locked periods and validation can report
  `ASSIGNMENT_MISMATCH`. Pre-6E rows keep NULL.

## Scheduler integration (`backend/scheduler.py`)

`run_scheduler(..., locked_placements=None)`:

1. Re-validates locked geometry/break/day + locked-vs-locked collisions,
   faculty availability, HN1/H12 self-violation → `INFEASIBLE` naming the
   blocking locked blocks (never moved, never silently dropped).
2. Subtracts locked periods from each assignment's `periods_per_week`
   (fully-locked assignments schedule zero sessions).
3. Prunes normal candidates colliding with locked room/faculty/group/
   hierarchy cells, plus HN1/H12 single-candidate pruning (candidate +
   locked alone already violating ⇒ unavoidable).
4. Adds locked periods as CP-SAT constants: HN1 windows
   `sum + locked_n <= 2`, H12 windows `sum + locked_n <= max`.
5. Solves the remainder; returned placements exclude locked rows.

Unchanged: time limit (30s), workers (8), objective (minimize starts),
HN1 semantics. With no locked placements the encoding is byte-identical
in behavior to Phase 6D (verified: same status/counts per section).

`POST /api/schedule/run` loads locked placements, and on SUCCESS replaces
only non-locked rows; on FAILURE it writes nothing (previous schedule
preserved). Locked-caused failure returns `SCHEDULING_INFEASIBLE` with
`{locked_block_ids, reason}`.

## Validation & errors (`backend/locked_blocks.py`)

Pre-lock checks via `schedule_rules` + `schedule_validator`: `UNKNOWN_DAY`,
`PERIOD_OUT_OF_RANGE`, `BLOCK_GEOMETRY`, `BREAK_SPAN`, `ROOM_CONFLICT`
(+`conflicting_class_id`), `ROOM_CAPACITY`, `ROOM_TYPE_MISMATCH`,
`ROOM_EQUIPMENT`, `FACULTY_CONFLICT` (+`conflicting_assignment_id`),
`FACULTY_UNAVAILABLE`, `SECTION_CONFLICT`, `SECTION_HIERARCHY_CONFLICT`,
`MAX_TWO_THEORY`, `ASSIGNMENT_MISMATCH` (+`ROOM_REQUIRED`,
`UNKNOWN_ASSIGNMENT/ROOM`). `LockedBlockError.to_payload()` →
`{error, code, details, failures}`.

## Audit & validator (read-only / no UI)

- `audit_schedule.py`: `LOCKED_BLOCK_ORPHAN`, `LOCKED_BLOCK_MISSING`,
  `LOCKED_FLAG_MISSING`, `LOCKED_BLOCK_MISMATCH`, `LOCKED_ROOM_MISMATCH`,
  `LOCKED_ASSIGNMENT_MISMATCH`, `LOCKED_BLOCK_RULE_VIOLATION`,
  `LOCKED_BLOCK_CONFLICT`, `LOCKED_BLOCK_DUPLICATE`. Never writes.
- `schedule_validator.py`: `check_locked_immovable()` /
  `validate_move()` / `validate_candidate(..., editing_class_id=...)`
  refuse locked moves with `LOCKED_BLOCK` (+ids, attempted vs current).
  Foundation for Phase 6H; no editor UI here.

## API (`/api/locked-blocks`)

- `GET /api/locked-blocks` — list (with `scheduled_class_id` links).
- `POST /api/locked-blocks` — create (201 or structured 422).
- `POST /api/locked-blocks/<id>/delete` — cancel (removes both rows).
- Same session-cookie auth; `POST` mutations like the rest of the API.

## Explicitly out of scope

Specializations, faculty preferences, manual editor/drag-drop, swapping,
reassignment, room-preference optimization, frontend locked-block UI.
