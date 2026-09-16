import { api } from "./client.js";

/** GET /api/dashboard → { session_name, counts: {...} } (live shape). */
export function getDashboard() {
  return api.get("/api/dashboard");
}
