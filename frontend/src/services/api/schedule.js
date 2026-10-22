import { api } from "./client.js";

/**
 * Interactive timetable editor reads + manual-move clients (Phase 6O).
 *
 * The backend stays the sole authority for whether a move is valid: these
 * functions only transport its payloads — including the structured
 * `{ error, code, details, failures }` envelope on 422/404s, preserved
 * verbatim on ApiError.payload for FailureList rendering.
 *
 * None of these endpoints regenerates the timetable or invokes the
 * CP-SAT scheduler; moves relocate exactly one ScheduledClass.
 */

/**
 * GET /api/schedule/classes → { classes: [{ id, assignment_id, day,
 *   start_period, length, room_id, room, subject, subject_id, faculty,
 *   faculty_id, session_type, section_id, section, lab_group_id,
 *   lab_group, specialization_id, specialization, run_id, is_locked,
 *   slot_id, locked_block_id }], days[], periods[], break_after,
 *   has_schedule }.
 */
export function getScheduledClasses() {
  return api.get("/api/schedule/classes");
}

/**
 * POST /api/schedule/classes/<id>/validate-move { day, start_period,
 *   room_id } → 200 { ok, noop, message, candidate, current }. Dry-run
 *   only: nothing is mutated. 422 carries structured failures;
 *   404 when the class does not exist.
 */
export function validateMove(id, { day, start_period, room_id }) {
  return api.post(`/api/schedule/classes/${id}/validate-move`, {
    day,
    start_period,
    room_id,
  });
}

/**
 * POST /api/schedule/classes/<id>/move { day, start_period, room_id } →
 * 200 { ok, noop, message, scheduled_class }. Atomically relocates one
 * class; only day/start/room may change (assignment, length, run_id,
 * lock, and slot linkage are preserved server-side). Same error
 * envelope as the dry-run. Call only with the exact payload that was
 * validated.
 */
export function moveScheduledClass(id, { day, start_period, room_id }) {
  return api.post(`/api/schedule/classes/${id}/move`, {
    day,
    start_period,
    room_id,
  });
}
