import { api } from "./client.js";

/**
 * Timetable reads. Lane layout, conflict handling, and scheduling all stay
 * server-side (export.build_lane_rows); React only presents what the API
 * returns.
 *
 * GET /api/timetable → { sections: [{ id, name }], faculty: [{ id, name }],
 *   rooms: [{ id, name }], has_schedule: bool }
 *
 * GET /api/timetable/<view>/<id> (view: section|faculty|room) → { title,
 *   view, obj_id, days[], periods[], extra|null,
 *   day_rows: [{ day, lanes: [[{ empty, colspan, class? }]] }] } where a
 *   non-empty cell's `class` is { assignment_id, subject, faculty, group,
 *   room, session_type, kind, css_class, start_period, length, day }.
 *   Unknown view/id → 404 JSON.
 *
 * GET /api/timetable/free[?day=] → { days[], periods[],
 *   faculty: [{ id, name }], selected_day, busy: [{ faculty_id, period,
 *   label }], break_after, has_schedule, warning? }
 */
export function getTimetableHome() {
  return api.get("/api/timetable");
}

export function getTimetableView(view, id) {
  return api.get(`/api/timetable/${view}/${id}`);
}

export function getFreeFaculty(day) {
  const query = day ? `?day=${encodeURIComponent(day)}` : "";
  return api.get(`/api/timetable/free${query}`);
}

/**
 * POST /api/schedule/run (no body) → 200 { ok, message, status,
 *   placements, run_id }. Invokes the existing OR-Tools scheduler with the
 *   same inputs as the Jinja route and REPLACES the stored schedule.
 * Failure (infeasible / nothing to schedule) → 422
 * { error: "Scheduling failed: …" }; the previous schedule is preserved.
 */
export function runScheduler() {
  return api.post("/api/schedule/run");
}

/**
 * Existing Jinja export endpoints (same-origin GETs, session cookie
 * applies — no new API involved). `fmt` is xlsx, csv, or html (print).
 */
export function exportUrl(view, id, fmt) {
  return `/export/${view}/${id}/${fmt}`;
}
