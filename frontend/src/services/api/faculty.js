import { api } from "./client.js";

/**
 * GET /api/faculty → { faculty: [{ id, name, department|null, faculty_type,
 * weekly_load, weekly_max_hours }] } (live shape).
 */
export function getFaculty() {
  return api.get("/api/faculty").then((payload) => payload.faculty ?? []);
}

/**
 * POST /api/faculty → 201 { ok, message, faculty }.
 * Blank faculty_type means "regular"; blank weekly_max_hours means 24.
 */
export function createFaculty(payload) {
  return api.post("/api/faculty", payload);
}

/** POST /api/faculty/<fid>/delete → 200 { ok, message }. 404 when missing. */
export function deleteFaculty(id) {
  return api.post(`/api/faculty/${id}/delete`);
}

/**
 * GET /api/faculty/<fid>/availability → { faculty: { id, name },
 *   days[], periods[], unavailable: ["Day:idx", …] } (live shape).
 */
export function getFacultyAvailability(fid) {
  return api.get(`/api/faculty/${fid}/availability`);
}

/**
 * POST /api/faculty/<fid>/availability { unavailable: […] } →
 * 200 { ok, message, unavailable }. Saves the whole matrix at once,
 * mirroring the Jinja form. 404 when the faculty is missing.
 */
export function saveFacultyAvailability(fid, unavailable) {
  return api.post(`/api/faculty/${fid}/availability`, { unavailable });
}

/**
 * GET /api/faculty/<fid>/preferences → { faculty, days[], periods[],
 *   num_periods, preferences: [{ id, faculty_id, kind, days[], start_period,
 *   end_period, weight, is_hard, enabled }] } (live shape).
 */
export function getFacultyPreferences(fid) {
  return api.get(`/api/faculty/${fid}/preferences`);
}

/**
 * POST /api/faculty/<fid>/preferences { kind, days?, start_period?,
 * end_period?, weight?, enabled? } → 201 { ok, message, preference }.
 * Soft-only: is_hard=true is rejected; SUBJECT_AFFINITY is rejected as
 * unsupported. Never regenerates the timetable. 404 UNKNOWN_FACULTY
 * when missing; 422 carries field_errors for invalid input.
 */
export function createFacultyPreference(fid, payload) {
  return api.post(`/api/faculty/${fid}/preferences`, payload);
}

/**
 * POST /api/faculty/preferences/<pid> (partial fields) →
 * 200 { ok, message, preference }. Explicit null clears a period bound
 * (needed to change kinds). Never regenerates the timetable.
 * 404 UNKNOWN_PREFERENCE when missing.
 */
export function updateFacultyPreference(preferenceId, payload) {
  return api.post(`/api/faculty/preferences/${preferenceId}`, payload);
}

/** POST /api/faculty/preferences/<pid>/delete → 200 { ok, message }. */
export function deleteFacultyPreference(preferenceId) {
  return api.post(`/api/faculty/preferences/${preferenceId}/delete`);
}
