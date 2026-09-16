import { api } from "./client.js";

/**
 * GET /api/faculty → { faculty: [{ id, name, department|null, faculty_type,
 * weekly_load, weekly_max_hours }] } (live shape).
 */
export function getFaculty() {
  return api.get("/api/faculty").then((payload) => payload.faculty ?? []);
}
