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
