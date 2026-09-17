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
