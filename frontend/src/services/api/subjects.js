import { api } from "./client.js";

/**
 * GET /api/subjects → {
 *   subjects: [{ id, code, name, enrollment_id, program_name, year_label,
 *     credits, theory_hours_per_week, practical_hours_per_week,
 *     practical_block_length }],
 *   enrollments: [{ id, program_name, year_label }]
 * } (live shape).
 */
export function getSubjects() {
  return api.get("/api/subjects").then((payload) => ({
    subjects: payload.subjects ?? [],
    enrollments: payload.enrollments ?? [],
  }));
}

/**
 * POST /api/subjects → 201 { ok, message, subject }.
 * Blank credits/theory/practical mean None; blank block length means 2.
 */
export function createSubject(payload) {
  return api.post("/api/subjects", payload);
}

/** POST /api/subjects/<sid>/delete → 200 { ok, message }. 404 when missing. */
export function deleteSubject(id) {
  return api.post(`/api/subjects/${id}/delete`);
}
