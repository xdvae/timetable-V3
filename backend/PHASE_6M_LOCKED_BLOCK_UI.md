# Phase 6M — Interdepartment / Locked Block Administration UI

Administrator-facing React workflow over the Phase 6E backend. No backend
changes: the API already exposed exactly list / create / delete, and this
phase adds no endpoints, no migrations, and no scheduler changes.

## Where it lives

- Page: `frontend/src/pages/LockedBlocks/LockedBlocksPage.jsx`
- Route: `/timetable/locked-blocks` (sibling of `/timetable`, `/timetable/free`)
- Nav: Timetable group → "Fixed Blocks"
- Service: `frontend/src/services/api/lockedBlocks.js`
  (`getLockedBlocks`, `createLockedBlock`, `deleteLockedBlock`)
- Flask SPA fallback (`backend/app.py::serve_react`) serves the route with
  no backend change.

## What a locked block is

A fixed scheduling **input**: one teaching assignment pinned to an exact
day + start period + length + room. The scheduler builds every future
timetable around it and never moves it. A normal scheduled class is movable
output. The page states this distinction in its header notice.

## Supported operations (backend contract, unchanged)

- LIST `GET /api/locked-blocks` → enriched client-side with assignment,
  room, and config names (blocks carry IDs only).
- CREATE `POST /api/locked-blocks` with `assignment_id, day, start_period,
  length, room_id` + optional `department, note`. Faculty/subject/
  section are derived from the assignment server-side; the form does not
  duplicate them. Creation is the authoritative validation (no dry-run
  endpoint exists; no duplicate POST is issued).
- DELETE `POST /api/locked-blocks/<id>/delete` via `DeleteConfirmDialog`.
  Removes the block and its locked `ScheduledClass` atomically.
- No UPDATE endpoint exists, so blocks cannot be edited in place: the UI
  offers delete + recreate (deletion only frees resources, so the
  round-trip is safe) and says so in the list panel.

## Generation behavior

Creating or deleting a block never calls `POST /api/schedule/run` (verified
by search). Every mutation refetches `GET /api/locked-blocks` before
rendering. Structured `{ error, code, details, failures }` errors render
through the existing `FailureList`/`MutationError` components; locked-block
codes (`BLOCK_GEOMETRY`, `ROOM_REQUIRED`, `ROOM_EQUIPMENT`,
`ASSIGNMENT_MISMATCH`, `KIND_NOT_ENABLED`, `UNKNOWN_KIND`,
`UNKNOWN_LOCKED_BLOCK`, `GROUP_CONFLICT`) were added to `FAILURE_LABELS`.

## Known limitations

- Standalone (assignment-less) blocks are not offered: Phase 6E requires
  `assignment_id` and a fixed room (`ROOM_REQUIRED`).
- Specialization assignments are rejected server-side
  (`SPECIALIZATION_OVERLAP`); the picker flags assignments without a
  section/lab group and leaves the backend authoritative.
