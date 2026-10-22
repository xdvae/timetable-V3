import { describe, expect, it } from "vitest";

import { ApiError } from "@/services/api/client.js";
import {
  categoryFor,
  FAILURE_LABELS,
  getFailures,
  getFieldErrors,
  getImportRowErrors,
  hasFieldErrors,
  labelFor,
  normalizeFailure,
  normalizeFieldErrors,
  safeMessage,
} from "@/lib/failures.js";

function apiError(body, status) {
  return new ApiError("transport", {
    status,
    fieldErrors: body && typeof body === "object" ? body.field_errors ?? null : null,
    payload: body,
  });
}

describe("safeMessage (Phase 6Q)", () => {
  it("passes strings through trimmed", () => {
    expect(safeMessage("  hello  ")).toBe("hello");
  });

  it("never returns undefined/null/[object Object]", () => {
    for (const bad of [undefined, null, "", "   ", {}, { a: 1 }, [], [1]]) {
      const out = safeMessage(bad);
      expect(typeof out).toBe("string");
      expect(out.length).toBeGreaterThan(0);
      expect(out).not.toBe("[object Object]");
      expect(out).not.toBe("undefined");
      expect(out).not.toBe("null");
    }
  });

  it("prefers nested message objects over stringification", () => {
    expect(safeMessage({ message: "nested boom" })).toBe("nested boom");
  });

  it("coerces numbers and booleans", () => {
    expect(safeMessage(42)).toBe("42");
    expect(safeMessage(false)).toBe("false");
  });
});

describe("labelFor (Phase 6Q)", () => {
  it("labels every structured backend code", () => {
    const codes = [
      // schedule_rules / validator
      "ROOM_TYPE_MISMATCH", "ROOM_CAPACITY", "ROOM_EQUIPMENT", "BREAK_SPAN",
      "PERIOD_OUT_OF_RANGE", "UNKNOWN_DAY", "FACULTY_UNAVAILABLE",
      "BLOCK_LENGTH_INVALID", "FACULTY_CONSECUTIVE", "COVERAGE_MISMATCH",
      "MAX_TWO_THEORY", "ROOM_CONFLICT", "FACULTY_CONFLICT",
      "SECTION_CONFLICT", "SECTION_HIERARCHY_CONFLICT", "GROUP_CONFLICT",
      // specializations
      "SPECIALIZATION_SYNC", "SPECIALIZATION_OVERLAP", "SPECIALIZATION_CAPACITY",
      "SPECIALIZATION_ENROLLMENT", "SPECIALIZATION_MEMBERSHIP", "SPECIALIZATION_INVALID",
      // manual edits / reassign / swap / locked
      "MANUAL_EDIT_INVALID", "REASSIGNMENT_INVALID", "INVALID_SWAP",
      "LOCKED_BLOCK", "LOCKED_BLOCK_INVALID", "UNKNOWN_LOCKED_BLOCK",
      "UNKNOWN_ASSIGNMENT", "UNKNOWN_FACULTY", "UNKNOWN_ROOM", "UNKNOWN_SECTION",
      "UNKNOWN_PREFERENCE", "UNKNOWN_KIND", "KIND_NOT_ENABLED",
      "ASSIGNMENT_MISMATCH", "PERSISTENCE_FAILED", "ROOM_REQUIRED", "BLOCK_GEOMETRY",
      "SPECIALIZATION_SWAP",
      // preferences
      "PREFERENCE_INVALID", "PREF_INVALID_KIND", "PREF_INVALID_DAYS",
      "PREF_INVALID_PERIOD", "PREF_INVALID_WEIGHT", "PREF_HARD_UNSUPPORTED",
      // scheduler / auth / transport (6Q)
      "SCHEDULING_INFEASIBLE", "SCHEDULING_FAILED", "INVALID_CREDENTIALS",
      "AUTH_REQUIRED", "NOT_FOUND", "BAD_REQUEST", "METHOD_NOT_ALLOWED",
      "INTERNAL_ERROR",
    ];
    for (const code of codes) {
      expect(FAILURE_LABELS[code], code).toBeTruthy();
      expect(labelFor(code)).toBe(FAILURE_LABELS[code]);
    }
  });

  it("falls back safely for unknown future codes", () => {
    expect(labelFor("SOME_FUTURE_CODE")).toBe("SOME_FUTURE_CODE");
    expect(labelFor(null)).toBe("Validation failed");
    expect(labelFor("<script>")).toBe("Validation failed");
  });
});

describe("categoryFor (Phase 6Q)", () => {
  it("distinguishes network/auth/validation/scheduler/internal", () => {
    expect(categoryFor({ status: 0 })).toBe("network");
    expect(categoryFor({ status: 401 })).toBe("auth");
    expect(categoryFor({ status: 404 })).toBe("not_found");
    expect(categoryFor({ status: 422 })).toBe("validation");
    expect(categoryFor({ status: 422, code: "SCHEDULING_INFEASIBLE" })).toBe("scheduler");
    expect(categoryFor({ status: 422, code: "SCHEDULING_FAILED" })).toBe("scheduler");
    expect(categoryFor({ status: 500 })).toBe("internal");
  });
});

describe("normalizeFieldErrors / getFieldErrors (Phase 6Q)", () => {
  it("keeps string messages and drops objects", () => {
    expect(normalizeFieldErrors({ a: "bad", b: { x: 1 }, c: null, d: 5 })).toEqual({
      a: "bad",
      d: "5",
    });
  });

  it("reads legacy flat and nested envelopes", () => {
    expect(getFieldErrors(apiError({ error: "x", field_errors: { f: "req" } }, 422))).toEqual({
      f: "req",
    });
    expect(
      getFieldErrors(apiError({ ok: false, error: { message: "x", field_errors: { g: "req" } } }, 422))
    ).toEqual({ g: "req" });
    expect(getFieldErrors(null)).toEqual({});
  });

  it("hasFieldErrors gates the generic box", () => {
    expect(hasFieldErrors(apiError({ error: "x", field_errors: { f: "req" } }, 422))).toBe(true);
    expect(hasFieldErrors(apiError({ error: "x" }, 422))).toBe(false);
  });
});

describe("normalizeFailure (Phase 6Q)", () => {
  it("preserves structured code/message/details/field errors", () => {
    const err = apiError(
      {
        ok: false,
        error: "Move blocked.",
        code: "ROOM_CONFLICT",
        details: { day: "Mon", conflicting_class_id: 7 },
        field_errors: { room: "Taken." },
        failures: [{ code: "ROOM_CONFLICT", message: "Taken.", details: { day: "Mon" } }],
      },
      422
    );
    const out = normalizeFailure(err);
    expect(out.code).toBe("ROOM_CONFLICT");
    expect(out.message).toBe("Move blocked.");
    expect(out.details).toEqual({ day: "Mon", conflicting_class_id: 7 });
    expect(out.fieldErrors).toEqual({ room: "Taken." });
    expect(out.failures).toHaveLength(1);
    expect(out.status).toBe(422);
    expect(out.category).toBe("validation");
  });

  it("preserves scheduler details (locked_block_ids)", () => {
    const err = apiError(
      {
        error: "Scheduling failed.",
        code: "SCHEDULING_INFEASIBLE",
        details: { locked_block_ids: [3], reason: "blocked" },
        failures: [{ code: "SCHEDULING_INFEASIBLE", message: "blocked", details: {} }],
      },
      422
    );
    const out = normalizeFailure(err);
    expect(out.category).toBe("scheduler");
    expect(out.details.locked_block_ids).toEqual([3]);
  });

  it("handles unknown structured codes with a safe fallback", () => {
    const out = normalizeFailure(apiError({ error: "Weird.", code: "FUTURE_X" }, 422));
    expect(out.code).toBe("FUTURE_X");
    expect(out.message).toBe("Weird.");
    expect(labelFor(out.code)).toBe("FUTURE_X");
  });

  it("handles HTTP-only errors without JSON", () => {
    const err = new ApiError("Request failed (502).", { status: 502, payload: null });
    const out = normalizeFailure(err);
    expect(out.message).toBe("Request failed (502).");
    expect(out.category).toBe("internal");
  });

  it("handles malformed/empty bodies", () => {
    const out = normalizeFailure(new ApiError("", { status: 200, payload: null }));
    expect(typeof out.message).toBe("string");
    expect(out.message.length).toBeGreaterThan(0);
  });

  it("handles network failures distinctly", () => {
    const out = normalizeFailure(new ApiError("Could not reach the server.", { status: 0 }));
    expect(out.category).toBe("network");
    expect(out.status).toBe(0);
  });

  it("handles unknown JS exceptions generically", () => {
    const out = normalizeFailure(new TypeError("boom"));
    expect(out.message).toBe("Something went wrong. Please try again.");
    expect(out.category).toBe("error");
  });

  it("handles null/undefined/string inputs", () => {
    for (const input of [null, undefined, "plain text"]) {
      const out = normalizeFailure(input);
      expect(typeof out.message).toBe("string");
      expect(out.message).not.toBe("[object Object]");
    }
  });

  it("never emits [object Object] for object messages", () => {
    const err = new ApiError({ weird: true }, { status: 500, payload: { error: { weird: 1 } } });
    const out = normalizeFailure(err);
    expect(out.message).not.toContain("[object Object]");
  });

  it("keeps import row errors without losing them", () => {
    const out = normalizeFailure(
      apiError({ ok: true, message: "done", counts: {}, errors: ["Row 2: bad"] }, 200)
    );
    expect(out.importErrors).toEqual(["Row 2: bad"]);
  });

  it("is idempotent on normalized input", () => {
    const once = normalizeFailure(apiError({ error: "x", code: "ROOM_CONFLICT" }, 422));
    expect(normalizeFailure(once)).toBe(once);
  });
});

describe("getFailures / getImportRowErrors (Phase 6Q)", () => {
  it("still reads structured failures only", () => {
    expect(getFailures(apiError({ failures: [{ code: "X" }] }, 422))).toHaveLength(1);
    expect(getFailures(apiError({ error: "x" }, 422))).toEqual([]);
  });

  it("reads import row errors from success payloads", () => {
    expect(getImportRowErrors({ errors: ["Row 1: bad"], message: "m" })).toEqual(["Row 1: bad"]);
    expect(getImportRowErrors(null)).toEqual([]);
  });
});
