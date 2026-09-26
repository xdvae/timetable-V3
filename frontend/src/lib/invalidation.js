/**
 * Phase 6P — lightweight domain invalidation bus.
 *
 * UniSchedule has no API response cache (see backend/PHASE_6P1_PROPAGATION_AUDIT.md):
 * every page owns independent GET-on-mount fetches via `useApi`, and every
 * mutation refetches only its own page via `retry()`. This module closes the
 * cross-page gap with the smallest possible mechanism: successful
 * authoritative mutations emit logical resource-domain names, and mounted
 * `useApi` consumers subscribed to those domains re-fetch through their
 * existing `retry()` path.
 *
 * Design constraints (deliberate):
 * - No page knowledge, no endpoint knowledge, no network calls, no backend
 *   dependency, no stored responses. The bus carries domain names only.
 * - Synchronous dispatch. A subscriber's `retry()` runs inside the same
 *   synchronous tick as the emitter's own local `retry()`, so React batches
 *   them into a single render and a single GET (see `useApi` docs).
 * - One callback invocation per emit per subscriber, even when the
 *   subscriber matches several emitted domains (deduplicated via a Set).
 * - Only successful authoritative mutations may emit. Validation-only
 *   endpoints and failed/rolled-back mutations must never call `emit`.
 *
 * Usage:
 *   import { emitInvalidation, subscribeInvalidation } from "@/lib/invalidation.js";
 *
 *   // mutation success path (never on failure / validation / noop):
 *   emitInvalidation(["schedule"]);
 *
 *   // consumer (normally done inside `useApi`, not by hand):
 *   const unsubscribe = subscribeInvalidation(["schedule"], () => retry());
 *   unsubscribe(); // on unmount
 */

/**
 * Definitive logical resource domains (Phase 6P). Each domain maps to one or
 * more GET endpoints consumed by at least one page; see the final audit for
 * the full domain → endpoint → consumer matrix.
 */
export const INVALIDATION_DOMAINS = Object.freeze([
  "schedule", // GET /api/schedule/classes, /api/timetable*, /api/timetable/free
  "assignments", // GET /api/assignments
  "faculty", // GET /api/faculty, /api/faculty/:fid/availability
  "preferences", // GET /api/faculty/:fid/preferences
  "sections", // GET /api/enrollments/:eid/sections
  "enrollments", // GET /api/enrollments
  "specializations", // GET /api/specializations[/:sid]
  "lockedBlocks", // GET /api/locked-blocks
  "rooms", // GET /api/rooms
  "overview", // GET /api/overview
  "dashboard", // GET /api/dashboard
  "config", // GET /api/config
  "programs", // GET /api/programs
  "subjects", // GET /api/subjects
]);

/** domain -> Set<callback>. Module-level: one bus per SPA session. */
const subscribers = new Map();

function normalizeDomains(domains) {
  if (!Array.isArray(domains)) return [];
  const seen = new Set();
  for (const domain of domains) {
    if (typeof domain !== "string" || domain === "") continue;
    if (!seen.has(domain)) seen.add(domain);
  }
  return [...seen];
}

/**
 * Subscribe `callback` to one or more domains. Returns an `unsubscribe`
 * function that is idempotent and safe to call after unmount.
 * An empty/irrelevant domain list subscribes to nothing and returns a no-op.
 */
export function subscribeInvalidation(domains, callback) {
  const list = normalizeDomains(domains);
  if (list.length === 0 || typeof callback !== "function") {
    return () => {};
  }
  for (const domain of list) {
    let set = subscribers.get(domain);
    if (!set) {
      set = new Set();
      subscribers.set(domain, set);
    }
    set.add(callback);
  }
  let active = true;
  return function unsubscribe() {
    if (!active) return;
    active = false;
    for (const domain of list) {
      const set = subscribers.get(domain);
      if (!set) continue;
      set.delete(callback);
      if (set.size === 0) subscribers.delete(domain);
    }
  };
}

/**
 * Notify mounted subscribers of one or more changed domains. Each matching
 * subscriber callback runs exactly once per call (synchronously), receiving
 * the normalized emitted domain list. Unknown domain names are delivered
 * verbatim to whoever subscribed to them; empty emissions notify nobody.
 */
export function emitInvalidation(domains) {
  const list = normalizeDomains(domains);
  if (list.length === 0) return;
  const toNotify = new Set();
  for (const domain of list) {
    const set = subscribers.get(domain);
    if (!set) continue;
    for (const callback of set) toNotify.add(callback);
  }
  const frozen = Object.freeze([...list]);
  for (const callback of toNotify) callback(frozen);
}

/**
 * Test-only helper: drop every subscription. Never used by application code;
 * lets propagation tests start each case from a clean bus.
 */
export function resetInvalidationForTests() {
  subscribers.clear();
}
