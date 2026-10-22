/**
 * Phase 6P — mutation → domain mapping (single source of truth).
 *
 * Each constant lists the resource domains a successful authoritative
 * mutation invalidates. Pages emit these constants (never string literals)
 * so the final audit matrix and the propagation tests assert against the
 * exact values the UI uses.
 *
 * Semantic rules (enforced by `emitOnSuccess`, tested in
 * `__tests__/propagation.test.js`):
 * - Only successful authoritative mutations emit (`result.ok === true`).
 * - A true no-op (`data.noop === true`) writes nothing and emits nothing.
 * - Failed/rolled-back mutations (`ok === false`) emit nothing.
 * - Validation-only endpoints (validate-move/reassign/swap) never call this
 *   module at all — their handlers contain no emit.
 * - Configuration-only writes (preferences, preferred room) emit their
 *   config domain only; the existing generated timetable is intentionally
 *   left alone and changes only at the next `POST /api/schedule/run`.
 */

import { emitInvalidation } from "./invalidation.js";

/** POST /api/schedule/classes/<id>/move — placement changed. */
export const MOVE_DOMAINS = Object.freeze(["schedule"]);

/** POST /api/assignments/<aid>/reassign — ownership + labels + loads. */
export const REASSIGN_DOMAINS = Object.freeze([
  "assignments",
  "schedule",
  "faculty",
  "overview",
]);

/** POST /api/assignments/swap — both ownerships + labels + loads. */
export const SWAP_DOMAINS = Object.freeze([
  "assignments",
  "schedule",
  "faculty",
  "overview",
]);

/** POST /api/assignments, POST /api/assignments/<aid>/delete. */
export const ASSIGNMENT_WRITE_DOMAINS = Object.freeze(["assignments", "overview"]);

/** Faculty preference create/update/delete — future generations only. */
export const PREFERENCE_DOMAINS = Object.freeze(["preferences"]);

/** POST /api/sections/<sid>/preferred-room — future generations only. */
export const PREFERRED_ROOM_DOMAINS = Object.freeze(["sections"]);

/** Specialization create/delete. */
export const SPECIALIZATION_DOMAINS = Object.freeze(["specializations"]);

/** Membership upsert/delete — membership + section context. */
export const MEMBERSHIP_DOMAINS = Object.freeze(["specializations", "sections"]);

/** Locked-block create/delete — record + paired schedule row + labels. */
export const LOCKED_BLOCK_DOMAINS = Object.freeze([
  "lockedBlocks",
  "schedule",
  "assignments",
]);

/** POST /api/schedule/run (success) — every schedule-dependent domain. */
export const GENERATION_DOMAINS = Object.freeze([
  "schedule",
  "overview",
  "dashboard",
  "assignments",
  "lockedBlocks",
  "specializations",
]);

/** Single-entity CRUD domains (own domain only). */
export const ROOMS_DOMAINS = Object.freeze(["rooms"]);
export const FACULTY_DOMAINS = Object.freeze(["faculty"]);
export const PROGRAMS_DOMAINS = Object.freeze(["programs"]);
export const SUBJECTS_DOMAINS = Object.freeze(["subjects"]);
export const ENROLLMENTS_DOMAINS = Object.freeze(["enrollments"]);
export const CONFIG_DOMAINS = Object.freeze(["config"]);

/**
 * Workload CSV import (POST /api/import/workload): creates programs,
 * enrollments, sections, subjects, faculty, and assignments in one commit.
 * Rooms CSV import reuses ROOMS_DOMAINS. Partial row warnings still commit
 * the valid rows, so any resolved import emits.
 */
export const IMPORT_WORKLOAD_DOMAINS = Object.freeze([
  "programs",
  "enrollments",
  "sections",
  "subjects",
  "faculty",
  "assignments",
  "overview",
]);

/**
 * Emit `domains` iff `result` is a successful, non-noop authoritative
 * mutation result (`{ ok: true, data }` from `useMutation().execute()`).
 * Returns true when an emission happened. Safe to call with any value.
 */
export function emitOnSuccess(result, domains) {
  if (!result || result.ok !== true) return false;
  if (result.data != null && result.data.noop === true) return false;
  emitInvalidation(domains);
  return true;
}
