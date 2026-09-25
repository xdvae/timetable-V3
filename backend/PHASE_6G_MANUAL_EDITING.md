# Phase 6G — Manual Timetable Editing + Shared Move Validation

> Phase 6G supports moving normal scheduled classes. It does not yet provide drag-and-drop UI, faculty reassignment, faculty swapping, or cohort-wide specialization movement.

## Move semantics

One narrow, atomic operation: relocate a single existing `ScheduledClass`
to a new `(day, start_period, room_id)`. Only those three fields may
change; `assignment_id`, `length`, `run_id`, `is_locked`, `slot_id`, and
`locked_block_id` are preserved and cannot be altered through the move
endpoints (extra body fields are ignored). A move never relocates
unrelated classes and never reruns CP-SAT. A same-position request is a
no-op success with no database write. `ScheduledClass` remains the single
source of truth, so section/faculty/room views reflect the move
immediately.

## Validation flow

```
API (move / validate-move)
  -> manual_edits.validate_move_candidate (no writes)
       1. load ScheduledClass (missing -> MANUAL_EDIT_INVALID / 404)
       2. locked? (is_locked OR locked_block_id set -> LOCKED_BLOCK)
       3. specialization assignment? (-> SPECIALIZATION_SYNC)
       4. same position? -> ok/noop
       5. build ScheduleSnapshot from current rows
       6. snapshot_without(class) — the class never conflicts with itself
       7. schedule_validator.validate_candidate on the slim snapshot
          (H2/H3/H4 room, H5/H6/H7 occupancy, H8 hierarchy, H9
          availability, H10/H11/H13 geometry, HN1 incl. spec theory,
          specialization footprint, locked occupancy)
       8. H12 faculty consecutive-teaching check via the shared
          schedule_rules.check_faculty_consecutive
       9. enrich occupancy failures with conflicting_class_id /
          conflicting_assignment_id
  -> manual_edits.move_scheduled_class
       validate -> update day/start/room -> flush -> re-verify against a
       freshly rebuilt snapshot -> commit (any failure -> rollback)
```

No second validation system: steps 5–7 reuse `schedule_validator` and
`schedule_rules`, the same rules the scheduler encodes and the audit
re-checks. `MoveValidationResult(ok, failures, candidate, current, noop)`
is shared verbatim between dry-run validation and the mutation.

## Atomicity

Validation precedes all persistence. The update, flush, re-verification,
and commit happen inside one transaction; any failure rolls back, leaving
the original row (and every other row) exactly unchanged — verified in
tests by full row-snapshot comparison plus database SHA equality.

## Locked-block behavior

Locked rows (`is_locked` true **or** `locked_block_id` set, covering both
flag forms) are immovable: `LOCKED_BLOCK` with
`{scheduled_class_id, locked_block_id, attempted_change, current}` and no
write. Moves targeting locked room/faculty/section occupancy are rejected
with the usual `ROOM_CONFLICT` / `FACULTY_CONFLICT` / `SECTION_CONFLICT`
(including `conflicting_class_id`) through the shared snapshot, so Phase
6E semantics are never bypassed.

## Specialization behavior

Normal classes cannot move into a synchronized specialization footprint
(`SPECIALIZATION_OVERLAP`, with the blocking spec class identified).
Specialization classes cannot be moved independently: an independent move
would desynchronize the cohort, so it is rejected with
`SPECIALIZATION_SYNC` before any occupancy check. Cohort-wide movement is
out of scope. Normal moves leave spec classes and slots untouched
(verified in tests).

## HN1 behavior

Moves use the shared `check_max_two_theory` over normal + (deduped, once
per section) specialization theory occupancy: creating a three-theory
window is rejected (`MAX_TWO_THEORY`), removing one is accepted, break
segment boundaries are respected, and practicals contribute 0.

## API endpoints

Session-cookie auth, POST mutations per project convention.

* `POST /api/schedule/classes/<id>/validate-move` — dry run, no mutation.
  `{day, start_period, room_id}` → 200 `{ok, noop, candidate, current}` or
  422 with the structured `{code, details, failures}` envelope.
* `POST /api/schedule/classes/<id>/move` — atomic move. 200
  `{ok, noop, scheduled_class}` (`id, assignment_id, day, start_period,
  length, room/room_id, subject, faculty, section/lab_group/
  specialization, run_id, lock/slot links`) or 422/404 structured errors.

## Error codes

Most-specific rule code wins: `UNKNOWN_DAY`, `PERIOD_OUT_OF_RANGE`,
`BLOCK_GEOMETRY`, `BREAK_SPAN`, `UNKNOWN_ROOM`, `ROOM_CONFLICT`,
`ROOM_CAPACITY`, `ROOM_TYPE_MISMATCH`, `ROOM_EQUIPMENT`,
`FACULTY_CONFLICT`, `FACULTY_UNAVAILABLE`, `FACULTY_CONSECUTIVE`,
`SECTION_CONFLICT` (surfaces validator `GROUP_CONFLICT`, same as the
locked-block API), `SECTION_HIERARCHY_CONFLICT`, `MAX_TWO_THEORY`,
`LOCKED_BLOCK`, `SPECIALIZATION_SYNC`, `SPECIALIZATION_OVERLAP`, plus
`MANUAL_EDIT_INVALID` for malformed requests/missing rows. Occupancy
failures carry `conflicting_class_id` / `conflicting_assignment_id`,
`scheduled_class_id`, day/period/room context. 404 only for a missing
scheduled class; Python tracebacks are never exposed.

## Limitations

No editor UI, no faculty reassignment or swapping, no cohort-wide
specialization moves, no preferred-room optimization, no soft
preferences, no audit log (the audit validates the resulting schedule
unchanged).
