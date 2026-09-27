# Phase 6R — Timetable UX Audit (evidence-based, pre-implementation)

Date: 2026-09-26. Scope: frontend UX/usability only. Scheduler, 6P
invalidation, 6Q error contract, and DB integrity are preserved.

## Current timetable surfaces

- `/timetable` (`TimetablePage`, `TimetablePage.jsx`): scheduler
  generation panel (`POST /api/schedule/run` + confirm dialog), editor /
  who's-free links, by-section / by-faculty / by-room pickers. Reads
  `GET /api/timetable`, subscribes `["schedule"]`. Sound.
- `/timetable/:view/:id` (`TimetableViewPage`): day x period lane grid
  (`TimetableGrid` + `TimetableClassBlock` + `TimetableLegend`). Reads
  `GET /api/timetable/<view>/<id>`, subscribes `["schedule"]`. Uses
  `PageLoading` / `QueryError` / `EmptyState`. Lane layout server-side.
- `/timetable/editor` (`TimetableEditorPage.jsx`): day x period editor
  grid (period rows, day columns), client-side group + faculty filters,
  `MoveDialog` (validate-before-apply, footprint preview, snapshot
  payload, no optimistic mutation, refetch on success/stale) and
  details-only `DetailsDialog` for locked/spec classes. Bulk read
  `GET /api/schedule/classes` + `GET /api/rooms`, subscribes
  `["schedule", "rooms"]`. Emits `MOVE_DOMAINS` on successful apply
  only. Sound; the strongest surface.
- `/timetable/free` (`FreeFacultyPage.jsx`): day tabs via URL param,
  faculty x period availability table. Reads `GET /api/timetable/free`,
  subscribes `["schedule"]`. Sound.
- `/timetable/locked-blocks`: untouched by 6R.

## Current navigation / filters / states

- Entry points: sidebar Timetable group + home-page cards. Breadcrumbs
  on all views. Export (xlsx/csv/html) actions on the read-only view.
- Filters: editor has section/group + faculty view filters (display-only,
  client-side). Read-only view has none. Free-faculty has day tabs.
- Loading/empty/error: `PageLoading`, `QueryError` (normalized), and
  `EmptyState` everywhere. Failure rendering via `FailureList` /
  `MutationError` + `normalizeFailure()` / `FAILURE_LABELS`. Sound.
- Responsive: horizontal-scroll grids with a sticky first column; no
  vertical pinning. Sticky cells lack `z-index`, so scrolling lane cells
  can paint over the pinned column. Cards truncate long text without
  `title` fallbacks.
- Accessibility: editor buttons carry full `aria-label`s, dialogs have
  title/description, validation region is `aria-live`. Read-only blocks
  are `role="img"` with labels (fine). State is never color-only in the
  editor; the read-only view cannot show Fixed/Spec state at all (the
  lane-cell payload omits it).

## Confirmed UX problems (worth fixing in 6R)

1. Read-only timetable cards cannot answer "fixed?", "specialization?",
   or "how long?" — `_cell_json` (`api_routes.py`) omits lock/spec
   linkage (length is present but unrendered). Requires a small
   additive read-only backend extension; nothing else can fix it.
2. Read-only view has no context bar (view type, day x period counts,
   class counts, today) and no display filter; its empty state says
   "once scheduling ships" (stale — scheduling shipped) and offers no
   recovery path.
3. Sticky first-column cells have no `z-index`/shadow, so horizontal
   scroll overlaps them (read-only grid, editor grid, who's-free table).
4. Editor has no day filter and its no-match empty state has no
   clear-filters action; header shows no movable/fixed/spec counts.
5. Move dialog resets validation silently on destination change (no
   "validate again" cue) and gives no generic next-step hint under a
   failed validation.
6. Card text is small with no `title` fallbacks for truncated lines.
7. Locked-class details dialog has no path to the Fixed Blocks page.

## Deferred / non-problems

- Drag-and-drop: dialog workflow is authoritative and safe; skipped.
- Home-page search, faculty search on who's-free, room/subject/spec
  filters: datasets are small; existing pickers/tabs suffice.
- Current-period (clock) indication: cannot be derived reliably from
  config/time; only a static informational today highlight is added
  (computed once, no timer, no refetch).
- Dual Validate+Apply buttons: the current sequential
  Validate-then-Apply presentation already enforces "apply only when
  valid/current"; kept as-is.
- New invalidation domains, new endpoints for filters, second design
  system, animation/decoration: out of scope.
- `POST /api/schedule/run` auto-generation from empty states: never.

## Planned changes

- Backend (additive, read-only): `_cell_json` also returns `is_locked`,
  `locked_block_id`, `specialization_id`, `specialization`. Existing
  keys untouched. Covered by `test_timetable_cells_6r.py` (temp DB).
- Frontend: shared `timetable-helpers.js` pure helpers (today abbrev,
  day-row filter/summary, editor summary, lock/spec/movable predicates
  reused by the editor); card badges (duration/Fixed/Spec) + tooltips;
  extended legend; sticky-column `z-index` fixes; read-only context bar
  + client-side day filter + today highlight + actionable empty states
  + "Open in Editor" action; editor day filter + counts + clear-filters
  + revalidation cue + try-next hint + Fixed Blocks link; who's-free
  sticky first column.
- Tests: `timetable-6r.test.jsx` (helpers, card/legend rendering,
  malformed-failure safety); backend cell-payload test. No scheduler,
  propagation, or error-contract changes.

## Risk assessment

Low. All filters are client-side display-only; no mutation paths change;
no optimistic UI; validation-before-apply, snapshot payload, and
refetch semantics untouched; invalidation subscriptions unchanged
(`["schedule"]`, editor `["schedule", "rooms"]`); error rendering stays
on `normalizeFailure()`/`FailureList`. Real DBs untouched (temp DBs in
tests).
