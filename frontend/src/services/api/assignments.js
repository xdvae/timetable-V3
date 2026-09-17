import { api } from "./client.js";

/**
 * GET /api/assignments → {
 *   assignments: [{ id, faculty_id, faculty_name, subject_id, subject_name,
 *     session_type, section_id, lab_group_id, group, periods_per_week,
 *     block_length }],
 *   faculty: [...], subjects: [...], sections: [...], lab_groups: [...],
 *   faculty_load: {...}, subjects_json: {...}
 * } (live shape). The create form also consumes the option lists,
 * faculty loads, and subjects_json defaults returned alongside.
 */
export function getAssignments() {
  return api.get("/api/assignments").then((payload) => ({
    assignments: payload.assignments ?? [],
    faculty: payload.faculty ?? [],
    subjects: payload.subjects ?? [],
    sections: payload.sections ?? [],
    labGroups: payload.lab_groups ?? [],
    facultyLoad: payload.faculty_load ?? {},
    subjectDefaults: payload.subjects_json ?? {},
  }));
}

/**
 * POST /api/assignments → 201 { ok, message, category, assignment, faculty_load }.
 * Theory requires section_id; practical requires lab_group_id. The backend
 * enforces the block-length rule and reports load (category is "warning"
 * when the faculty max is exceeded). 422/404 carry the backend message.
 */
export function createAssignment(payload) {
  return api.post("/api/assignments", payload);
}

/** POST /api/assignments/<aid>/delete → 200 { ok, message }. 404 when missing. */
export function deleteAssignment(id) {
  return api.post(`/api/assignments/${id}/delete`);
}
