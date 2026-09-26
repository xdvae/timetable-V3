import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  emitInvalidation,
  resetInvalidationForTests,
  subscribeInvalidation,
} from "@/lib/invalidation.js";
import { INVALIDATION_DOMAINS } from "@/lib/invalidation.js";

beforeEach(() => {
  resetInvalidationForTests();
});

describe("invalidation bus (Phase 6P.2)", () => {
  it("notifies a subscriber of an emitted domain with the domain list", () => {
    const callback = vi.fn();
    subscribeInvalidation(["schedule"], callback);
    emitInvalidation(["schedule"]);
    expect(callback).toHaveBeenCalledTimes(1);
    expect(callback).toHaveBeenCalledWith(["schedule"]);
  });

  it("notifies multiple subscribers of the same domain", () => {
    const first = vi.fn();
    const second = vi.fn();
    const third = vi.fn();
    subscribeInvalidation(["overview"], first);
    subscribeInvalidation(["overview"], second);
    subscribeInvalidation(["overview"], third);
    emitInvalidation(["overview"]);
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
    expect(third).toHaveBeenCalledTimes(1);
  });

  it("notifies a multi-domain subscriber exactly once per emission", () => {
    const callback = vi.fn();
    subscribeInvalidation(["schedule", "overview", "dashboard"], callback);
    emitInvalidation(["schedule", "overview"]);
    expect(callback).toHaveBeenCalledTimes(1);
    expect(callback).toHaveBeenCalledWith(["schedule", "overview"]);
  });

  it("supports multiple domains in one emission across subscribers", () => {
    const schedule = vi.fn();
    const overview = vi.fn();
    subscribeInvalidation(["schedule"], schedule);
    subscribeInvalidation(["overview"], overview);
    emitInvalidation(["schedule", "overview"]);
    expect(schedule).toHaveBeenCalledTimes(1);
    expect(overview).toHaveBeenCalledTimes(1);
  });

  it("ignores subscribers of unrelated domains", () => {
    const callback = vi.fn();
    subscribeInvalidation(["preferences"], callback);
    emitInvalidation(["schedule"]);
    expect(callback).not.toHaveBeenCalled();
  });

  it("stops notifying after unsubscribe", () => {
    const callback = vi.fn();
    const unsubscribe = subscribeInvalidation(["schedule"], callback);
    emitInvalidation(["schedule"]);
    expect(callback).toHaveBeenCalledTimes(1);
    unsubscribe();
    emitInvalidation(["schedule"]);
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("unsubscribe is idempotent and safe to repeat", () => {
    const callback = vi.fn();
    const unsubscribe = subscribeInvalidation(["schedule"], callback);
    unsubscribe();
    expect(() => unsubscribe()).not.toThrow();
    emitInvalidation(["schedule"]);
    expect(callback).not.toHaveBeenCalled();
  });

  it("does not duplicate a callback subscribed twice to the same domain", () => {
    const callback = vi.fn();
    subscribeInvalidation(["schedule"], callback);
    subscribeInvalidation(["schedule"], callback);
    emitInvalidation(["schedule"]);
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("empty emissions notify nobody and never throw", () => {
    const callback = vi.fn();
    subscribeInvalidation(["schedule"], callback);
    expect(() => emitInvalidation([])).not.toThrow();
    expect(() => emitInvalidation()).not.toThrow();
    expect(() => emitInvalidation(null)).not.toThrow();
    expect(callback).not.toHaveBeenCalled();
  });

  it("subscribe with empty domains returns a harmless no-op", () => {
    const callback = vi.fn();
    const unsubscribe = subscribeInvalidation([], callback);
    expect(() => unsubscribe()).not.toThrow();
    emitInvalidation(["schedule"]);
    expect(callback).not.toHaveBeenCalled();
  });

  it("subscribe with a non-function callback returns a harmless no-op", () => {
    expect(() => subscribeInvalidation(["schedule"], null)).not.toThrow();
    const unsubscribe = subscribeInvalidation(["schedule"], "nope");
    expect(() => unsubscribe()).not.toThrow();
    expect(() => emitInvalidation(["schedule"])).not.toThrow();
  });

  it("deduplicates repeated domains inside one emission", () => {
    const callback = vi.fn();
    subscribeInvalidation(["schedule"], callback);
    emitInvalidation(["schedule", "schedule", "schedule"]);
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("cleanup removes empty domain sets so later subscribers start fresh", () => {
    const first = vi.fn();
    const unsubscribe = subscribeInvalidation(["schedule"], first);
    unsubscribe();
    const second = vi.fn();
    subscribeInvalidation(["schedule"], second);
    emitInvalidation(["schedule"]);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});

describe("INVALIDATION_DOMAINS", () => {
  it("is a frozen list containing every domain the app subscribes or emits", () => {
    expect(Object.isFrozen(INVALIDATION_DOMAINS)).toBe(true);
    expect([...INVALIDATION_DOMAINS].sort()).toEqual(
      [
        "assignments",
        "config",
        "dashboard",
        "enrollments",
        "faculty",
        "lockedBlocks",
        "overview",
        "preferences",
        "programs",
        "rooms",
        "schedule",
        "sections",
        "specializations",
        "subjects",
      ].sort()
    );
  });
});
