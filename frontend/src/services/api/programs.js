import { api } from "./client.js";

/**
 * GET /api/programs → { programs: [{ id, name, department }] } (live shape).
 */
export function getPrograms() {
  return api.get("/api/programs").then((payload) => payload.programs ?? []);
}

/** POST /api/programs → 201 { ok, message, program }. */
export function createProgram(payload) {
  return api.post("/api/programs", payload);
}

/** POST /api/programs/<pid>/delete → 200 { ok, message }. 404 when missing. */
export function deleteProgram(id) {
  return api.post(`/api/programs/${id}/delete`);
}
