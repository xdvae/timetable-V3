import { api } from "./client.js";

/**
 * Specialization administration clients (Phase 6K).
 *
 * Thin wrappers over the Phase 6F backend, which stays authoritative for
 * every rule (enrollment match, capacity, sync, overlap). These functions
 * only transport the backend's own payloads — including the structured
 * `{ error, code, details, failures }` envelope on 422/404s, preserved
 * verbatim on ApiError.payload for FailureList rendering.
 *
 * None of these endpoints regenerates the timetable; configuration
 * changes apply to future schedule generations only.
 */

/**
 * GET /api/specializations → { specializations: [...] }.
 * Each entry is the full payload: identity, memberships, slots,
 * scheduled_classes, and total_students.
 */
export function getSpecializations() {
  return api.get("/api/specializations").then((payload) => ({
    specializations: payload.specializations ?? [],
  }));
}

/**
 * GET /api/specializations/<sid> → { specialization }.
 * Authoritative single-spec read used after every mutation.
 */
export function getSpecialization(id) {
  return api.get(`/api/specializations/${id}`);
}

/**
 * POST /api/specializations → 201 { ok, message, specialization }.
 * Minimal working payload is { name, enrollment_id }; session_type /
 * block_length / periods_per_week default server-side (theory / 1 / 2).
 * 422 carries structured specialization failures; missing name is a
 * field error.
 */
export function createSpecialization(payload) {
  return api.post("/api/specializations", payload);
}

/**
 * POST /api/specializations/<sid>/delete → 200 { ok, message }.
 * Also removes the spec's memberships, slots, scheduled classes, and
 * specialization assignments. 404 when missing.
 */
export function deleteSpecialization(id) {
  return api.post(`/api/specializations/${id}/delete`);
}

/**
 * POST /api/specializations/<sid>/memberships { section_id, student_count }
 * → 201 { ok, message, membership, specialization }. Upsert: an existing
 * section row is updated in place. Enrollment/capacity/count rules are
 * enforced server-side with structured failures.
 */
export function saveMembership(specializationId, { sectionId, studentCount }) {
  return api.post(`/api/specializations/${specializationId}/memberships`, {
    section_id: sectionId,
    student_count: studentCount,
  });
}

/**
 * POST /api/specializations/<sid>/memberships/delete { section_id }
 * → 200 { ok, message, specialization }. 404 when no such membership.
 */
export function deleteMembership(specializationId, sectionId) {
  return api.post(`/api/specializations/${specializationId}/memberships/delete`, {
    section_id: sectionId,
  });
}
