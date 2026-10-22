import { api } from "./client.js";

/**
 * CSV imports. The browser sets the multipart boundary itself — never set
 * Content-Type manually for these calls (see client.js FormData handling).
 *
 * POST /api/import/rooms (field: `file`) →
 *   { ok, message, counts: { created, updated }, errors: ["Row N: …"] }
 * POST /api/import/workload (field: `file`) →
 *   { ok, message, counts: { programs?, enrollments?, … }, errors: [...] }
 * Missing file → 422 { error, field_errors: { file } }.
 * All parsing/validation stays server-side in csv_import.py.
 */
function uploadCsv(path, file) {
  const form = new FormData();
  form.append("file", file);
  return api.post(path, form);
}

export function importRoomsCsv(file) {
  return uploadCsv("/api/import/rooms", file);
}

export function importWorkloadCsv(file) {
  return uploadCsv("/api/import/workload", file);
}
