import { api } from "./client.js";

/**
 * GET /api/programs → { programs: [{ id, name, department }] } (live shape).
 */
export function getPrograms() {
  return api.get("/api/programs").then((payload) => payload.programs ?? []);
}
