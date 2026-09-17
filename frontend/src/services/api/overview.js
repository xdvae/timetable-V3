import { api } from "./client.js";

/**
 * GET /api/overview → {
 *   enrollments: [{ id, program_name, year_label, total_students,
 *     sections: [{ id, name, student_count,
 *       lab_groups: [{ id, name, student_count }] }] }],
 *   faculty: [{ id, name, faculty_type, weekly_max_hours, weekly_load,
 *     assignments: [{ id, subject_name, group, session_type,
 *       periods_per_week }] }]
 * } (live shape). Weekly loads are computed server-side; the page
 * renders `weekly_load` as-is and never re-derives it.
 */
export function getOverview() {
  return api.get("/api/overview").then((payload) => ({
    enrollments: payload.enrollments ?? [],
    faculty: payload.faculty ?? [],
  }));
}
