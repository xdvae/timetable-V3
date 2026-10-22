import { api } from "./client.js";

/**
 * Locked / interdepartment block administration clients (Phase 6M).
 *
 * Thin wrappers over the Phase 6E backend, which stays authoritative for
 * every rule (room/faculty/section conflicts, availability, geometry, HN1,
 * hierarchy, capacity, specialization restrictions). These functions only
 * transport the backend's own payloads — including the structured
 * `{ error, code, details, failures }` envelope on 422/404s, preserved
 * verbatim on ApiError.payload for FailureList rendering.
 *
 * Supported operations mirror the backend exactly: list, create, delete.
 * The backend exposes no update and no dry-run/validate endpoint, so this
 * module offers neither — creation itself validates authoritatively.
 *
 * None of these endpoints regenerates the timetable; configuration
 * changes apply to future schedule generations only.
 */

/**
 * GET /api/locked-blocks → { locked_blocks: [{ id, kind, assignment_id,
 *   subject_id, faculty_id, section_id, lab_group_id, day, start_period,
 *   length, room_id, room_locked, department, is_external, note,
 *   scheduled_class_id }] }.
 */
export function getLockedBlocks() {
  return api.get("/api/locked-blocks").then((payload) => ({
    lockedBlocks: payload.locked_blocks ?? [],
  }));
}

/**
 * POST /api/locked-blocks { assignment_id, day, start_period, length,
 *   room_id, department?, note? } → 201 { ok, message, locked_block,
 *   scheduled_class }. Atomically persists the LockedBlock plus its
 *   ScheduledClass (is_locked). 422 carries structured failures
 *   (ROOM_CONFLICT, FACULTY_CONFLICT, SECTION_CONFLICT, FACULTY_UNAVAILABLE,
 *   SPECIALIZATION_OVERLAP, geometry/HN1/room-compatibility codes…);
 *   missing/invalid scalars arrive as field_errors.
 */
export function createLockedBlock(payload) {
  return api.post("/api/locked-blocks", payload);
}

/**
 * POST /api/locked-blocks/<id>/delete → 200 { ok, message }.
 * Atomically removes the LockedBlock and its ScheduledClass rows (frees
 * resources; never regenerates the timetable). 404 when missing.
 */
export function deleteLockedBlock(id) {
  return api.post(`/api/locked-blocks/${id}/delete`);
}
