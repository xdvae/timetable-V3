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

/**
 * POST /api/assignments/<aid>/validate-reassign { faculty_id } →
 * 200 { ok, noop, dry_run, assignment_id, current_faculty_id,
 *   new_faculty_id, scheduled_class_ids, warning }. Dry-run only: the
 * backend validates every scheduled class of the assignment against the
 * target faculty without mutating anything. 422 carries the structured
 * { error, code, details, failures } envelope; 404 when the assignment
 * or faculty is missing.
 */
export function validateReassignFaculty(assignmentId, facultyId) {
  return api.post(`/api/assignments/${assignmentId}/validate-reassign`, {
    faculty_id: facultyId,
  });
}

/**
 * POST /api/assignments/<aid>/reassign { faculty_id } →
 * 200 { ok, noop, message, assignment, result }. Atomically changes the
 * assignment's faculty; existing timetable placements stay where they
 * are (no regeneration). Same error envelope as the dry-run.
 */
export function reassignFaculty(assignmentId, facultyId) {
  return api.post(`/api/assignments/${assignmentId}/reassign`, {
    faculty_id: facultyId,
  });
}

/**
 * POST /api/assignments/validate-swap { assignment_a_id, assignment_b_id } →
 * 200 { ok, noop, dry_run, assignment_a_id, assignment_b_id, faculty_a_id,
 *   faculty_b_id, scheduled_class_ids_a/b, warnings }. Dry-run only.
 * Failures carry swap_side ("A"/"B") where they belong to one side.
 */
export function validateFacultySwap(assignmentAId, assignmentBId) {
  return api.post("/api/assignments/validate-swap", {
    assignment_a_id: assignmentAId,
    assignment_b_id: assignmentBId,
  });
}

/**
 * POST /api/assignments/swap { assignment_a_id, assignment_b_id } →
 * 200 { ok, noop, message, assignments: [a, b], result }. Atomically
 * exchanges both assignments' faculties (never half-swapped); placements
 * stay where they are. Same structured error envelope as the dry-run.
 */
export function swapFaculty(assignmentAId, assignmentBId) {
  return api.post("/api/assignments/swap", {
    assignment_a_id: assignmentAId,
    assignment_b_id: assignmentBId,
  });
}
