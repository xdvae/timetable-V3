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
