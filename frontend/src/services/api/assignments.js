import { api } from "./client.js";

/**
 * GET /api/assignments → {
 *   assignments: [{ id, faculty_id, faculty_name, subject_id, subject_name,
 *     session_type, section_id, lab_group_id, group, periods_per_week,
 *     block_length }],
 *   faculty: [...], subjects: [...], sections: [...], lab_groups: [...],
 *   faculty_load: {...}, subjects_json: {...}
 * } (live shape). This read-only page consumes `assignments` only.
 */
export function getAssignments() {
  return api.get("/api/assignments").then((payload) => ({
    assignments: payload.assignments ?? [],
  }));
}
