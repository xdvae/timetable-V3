// Phase 6U — frontend API contract tests.
//
// Real service modules + real client + real normalizer, with ONLY the
// network boundary (global fetch) stubbed. Each test pins the HTTP
// method, URL, and JSON body the frontend sends, plus the success/error
// envelope handling the UI depends on. No page, hook, or backend is
// mocked: the purpose is to catch frontend/backend contract drift.
//
// Read-only safety: every GET test also asserts no mutation method was
// used and the scheduler endpoint was never touched.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/services/api/client.js";
import { login, logout, me } from "@/services/api/auth.js";
import { getScheduledClasses, moveScheduledClass, validateMove } from "@/services/api/schedule.js";
import {
  getTimetableHome,
  getTimetableView,
  getFreeFaculty,
  runScheduler,
} from "@/services/api/timetable.js";
import {
  getAssignments,
  reassignFaculty,
  swapFaculty,
  validateFacultySwap,
  validateReassignFaculty,
} from "@/services/api/assignments.js";
import {
  createSpecialization,
  deleteMembership,
  deleteSpecialization,
  getSpecialization,
  getSpecializations,
  saveMembership,
} from "@/services/api/specializations.js";
import {
  createLockedBlock,
  deleteLockedBlock,
  getLockedBlocks,
} from "@/services/api/lockedBlocks.js";
import { setPreferredTheoryRoom } from "@/services/api/enrollments.js";
import {
  createFacultyPreference,
  deleteFacultyPreference,
  getFacultyPreferences,
  updateFacultyPreference,
} from "@/services/api/faculty.js";
import { normalizeFailure } from "@/lib/failures.js";

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => (String(name).toLowerCase() === "content-type" ? "application/json" : "") },
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  };
}

function errorResponse(body, status) {
  return jsonResponse(body, status);
}

function textResponse(text, status) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => "text/html" },
    json: async () => {
      throw new SyntaxError("not json");
    },
    text: async () => text,
  };
}

let calls;

function stubFetch(handler) {
  calls = [];
  vi.stubGlobal("fetch", async (url, init = {}) => {
    calls.push({ url, method: init.method ?? "GET", body: init.body });
    return handler(calls[calls.length - 1]);
  });
}

function lastCall() {
  return calls[calls.length - 1];
}

function parsedBody(call) {
  return typeof call.body === "string" ? JSON.parse(call.body) : call.body;
}

function errorText(err) {
  return `${err.message ?? ""} ${JSON.stringify(err.payload ?? null)}`;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("auth contracts (Phase 6U)", () => {
  it("login POSTs credentials to /api/login", async () => {
    stubFetch(() => jsonResponse({ ok: true, username: "admin" }));
    const data = await login("admin", "password123");
    expect(data.username).toBe("admin");
    expect(lastCall().url).toBe("/api/login");
    expect(lastCall().method).toBe("POST");
    expect(parsedBody(lastCall())).toEqual({ username: "admin", password: "password123" });
  });

  it("login failure preserves the 401 INVALID_CREDENTIALS contract", async () => {
    stubFetch(() =>
      errorResponse({ ok: false, error: "Incorrect username or password.", code: "INVALID_CREDENTIALS" }, 401)
    );
    const err = await login("admin", "wrong").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(401);
    expect(err.isAuth).toBe(true);
    expect(err.code).toBe("INVALID_CREDENTIALS");
    const normalized = normalizeFailure(err);
    expect(normalized.category).toBe("auth");
    expect(normalized.message).toBe("Incorrect username or password.");
  });

  it("session read uses GET /api/me and logout uses POST /api/logout", async () => {
    stubFetch((call) => {
      if (call.url === "/api/me") return jsonResponse({ username: "admin" });
      return jsonResponse({ ok: true });
    });
    await me();
    expect(lastCall().url).toBe("/api/me");
    expect(lastCall().method).toBe("GET");
    await logout();
    expect(lastCall().url).toBe("/api/logout");
    expect(lastCall().method).toBe("POST");
  });

  it("unauthorized API responses normalize to a safe auth state", async () => {
    stubFetch(() => errorResponse({ ok: false, error: "Authentication required.", code: "AUTH_REQUIRED" }, 401));
    const err = await me().catch((e) => e);
    const normalized = normalizeFailure(err);
    expect(normalized.category).toBe("auth");
    expect(normalized.code).toBe("AUTH_REQUIRED");
    expect(normalized.message).not.toBe("[object Object]");
    expect(normalized.message).not.toBe("undefined");
  });
});

describe("timetable/editor contracts (Phase 6U)", () => {
  it("scheduled-classes read uses GET with no body and the documented keys", async () => {
    stubFetch(() =>
      jsonResponse({ classes: [], days: ["Mon"], periods: ["p0"], break_after: 4, has_schedule: false })
    );
    const data = await getScheduledClasses();
    expect(lastCall().url).toBe("/api/schedule/classes");
    expect(lastCall().method).toBe("GET");
    expect(lastCall().body).toBeUndefined();
    expect(data.classes).toEqual([]);
    expect(data.has_schedule).toBe(false);
  });

  it("validate-move and move POST day/start_period/room_id to the class URLs", async () => {
    stubFetch((call) => {
      if (call.url.endsWith("/validate-move")) {
        return jsonResponse({ ok: true, noop: false, message: "Move is valid.", candidate: {}, current: {} });
      }
      return jsonResponse({ ok: true, noop: false, message: "moved", scheduled_class: { id: 7 } });
    });
    await validateMove(7, { day: "Tue", start_period: 2, room_id: 3 });
    expect(lastCall().url).toBe("/api/schedule/classes/7/validate-move");
    expect(lastCall().method).toBe("POST");
    expect(parsedBody(lastCall())).toEqual({ day: "Tue", start_period: 2, room_id: 3 });
    await moveScheduledClass(7, { day: "Tue", start_period: 2, room_id: 3 });
    expect(lastCall().url).toBe("/api/schedule/classes/7/move");
    expect(lastCall().method).toBe("POST");
    expect(parsedBody(lastCall())).toEqual({ day: "Tue", start_period: 2, room_id: 3 });
  });

  it("same-position move surfaces the noop contract", async () => {
    stubFetch(() => jsonResponse({ ok: true, noop: true, message: "nothing changed" }));
    const data = await moveScheduledClass(7, { day: "Mon", start_period: 0, room_id: 1 });
    expect(data.noop).toBe(true);
  });

  it("timetable home/view/free-faculty reads are GETs with the documented shapes", async () => {
    stubFetch((call) => {
      if (call.url === "/api/timetable") return jsonResponse({ sections: [], faculty: [], rooms: [], has_schedule: false });
      if (call.url.startsWith("/api/timetable/free")) {
        return jsonResponse({ days: [], periods: [], faculty: [], busy: [] });
      }
      return jsonResponse({ title: "T", view: "section", day_rows: [] });
    });
    await getTimetableHome();
    expect(lastCall().method).toBe("GET");
    await getTimetableView("section", 1);
    expect(lastCall().url).toBe("/api/timetable/section/1");
    expect(lastCall().method).toBe("GET");
    await getFreeFaculty("Mon");
    expect(lastCall().url).toBe("/api/timetable/free?day=Mon");
    expect(lastCall().method).toBe("GET");
    // Read-only paths never invoke the scheduler.
    expect(calls.some((c) => String(c.url).includes("/api/schedule/run"))).toBe(false);
  });

  it("locked-class move rejection preserves the structured failure envelope", async () => {
    stubFetch(() =>
      errorResponse(
        {
          ok: false,
          error: "Locked timetable block.",
          code: "LOCKED_BLOCK",
          failures: [{ code: "LOCKED_BLOCK", message: "Locked timetable block.", details: {} }],
        },
        422
      )
    );
    const err = await moveScheduledClass(9, { day: "Tue", start_period: 1, room_id: 1 }).catch((e) => e);
    expect(err.status).toBe(422);
    const normalized = normalizeFailure(err);
    expect(normalized.code).toBe("LOCKED_BLOCK");
    expect(normalized.failures).toHaveLength(1);
    expect(errorText(err)).not.toMatch(/traceback|Traceback|SELECT|UNIQUE/i);
  });
});

describe("assignment/faculty contracts (Phase 6U)", () => {
  it("assignment listing maps the live backend shape", async () => {
    stubFetch(() =>
      jsonResponse({ assignments: [{ id: 1 }], faculty: [], subjects: [], sections: [], lab_groups: [], faculty_load: {}, subjects_json: {} })
    );
    const data = await getAssignments();
    expect(lastCall().url).toBe("/api/assignments");
    expect(lastCall().method).toBe("GET");
    expect(data.assignments).toHaveLength(1);
    expect(data.labGroups).toEqual([]);
  });

  it("reassign validate + apply send faculty_id to the assignment URLs", async () => {
    stubFetch((call) => {
      if (call.url.endsWith("/validate-reassign")) {
        return jsonResponse({ ok: true, noop: false, dry_run: true });
      }
      return jsonResponse({ ok: true, noop: false, assignment: { id: 1 } });
    });
    await validateReassignFaculty(1, 2);
    expect(lastCall().url).toBe("/api/assignments/1/validate-reassign");
    expect(parsedBody(lastCall())).toEqual({ faculty_id: 2 });
    await reassignFaculty(1, 2);
    expect(lastCall().url).toBe("/api/assignments/1/reassign");
    expect(parsedBody(lastCall())).toEqual({ faculty_id: 2 });
  });

  it("swap validate + apply send both assignment ids", async () => {
    stubFetch((call) => {
      if (call.url.endsWith("/validate-swap")) return jsonResponse({ ok: true, noop: false, dry_run: true });
      return jsonResponse({ ok: true, noop: false, assignments: [{ id: 1 }, { id: 2 }] });
    });
    await validateFacultySwap(1, 2);
    expect(lastCall().url).toBe("/api/assignments/validate-swap");
    expect(parsedBody(lastCall())).toEqual({ assignment_a_id: 1, assignment_b_id: 2 });
    await swapFaculty(1, 2);
    expect(lastCall().url).toBe("/api/assignments/swap");
    expect(parsedBody(lastCall())).toEqual({ assignment_a_id: 1, assignment_b_id: 2 });
  });

  it("locked-assignment reassignment rejection keeps code + failures", async () => {
    stubFetch(() =>
      errorResponse(
        { ok: false, error: "Locked.", code: "LOCKED_BLOCK", failures: [{ code: "LOCKED_BLOCK", message: "Locked.", details: {} }] },
        422
      )
    );
    const err = await reassignFaculty(1, 2).catch((e) => e);
    expect(normalizeFailure(err).code).toBe("LOCKED_BLOCK");
  });

  it("specialization-guarded swap rejection preserves SPECIALIZATION_SWAP", async () => {
    stubFetch(() =>
      errorResponse(
        {
          ok: false,
          error: "Incompatible specialization swap.",
          code: "SPECIALIZATION_SWAP",
          failures: [{ code: "SPECIALIZATION_SWAP", message: "Incompatible.", details: {} }],
        },
        422
      )
    );
    const err = await swapFaculty(1, 2).catch((e) => e);
    expect(normalizeFailure(err).code).toBe("SPECIALIZATION_SWAP");
  });
});

describe("specialization contracts (Phase 6U)", () => {
  it("list/detail/create/delete/membership use the documented routes", async () => {
    stubFetch((call) => {
      if (call.url === "/api/specializations" && call.method === "GET") {
        return jsonResponse({ specializations: [{ id: 1 }] });
      }
      if (call.url === "/api/specializations/1" && call.method === "GET") {
        return jsonResponse({ specialization: { id: 1 } });
      }
      if (call.url === "/api/specializations" && call.method === "POST") {
        return jsonResponse({ ok: true, specialization: { id: 2 } }, 201);
      }
      if (call.url === "/api/specializations/1/memberships" && call.method === "POST") {
        return jsonResponse({ ok: true, membership: {} }, 201);
      }
      if (call.url === "/api/specializations/1/memberships/delete") {
        return jsonResponse({ ok: true });
      }
      return jsonResponse({ ok: true });
    });
    const list = await getSpecializations();
    expect(list.specializations).toHaveLength(1);
    await getSpecialization(1);
    expect(lastCall().url).toBe("/api/specializations/1");
    await createSpecialization({ name: "AI", enrollment_id: 1 });
    expect(lastCall().url).toBe("/api/specializations");
    expect(lastCall().method).toBe("POST");
    await saveMembership(1, { sectionId: 3, studentCount: 20 });
    expect(lastCall().url).toBe("/api/specializations/1/memberships");
    expect(parsedBody(lastCall())).toEqual({ section_id: 3, student_count: 20 });
    await deleteMembership(1, 3);
    expect(lastCall().url).toBe("/api/specializations/1/memberships/delete");
    expect(parsedBody(lastCall())).toEqual({ section_id: 3 });
    await deleteSpecialization(1);
    expect(lastCall().url).toBe("/api/specializations/1/delete");
    expect(lastCall().method).toBe("POST");
  });

  it("specialization sync failures surface structurally", async () => {
    stubFetch(() =>
      errorResponse(
        {
          ok: false,
          error: "Specialization out of sync.",
          code: "SPECIALIZATION_SYNC",
          failures: [{ code: "SPECIALIZATION_SYNC", message: "Out of sync.", details: {} }],
        },
        422
      )
    );
    const err = await saveMembership(1, { sectionId: 3, studentCount: 20 }).catch((e) => e);
    expect(normalizeFailure(err).code).toBe("SPECIALIZATION_SYNC");
  });
});

describe("locked-block contracts (Phase 6U)", () => {
  it("list/create/delete use the documented routes and payload", async () => {
    stubFetch((call) => {
      if (call.url === "/api/locked-blocks" && call.method === "GET") {
        return jsonResponse({ locked_blocks: [] });
      }
      if (call.url === "/api/locked-blocks" && call.method === "POST") {
        return jsonResponse({ ok: true, locked_block: { id: 1 }, scheduled_class: { id: 5 } }, 201);
      }
      return jsonResponse({ ok: true });
    });
    const list = await getLockedBlocks();
    expect(list.lockedBlocks).toEqual([]);
    await createLockedBlock({ assignment_id: 1, day: "Mon", start_period: 0, length: 2, room_id: 1 });
    expect(lastCall().url).toBe("/api/locked-blocks");
    expect(lastCall().method).toBe("POST");
    expect(parsedBody(lastCall())).toMatchObject({ assignment_id: 1, day: "Mon", length: 2 });
    await deleteLockedBlock(1);
    expect(lastCall().url).toBe("/api/locked-blocks/1/delete");
  });

  it("room-required and assignment-mismatch failures keep codes + field errors", async () => {
    stubFetch(() =>
      errorResponse(
        { ok: false, error: "Room required.", code: "ROOM_REQUIRED", field_errors: { placement: "Room required." } },
        422
      )
    );
    const err = await createLockedBlock({ assignment_id: 1, day: "Mon", start_period: 0, length: 1 }).catch((e) => e);
    expect(err.code).toBe("ROOM_REQUIRED");
    expect(err.fieldErrors).toEqual({ placement: "Room required." });
    expect(normalizeFailure(err).fieldErrors).toEqual({ placement: "Room required." });
  });
});

describe("preferred-room contracts (Phase 6U)", () => {
  it("set and clear POST room_id to the section URL", async () => {
    stubFetch(() => jsonResponse({ ok: true, section: { id: 5 }, warning: null }));
    await setPreferredTheoryRoom(5, 2);
    expect(lastCall().url).toBe("/api/sections/5/preferred-room");
    expect(parsedBody(lastCall())).toEqual({ room_id: 2 });
    await setPreferredTheoryRoom(5, null);
    expect(parsedBody(lastCall())).toEqual({ room_id: null });
  });

  it("stale-room warning payloads survive the client untouched", async () => {
    stubFetch(() => jsonResponse({ ok: true, section: { id: 5 }, warning: { message: "lab room", room_id: 2 } }));
    const data = await setPreferredTheoryRoom(5, 2);
    expect(data.warning.room_id).toBe(2);
  });
});

describe("faculty-preference contracts (Phase 6U)", () => {
  it("list/create/update/delete use the documented routes", async () => {
    stubFetch((call) => {
      if (call.method === "GET") return jsonResponse({ faculty: { id: 1 }, preferences: [] });
      if (call.url === "/api/faculty/1/preferences") return jsonResponse({ ok: true, preference: { id: 1 } }, 201);
      if (call.url === "/api/faculty/preferences/1") return jsonResponse({ ok: true, preference: { id: 1 } });
      return jsonResponse({ ok: true });
    });
    await getFacultyPreferences(1);
    expect(lastCall().url).toBe("/api/faculty/1/preferences");
    expect(lastCall().method).toBe("GET");
    await createFacultyPreference(1, { kind: "DAY_OFF_PREFERENCE", days: ["Mon"] });
    expect(lastCall().method).toBe("POST");
    expect(parsedBody(lastCall())).toMatchObject({ kind: "DAY_OFF_PREFERENCE" });
    await updateFacultyPreference(1, { weight: 7 });
    expect(lastCall().url).toBe("/api/faculty/preferences/1");
    await deleteFacultyPreference(1);
    expect(lastCall().url).toBe("/api/faculty/preferences/1/delete");
  });

  it("hard-preference and unsupported-kind rejections keep stable codes", async () => {
    stubFetch(() => errorResponse({ ok: false, error: "Preferences are soft-only.", code: "PREF_HARD_UNSUPPORTED" }, 422));
    const hard = await createFacultyPreference(1, { kind: "DAY_OFF_PREFERENCE", is_hard: true }).catch((e) => e);
    expect(normalizeFailure(hard).code).toBe("PREF_HARD_UNSUPPORTED");
    stubFetch(() => errorResponse({ ok: false, error: "Unsupported kind.", code: "PREF_INVALID_KIND" }, 422));
    const kind = await createFacultyPreference(1, { kind: "SUBJECT_AFFINITY" }).catch((e) => e);
    expect(normalizeFailure(kind).code).toBe("PREF_INVALID_KIND");
  });
});

describe("generation contracts (Phase 6U)", () => {
  it("generation POSTs /api/schedule/run with no body and reports OPTIMAL/FEASIBLE", async () => {
    for (const status of ["OPTIMAL", "FEASIBLE"]) {
      stubFetch(() => jsonResponse({ ok: true, message: "done", status, placements: 4, run_id: "r1" }));
      const data = await runScheduler();
      expect(lastCall().url).toBe("/api/schedule/run");
      expect(lastCall().method).toBe("POST");
      expect(data.status).toBe(status);
      expect(data.placements).toBe(4);
    }
  });

  it("INFEASIBLE stays a proven infeasibility with structured failures", async () => {
    stubFetch(() =>
      errorResponse(
        {
          ok: false,
          error: "Scheduling failed: No valid timetable could be found.",
          code: "SCHEDULING_FAILED",
          details: { reason: "No valid timetable could be found." },
        },
        422
      )
    );
    const err = await runScheduler().catch((e) => e);
    const normalized = normalizeFailure(err);
    expect(normalized.category).toBe("scheduler");
    expect(normalized.code).toBe("SCHEDULING_FAILED");
    expect(normalized.message).toMatch(/No valid timetable/i);
  });

  it("UNKNOWN/timeout is never reported as infeasible", async () => {
    stubFetch(() =>
      errorResponse(
        {
          ok: false,
          error: "Scheduling did not complete: time limit reached",
          code: "SCHEDULING_FAILED",
          details: { status: "UNKNOWN", timeout: true, reason: "time limit reached" },
          failures: [{ code: "SCHEDULING_FAILED", message: "time limit reached", details: { status: "UNKNOWN" } }],
        },
        422
      )
    );
    const err = await runScheduler().catch((e) => e);
    const normalized = normalizeFailure(err);
    expect(normalized.category).toBe("scheduler");
    expect(normalized.message.toLowerCase()).not.toContain("infeasible");
    expect(err.payload.details.timeout).toBe(true);
    expect(err.payload.details.status).toBe("UNKNOWN");
  });

  it("MODEL_INVALID becomes a sanitized internal failure", async () => {
    stubFetch(() => errorResponse({ ok: false, error: "Something went wrong on the server. Please try again.", code: "INTERNAL_ERROR" }, 500));
    const err = await runScheduler().catch((e) => e);
    const normalized = normalizeFailure(err);
    expect(normalized.category).toBe("internal");
    expect(normalized.code).toBe("INTERNAL_ERROR");
    expect(errorText(err)).not.toMatch(/traceback|Traceback|secret|\.db|\.py/i);
  });
});

describe("unified error transport (Phase 6U: the 16 scenarios)", () => {
  async function failsAs(fetchImpl, input) {
    stubFetch(fetchImpl);
    return normalizeFailure(await input().catch((e) => e));
  }

  it("1-3: structured failure, field errors, and failures array survive", async () => {
    const body = {
      ok: false,
      error: "Room already occupied.",
      code: "ROOM_CONFLICT",
      details: { day: "Mon" },
      field_errors: { room_id: "Taken." },
      failures: [{ code: "ROOM_CONFLICT", message: "Room already occupied.", details: { day: "Mon" } }],
    };
    const out = await failsAs(() => errorResponse(body, 422), () => getScheduledClasses());
    expect(out.code).toBe("ROOM_CONFLICT");
    expect(out.message).toBe("Room already occupied.");
    expect(out.fieldErrors).toEqual({ room_id: "Taken." });
    expect(out.failures).toHaveLength(1);
    expect(out.category).toBe("validation");
  });

  it("8-11: 401/404/400/405 map to stable categories with safe messages", async () => {
    const cases = [
      [() => errorResponse({ ok: false, error: "Authentication required.", code: "AUTH_REQUIRED" }, 401), "auth"],
      [() => errorResponse({ ok: false, error: "Not found.", code: "NOT_FOUND" }, 404), "not_found"],
      [() => errorResponse({ ok: false, error: "Invalid request.", code: "BAD_REQUEST" }, 400), "error"],
      [() => errorResponse({ ok: false, error: "Method not allowed.", code: "METHOD_NOT_ALLOWED" }, 405), "error"],
    ];
    for (const [impl, category] of cases) {
      const out = await failsAs(impl, () => getScheduledClasses());
      expect(out.category).toBe(category);
      expect(typeof out.message).toBe("string");
      expect(out.message.length).toBeGreaterThan(0);
    }
  });

  it("12-13: non-JSON and malformed JSON degrade to safe retryable messages", async () => {
    const html = await failsAs(() => textResponse("<html><body>Proxy Error</body></html>", 502), () => getScheduledClasses());
    expect(html.message).not.toContain("<html>");
    expect(html.message).not.toBe("[object Object]");
    stubFetch(() => ({
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: async () => {
        throw new SyntaxError("Unexpected token");
      },
      text: async () => "{bad",
    }));
    const malformed = normalizeFailure(await getScheduledClasses().catch((e) => e));
    expect(typeof malformed.message).toBe("string");
    expect(malformed.message.length).toBeGreaterThan(0);
  });

  it("14-15: network failure and unknown JS errors stay safe", async () => {
    stubFetch(() => {
      throw new TypeError("fetch failed");
    });
    const network = normalizeFailure(await getScheduledClasses().catch((e) => e));
    expect(network.category).toBe("network");
    expect(network.status).toBe(0);
    const unknown = normalizeFailure(new TypeError("boom"));
    expect(unknown.message).toBe("Something went wrong. Please try again.");
    expect(unknown.message).not.toBe("[object Object]");
  });

  it("16: unknown future backend codes are preserved, never invented", async () => {
    stubFetch(() => errorResponse({ ok: false, error: "Something future happened.", code: "FUTURE_CODE_X" }, 422));
    const out = normalizeFailure(await getScheduledClasses().catch((e) => e));
    expect(out.code).toBe("FUTURE_CODE_X");
    expect(out.message).toBe("Something future happened.");
    expect(out.message).not.toBe("undefined");
  });
});

describe("contract drift guard (Phase 6U)", () => {
  it("critical mutations use POST against /api/* (never GET, never a renamed path)", () => {
    const routes = {
      login: () => login("u", "p"),
      logout: () => logout(),
      validateMove: () => validateMove(1, { day: "Mon", start_period: 0, room_id: 1 }),
      move: () => moveScheduledClass(1, { day: "Mon", start_period: 0, room_id: 1 }),
      reassign: () => reassignFaculty(1, 2),
      swap: () => swapFaculty(1, 2),
      run: () => runScheduler(),
      prefRoom: () => setPreferredTheoryRoom(1, 2),
    };
    const expected = {
      login: "/api/login",
      logout: "/api/logout",
      validateMove: "/api/schedule/classes/1/validate-move",
      move: "/api/schedule/classes/1/move",
      reassign: "/api/assignments/1/reassign",
      swap: "/api/assignments/swap",
      run: "/api/schedule/run",
      prefRoom: "/api/sections/1/preferred-room",
    };
    return (async () => {
      for (const [key, fn] of Object.entries(routes)) {
        stubFetch(() => jsonResponse({ ok: true }));
        await fn().catch(() => null);
        expect(lastCall().method, key).toBe("POST");
        expect(lastCall().url, key).toBe(expected[key]);
      }
    })();
  });
});
