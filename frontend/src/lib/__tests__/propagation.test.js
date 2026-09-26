import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  resetInvalidationForTests,
  subscribeInvalidation,
} from "@/lib/invalidation.js";
import {
  ASSIGNMENT_WRITE_DOMAINS,
  CONFIG_DOMAINS,
  emitOnSuccess,
  ENROLLMENTS_DOMAINS,
  FACULTY_DOMAINS,
  GENERATION_DOMAINS,
  IMPORT_WORKLOAD_DOMAINS,
  LOCKED_BLOCK_DOMAINS,
  MEMBERSHIP_DOMAINS,
  MOVE_DOMAINS,
  PREFERENCE_DOMAINS,
  PREFERRED_ROOM_DOMAINS,
  PROGRAMS_DOMAINS,
  REASSIGN_DOMAINS,
  ROOMS_DOMAINS,
  SPECIALIZATION_DOMAINS,
  SUBJECTS_DOMAINS,
  SWAP_DOMAINS,
} from "@/lib/propagation.js";

beforeEach(() => {
  resetInvalidationForTests();
});

function emittedDomains(action) {
  const seen = [];
  subscribeInvalidation(
    [
      "schedule",
      "assignments",
      "faculty",
      "preferences",
      "sections",
      "enrollments",
      "specializations",
      "lockedBlocks",
      "rooms",
      "overview",
      "dashboard",
      "config",
      "programs",
      "subjects",
    ],
    (domains) => seen.push([...domains].sort())
  );
  action();
  return seen;
}

describe("mutation → domain matrix (Phase 6P.3)", () => {
  it("matches the code-confirmed 6P.1 matrix exactly", () => {
    expect([...MOVE_DOMAINS]).toEqual(["schedule"]);
    expect([...REASSIGN_DOMAINS]).toEqual(["assignments", "schedule", "faculty", "overview"]);
    expect([...SWAP_DOMAINS]).toEqual(["assignments", "schedule", "faculty", "overview"]);
    expect([...ASSIGNMENT_WRITE_DOMAINS]).toEqual(["assignments", "overview"]);
    expect([...PREFERENCE_DOMAINS]).toEqual(["preferences"]);
    expect([...PREFERRED_ROOM_DOMAINS]).toEqual(["sections"]);
    expect([...SPECIALIZATION_DOMAINS]).toEqual(["specializations"]);
    expect([...MEMBERSHIP_DOMAINS]).toEqual(["specializations", "sections"]);
    expect([...LOCKED_BLOCK_DOMAINS]).toEqual(["lockedBlocks", "schedule", "assignments"]);
    expect([...GENERATION_DOMAINS]).toEqual([
      "schedule",
      "overview",
      "dashboard",
      "assignments",
      "lockedBlocks",
      "specializations",
    ]);
    expect([...ROOMS_DOMAINS]).toEqual(["rooms"]);
    expect([...FACULTY_DOMAINS]).toEqual(["faculty"]);
    expect([...PROGRAMS_DOMAINS]).toEqual(["programs"]);
    expect([...SUBJECTS_DOMAINS]).toEqual(["subjects"]);
    expect([...ENROLLMENTS_DOMAINS]).toEqual(["enrollments"]);
    expect([...CONFIG_DOMAINS]).toEqual(["config"]);
    expect([...IMPORT_WORKLOAD_DOMAINS]).toEqual([
      "programs",
      "enrollments",
      "sections",
      "subjects",
      "faculty",
      "assignments",
      "overview",
    ]);
  });

  it("successful authoritative mutation emits its domains once", () => {
    const calls = emittedDomains(() => {
      const emitted = emitOnSuccess({ ok: true, data: { ok: true } }, MOVE_DOMAINS);
      expect(emitted).toBe(true);
    });
    expect(calls).toEqual([[ "schedule" ]]);
  });

  it("successful mutation without a data envelope still emits", () => {
    const calls = emittedDomains(() => {
      expect(emitOnSuccess({ ok: true }, GENERATION_DOMAINS)).toBe(true);
    });
    expect(calls).toEqual([
      ["assignments", "dashboard", "lockedBlocks", "overview", "schedule", "specializations"],
    ]);
  });

  it("true noop (validated, zero writes) emits nothing", () => {
    const calls = emittedDomains(() => {
      expect(emitOnSuccess({ ok: true, data: { ok: true, noop: true } }, MOVE_DOMAINS)).toBe(false);
      expect(emitOnSuccess({ ok: true, data: { ok: true, noop: true } }, REASSIGN_DOMAINS)).toBe(false);
      expect(emitOnSuccess({ ok: true, data: { ok: true, noop: true } }, SWAP_DOMAINS)).toBe(false);
    });
    expect(calls).toEqual([]);
  });

  it("failed mutation emits nothing", () => {
    const callback = vi.fn();
    subscribeInvalidation(["schedule", "assignments"], callback);
    expect(emitOnSuccess({ ok: false, error: new Error("ROOM_CONFLICT") }, MOVE_DOMAINS)).toBe(false);
    expect(emitOnSuccess({ ok: false, error: new Error("nope") }, GENERATION_DOMAINS)).toBe(false);
    expect(callback).not.toHaveBeenCalled();
  });

  it("generation failure emits nothing", () => {
    const calls = emittedDomains(() => {
      expect(emitOnSuccess({ ok: false, error: { message: "Scheduling failed" } }, GENERATION_DOMAINS)).toBe(
        false
      );
    });
    expect(calls).toEqual([]);
  });

  it("never throws on nullish or malformed results", () => {
    expect(emitOnSuccess(null, MOVE_DOMAINS)).toBe(false);
    expect(emitOnSuccess(undefined, MOVE_DOMAINS)).toBe(false);
    expect(emitOnSuccess({}, MOVE_DOMAINS)).toBe(false);
    expect(emitOnSuccess({ ok: true, data: { noop: false } }, [])).toBe(true);
  });

  it("preference writes never include the schedule domain", () => {
    expect(PREFERENCE_DOMAINS).not.toContain("schedule");
    expect(PREFERRED_ROOM_DOMAINS).not.toContain("schedule");
  });

  it("membership writes never include the schedule domain", () => {
    expect(MEMBERSHIP_DOMAINS).not.toContain("schedule");
    expect(SPECIALIZATION_DOMAINS).not.toContain("schedule");
  });

  it("generation emits every schedule-dependent domain and no config-only domain", () => {
    for (const domain of ["schedule", "overview", "dashboard", "assignments", "lockedBlocks", "specializations"]) {
      expect(GENERATION_DOMAINS).toContain(domain);
    }
    for (const domain of ["preferences", "sections", "rooms", "faculty", "config"]) {
      expect(GENERATION_DOMAINS).not.toContain(domain);
    }
  });
});
