import { api } from "./client.js";

/**
 * GET /api/enrollments → {
 *   enrollments: [{ id, program_id, program_name, year_label, total_students }],
 *   programs: [{ id, name }]
 * } (live shape).
 */
export function getEnrollments() {
  return api.get("/api/enrollments").then((payload) => ({
    enrollments: payload.enrollments ?? [],
    programs: payload.programs ?? [],
  }));
}

/**
 * GET /api/enrollments/<eid>/sections → {
 *   enrollment: { id, program_name, year_label, total_students },
 *   sections: [{ id, name, student_count,
 *     lab_groups: [{ id, name, student_count }] }]
 * } (live shape).
 */
export function getEnrollmentSections(eid) {
  return api.get(`/api/enrollments/${eid}/sections`);
}

/**
 * POST /api/enrollments → 201 { ok, message, enrollment, sections[] }.
 * Sections + lab groups are auto-generated server-side.
 */
export function createEnrollment(payload) {
  return api.post("/api/enrollments", payload);
}

/**
 * POST /api/enrollments/<eid>/delete → 200 { ok, message }.
 * Backend message confirms sections/lab groups go with it. 404 when missing.
 */
export function deleteEnrollment(id) {
  return api.post(`/api/enrollments/${id}/delete`);
}
