import { api } from "./client.js";

/**
 * GET /api/config → { id, session_name, max_section_size, max_lab_group_size,
 * working_days, periods, break_after_periods, max_consecutive_teaching,
 * days[], periods_list[] } (live shape).
 */
export function getConfig() {
  return api.get("/api/config");
}
