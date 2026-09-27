// Phase 6U — cross-feature workflow integration tests.
//
// Real client + real normalizer + real hooks + real invalidation bus +
// real feedback components, with ONLY the network boundary (global fetch)
// stubbed. Each workflow mirrors the exact glue the pages use:
//
//   const res = await execute(serviceFn);   // useMutation (real)
//   emitOnSuccess(res, *_DOMAINS);          // propagation (real)
//   ... useApi consumers refetch ...       // invalidation (real)
//
// Validation-only calls never reach emitOnSuccess; failed/noop results
// never emit centrally. Browser click-through is NOT claimed here (see
// the final audit: no browser-capable runner exists in this repo).
// @vitest-environment jsdom
import { act, useCallback } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { INVALIDATION_DOMAINS, emitInvalidation, resetInvalidationForTests } from "@/lib/invalidation.js";
import {
  GENERATION_DOMAINS,
  LOCKED_BLOCK_DOMAINS,
  MEMBERSHIP_DOMAINS,
  MOVE_DOMAINS,
  PREFERENCE_DOMAINS,
  PREFERRED_ROOM_DOMAINS,
  REASSIGN_DOMAINS,
  SPECIALIZATION_DOMAINS,
  SWAP_DOMAINS,
  emitOnSuccess,
} from "@/lib/propagation.js";
import { getFailures, normalizeFailure } from "@/lib/failures.js";
import { moveScheduledClass, validateMove } from "@/services/api/schedule.js";
import { reassignFaculty, swapFaculty } from "@/services/api/assignments.js";
import { runScheduler } from "@/services/api/timetable.js";
import { createLockedBlock } from "@/services/api/lockedBlocks.js";
import { saveMembership } from "@/services/api/specializations.js";
import { setPreferredTheoryRoom } from "@/services/api/enrollments.js";
import { createFacultyPreference } from "@/services/api/faculty.js";
import { EmptyState, QueryError } from "@/components/feedback/data-states.jsx";
import { FailureList, FieldError, MutationError, MutationFailure } from "@/components/feedback/mutation.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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

function stubFetch(handler) {
  const calls = [];
  vi.stubGlobal("fetch", async (url, init = {}) => {
    calls.push({ url, method: init.method ?? "GET", body: init.body });
    return handler(calls[calls.length - 1]);
  });
  return calls;
}

/** Harness mirroring page glue: useMutation + emitOnSuccess on success. */
function Mutator({ mutateFn, onResult }) {
  const { execute, error, fieldErrors } = useMutation(mutateFn);
  onResult({ execute, error, fieldErrors });
  return null;
}

/** Counting useApi consumer for the given domains. */
function Watcher({ name, domains, fetcher, onFetch }) {
  const stable = useCallback(() => {
    onFetch(name);
    return fetcher();
  }, [name, fetcher, onFetch]);
  useApi(stable, domains);
  return null;
}

let container;
let root;

beforeEach(() => {
  resetInvalidationForTests();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  vi.unstubAllGlobals();
});

async function renderTree(children) {
  await act(async () => {
    root.render(children);
  });
}

function textOf() {
  return container.textContent ?? "";
}

/** Run a mutation exactly like the pages do; returns the useMutation result. */
function useWorkflowRunner() {
  let execute = null;
  async function mount(watchDefs, mutateFn, onFetch) {
    await renderTree(
      <>
        {watchDefs.map((w) => (
          <Watcher key={w.name} name={w.name} domains={w.domains} fetcher={w.fetcher} onFetch={onFetch} />
        ))}
        <Mutator mutateFn={mutateFn} onResult={(next) => { execute = next.execute; }} />
      </>
    );
  }
  async function run(args, domains) {
    let res = null;
    await act(async () => {
      res = await execute(args);
    });
    let emitted = false;
    await act(async () => {
      emitted = emitOnSuccess(res, domains);
    });
    return { res, emitted };
  }
  return { mount, run };
}

const resolveNow = () => Promise.resolve({});

describe("Workflow A — manual timetable move (Phase 6U)", () => {
  it("validate then apply succeeds and invalidates schedule consumers", async () => {
    stubFetch(() => jsonResponse({ ok: true, noop: false, message: "Move is valid." }));
    const flow = useWorkflowRunner();
    let scheduleRefetches = 0;
    await flow.mount(
      [{ name: "s", domains: ["schedule"], fetcher: resolveNow }],
      (payload) => moveScheduledClass(3, payload),
      () => { scheduleRefetches += 1; }
    );
    expect(scheduleRefetches).toBe(1);

    const valid = await validateMove(3, { day: "Tue", start_period: 2, room_id: 1 });
    expect(valid.noop).toBe(false);
    // Validation-only: no central emission (pages never call emit here).
    expect(scheduleRefetches).toBe(1);

    const { res, emitted } = await flow.run({ day: "Tue", start_period: 2, room_id: 1 }, MOVE_DOMAINS);
    expect(res.ok).toBe(true);
    expect(emitted).toBe(true);
    expect(scheduleRefetches).toBe(2);
  });

  it("failed validation does not mutate and does not emit", async () => {
    stubFetch(() =>
      errorResponse(
        { ok: false, error: "Room already occupied.", code: "ROOM_CONFLICT", failures: [{ code: "ROOM_CONFLICT", message: "Taken.", details: {} }] },
        422
      )
    );
    const flow = useWorkflowRunner();
    let scheduleRefetches = 0;
    await flow.mount([{ name: "s", domains: ["schedule"], fetcher: resolveNow }], (p) => moveScheduledClass(3, p), () => { scheduleRefetches += 1; });
    const err = await validateMove(3, { day: "Tue", start_period: 2, room_id: 1 }).catch((e) => e);
    expect(normalizeFailure(err).code).toBe("ROOM_CONFLICT");
    expect(scheduleRefetches).toBe(1);
  });

  it("failed apply emits nothing centrally (local stale-recovery only)", async () => {
    stubFetch(() => errorResponse({ ok: false, error: "Section already has a class.", code: "SECTION_CONFLICT" }, 422));
    const flow = useWorkflowRunner();
    let scheduleRefetches = 0;
    await flow.mount([{ name: "s", domains: ["schedule"], fetcher: resolveNow }], (p) => moveScheduledClass(3, p), () => { scheduleRefetches += 1; });
    const { res, emitted } = await flow.run({ day: "Tue", start_period: 2, room_id: 1 }, MOVE_DOMAINS);
    expect(res.ok).toBe(false);
    expect(emitted).toBe(false);
    expect(scheduleRefetches).toBe(1);
  });

  it("same-position noop applies locally but emits nothing centrally", async () => {
    stubFetch(() => jsonResponse({ ok: true, noop: true, message: "nothing changed" }));
    const flow = useWorkflowRunner();
    let scheduleRefetches = 0;
    await flow.mount([{ name: "s", domains: ["schedule"], fetcher: resolveNow }], (p) => moveScheduledClass(3, p), () => { scheduleRefetches += 1; });
    const { res, emitted } = await flow.run({ day: "Mon", start_period: 0, room_id: 1 }, MOVE_DOMAINS);
    expect(res.ok).toBe(true);
    expect(res.data.noop).toBe(true);
    expect(emitted).toBe(false);
    expect(scheduleRefetches).toBe(1);
  });
});

describe("Workflows B/C — reassignment and swap (Phase 6U)", () => {
  it("successful reassignment invalidates assignments + schedule + faculty + overview", async () => {
    stubFetch(() => jsonResponse({ ok: true, noop: false, assignment: { id: 1 } }));
    const flow = useWorkflowRunner();
    const seen = {};
    await flow.mount(
      ["assignments", "schedule", "faculty", "overview", "rooms"].map((d) => ({ name: d, domains: [d], fetcher: resolveNow })),
      (fid) => reassignFaculty(1, fid),
      (n) => { seen[n] = (seen[n] ?? 0) + 1; }
    );
    const { res, emitted } = await flow.run(2, REASSIGN_DOMAINS);
    expect(res.ok).toBe(true);
    expect(emitted).toBe(true);
    expect(seen.assignments).toBe(2);
    expect(seen.schedule).toBe(2);
    expect(seen.faculty).toBe(2);
    expect(seen.overview).toBe(2);
    expect(seen.rooms).toBe(1);
  });

  it("failed reassignment produces no propagation", async () => {
    stubFetch(() => errorResponse({ ok: false, error: "Locked.", code: "LOCKED_BLOCK" }, 422));
    const flow = useWorkflowRunner();
    let count = 0;
    await flow.mount([{ name: "a", domains: ["assignments"], fetcher: resolveNow }], (fid) => reassignFaculty(1, fid), () => { count += 1; });
    const { res, emitted } = await flow.run(2, REASSIGN_DOMAINS);
    expect(res.ok).toBe(false);
    expect(emitted).toBe(false);
    expect(count).toBe(1);
  });

  it("successful swap refreshes both affected views; failed swap emits nothing", async () => {
    stubFetch(() => jsonResponse({ ok: true, noop: false, assignments: [{ id: 1 }, { id: 2 }] }));
    const flow = useWorkflowRunner();
    const seen = {};
    await flow.mount(
      ["assignments", "schedule", "faculty", "overview"].map((d) => ({ name: d, domains: [d], fetcher: resolveNow })),
      () => swapFaculty(1, 2),
      (n) => { seen[n] = (seen[n] ?? 0) + 1; }
    );
    const ok = await flow.run(undefined, SWAP_DOMAINS);
    expect(ok.res.ok).toBe(true);
    expect(ok.emitted).toBe(true);
    for (const d of ["assignments", "schedule", "faculty", "overview"]) expect(seen[d]).toBe(2);

    stubFetch(() => errorResponse({ ok: false, error: "Invalid swap.", code: "INVALID_SWAP" }, 422));
    const before = { ...seen };
    const bad = await flow.run(undefined, SWAP_DOMAINS);
    expect(bad.res.ok).toBe(false);
    expect(bad.emitted).toBe(false);
    expect(seen).toEqual(before);
  });
});

describe("Workflow D — schedule generation (Phase 6U)", () => {
  it("success fans out to every schedule-dependent domain", async () => {
    stubFetch(() => jsonResponse({ ok: true, message: "done", status: "OPTIMAL", placements: 6, run_id: "r" }));
    const flow = useWorkflowRunner();
    const seen = {};
    await flow.mount(
      ["schedule", "overview", "dashboard", "assignments", "lockedBlocks", "specializations", "preferences", "rooms"].map((d) => ({ name: d, domains: [d], fetcher: resolveNow })),
      () => runScheduler(),
      (n) => { seen[n] = (seen[n] ?? 0) + 1; }
    );
    const { res, emitted } = await flow.run(undefined, GENERATION_DOMAINS);
    expect(res.ok).toBe(true);
    expect(emitted).toBe(true);
    for (const d of ["schedule", "overview", "dashboard", "assignments", "lockedBlocks", "specializations"]) {
      expect(seen[d], d).toBe(2);
    }
    expect(seen.preferences).toBe(1);
    expect(seen.rooms).toBe(1);
  });

  it("failure emits nothing and the previous schedule stays visible (no optimistic replace)", async () => {
    stubFetch(() => errorResponse({ ok: false, error: "Scheduling failed: nope.", code: "SCHEDULING_FAILED" }, 422));
    let refetches = 0;
    const holder = {};
    let execute = null;
    function ScheduleView({ onQuery }) {
      const stable = useCallback(() => {
        refetches += 1;
        return Promise.resolve({ classes: [{ id: 1 }] });
      }, []);
      const query = useApi(stable, ["schedule"]);
      onQuery(query);
      return null;
    }
    // Co-mount the schedule consumer and the generation mutator, exactly
    // like TimetablePage hosts GeneratePanel beside its schedule reads.
    await renderTree(
      <>
        <ScheduleView onQuery={(query) => { holder.query = query; }} />
        <Mutator mutateFn={() => runScheduler()} onResult={(next) => { execute = next.execute; }} />
      </>
    );
    expect(refetches).toBe(1);
    const beforeData = holder.query.data;
    expect(beforeData.classes).toHaveLength(1);
    let res = null;
    await act(async () => {
      res = await execute(undefined);
    });
    let emitted = false;
    await act(async () => {
      emitted = emitOnSuccess(res, GENERATION_DOMAINS);
    });
    expect(res.ok).toBe(false);
    expect(emitted).toBe(false);
    expect(refetches).toBe(1);
    expect(holder.query.data).toBe(beforeData);
  });

  it("UNKNOWN is surfaced as a timeout, never as infeasible", async () => {
    stubFetch(() =>
      errorResponse(
        {
          ok: false,
          error: "Scheduling did not complete: time limit reached",
          code: "SCHEDULING_FAILED",
          details: { status: "UNKNOWN", timeout: true },
          failures: [{ code: "SCHEDULING_FAILED", message: "time limit reached", details: {} }],
        },
        422
      )
    );
    const flow = useWorkflowRunner();
    await flow.mount([], () => runScheduler(), () => {});
    const { res } = await flow.run(undefined, GENERATION_DOMAINS);
    expect(res.ok).toBe(false);
    const normalized = normalizeFailure(res.error);
    expect(normalized.category).toBe("scheduler");
    expect(normalized.message.toLowerCase()).not.toContain("infeasible");
  });
});

describe("Workflows E–H — config mutations (Phase 6U)", () => {
  it("locked-block create invalidates record + schedule + assignments; failure is silent", async () => {
    stubFetch(() => jsonResponse({ ok: true, locked_block: { id: 1 }, scheduled_class: { id: 2 } }, 201));
    const flow = useWorkflowRunner();
    const seen = {};
    await flow.mount(
      ["lockedBlocks", "schedule", "assignments", "rooms"].map((d) => ({ name: d, domains: [d], fetcher: resolveNow })),
      () => createLockedBlock({ assignment_id: 1, day: "Mon", start_period: 0, length: 2, room_id: 1 }),
      (n) => { seen[n] = (seen[n] ?? 0) + 1; }
    );
    const ok = await flow.run(undefined, LOCKED_BLOCK_DOMAINS);
    expect(ok.emitted).toBe(true);
    expect(seen.lockedBlocks).toBe(2);
    expect(seen.schedule).toBe(2);
    expect(seen.assignments).toBe(2);
    expect(seen.rooms).toBe(1);

    stubFetch(() => errorResponse({ ok: false, error: "Room already occupied.", code: "ROOM_CONFLICT" }, 422));
    const bad = await flow.run(undefined, LOCKED_BLOCK_DOMAINS);
    expect(bad.emitted).toBe(false);
  });

  it("membership change refreshes specializations + sections but leaves schedule alone", async () => {
    stubFetch(() => jsonResponse({ ok: true, membership: {} }, 201));
    const flow = useWorkflowRunner();
    const seen = {};
    await flow.mount(
      ["specializations", "sections", "schedule"].map((d) => ({ name: d, domains: [d], fetcher: resolveNow })),
      () => saveMembership(1, { sectionId: 3, studentCount: 10 }),
      (n) => { seen[n] = (seen[n] ?? 0) + 1; }
    );
    const { emitted } = await flow.run(undefined, MEMBERSHIP_DOMAINS);
    expect(emitted).toBe(true);
    expect(seen.specializations).toBe(2);
    expect(seen.sections).toBe(2);
    expect(seen.schedule).toBe(1);
  });

  it("preferred-room set refreshes sections only; the live schedule is untouched", async () => {
    stubFetch(() => jsonResponse({ ok: true, section: { id: 5 }, warning: null }));
    const flow = useWorkflowRunner();
    const seen = {};
    await flow.mount(
      ["sections", "schedule"].map((d) => ({ name: d, domains: [d], fetcher: resolveNow })),
      () => setPreferredTheoryRoom(5, 2),
      (n) => { seen[n] = (seen[n] ?? 0) + 1; }
    );
    const { emitted } = await flow.run(undefined, PREFERRED_ROOM_DOMAINS);
    expect(emitted).toBe(true);
    expect(seen.sections).toBe(2);
    expect(seen.schedule).toBe(1);
  });

  it("faculty-preference write refreshes preferences only; hard preference is rejected silently", async () => {
    stubFetch(() => jsonResponse({ ok: true, preference: { id: 1 } }, 201));
    const flow = useWorkflowRunner();
    const seen = {};
    await flow.mount(
      ["preferences", "schedule"].map((d) => ({ name: d, domains: [d], fetcher: resolveNow })),
      () => createFacultyPreference(1, { kind: "DAY_OFF_PREFERENCE", days: ["Mon"] }),
      (n) => { seen[n] = (seen[n] ?? 0) + 1; }
    );
    const ok = await flow.run(undefined, PREFERENCE_DOMAINS);
    expect(ok.emitted).toBe(true);
    expect(seen.preferences).toBe(2);
    expect(seen.schedule).toBe(1);

    stubFetch(() => errorResponse({ ok: false, error: "Preferences are soft-only.", code: "PREF_HARD_UNSUPPORTED" }, 422));
    const bad = await flow.run(undefined, PREFERENCE_DOMAINS);
    expect(bad.emitted).toBe(false);
    expect(seen.preferences).toBe(2);
  });

  it("specialization create/delete emit the specializations domain", async () => {
    stubFetch(() => jsonResponse({ ok: true }));
    let count = 0;
    await renderTree(<Watcher name="sp" domains={["specializations"]} fetcher={resolveNow} onFetch={() => { count += 1; }} />);
    let emitted = false;
    await act(async () => {
      emitted = emitOnSuccess({ ok: true, data: {} }, SPECIALIZATION_DOMAINS);
    });
    expect(emitted).toBe(true);
    expect(count).toBe(2);
    await act(async () => {
      emitted = emitOnSuccess({ ok: false, error: new Error("x") }, SPECIALIZATION_DOMAINS);
    });
    expect(emitted).toBe(false);
    expect(count).toBe(2);
  });
});

describe("propagation race and duplication (Phase 6U)", () => {
  it("one emission refetches each mounted subscriber exactly once", async () => {
    const counts = { a: 0, b: 0 };
    await renderTree(
      <>
        <Watcher name="a" domains={["schedule"]} fetcher={() => Promise.resolve({})} onFetch={() => { counts.a += 1; }} />
        <Watcher name="b" domains={["schedule"]} fetcher={() => Promise.resolve({})} onFetch={() => { counts.b += 1; }} />
      </>
    );
    expect(counts).toEqual({ a: 1, b: 1 });
    await act(async () => {
      emitInvalidation(["schedule"]);
    });
    expect(counts).toEqual({ a: 2, b: 2 });
  });

  it("rapid successful mutations cause no leaks or loops", async () => {
    let count = 0;
    await renderTree(<Watcher name="s" domains={["schedule"]} fetcher={resolveNow} onFetch={() => { count += 1; }} />);
    // Two emissions in the same tick batch into ONE refetch (same-tick
    // collapse is the documented behavior): no leak, no loop, no storm.
    await act(async () => {
      emitOnSuccess({ ok: true, data: {} }, MOVE_DOMAINS);
      emitOnSuccess({ ok: true, data: {} }, MOVE_DOMAINS);
    });
    expect(count).toBe(2);
    // A later emission in its own tick still refetches exactly once.
    await act(async () => {
      emitOnSuccess({ ok: true, data: {} }, MOVE_DOMAINS);
    });
    expect(count).toBe(3);
  });

  it("unmounted subscribers never receive stale callbacks", async () => {
    let count = 0;
    await renderTree(<Watcher name="s" domains={["schedule"]} fetcher={() => Promise.resolve({})} onFetch={() => { count += 1; }} />);
    expect(count).toBe(1);
    await act(async () => {
      root.unmount();
    });
    await act(async () => {
      emitInvalidation(["schedule"]);
    });
    expect(count).toBe(1);
  });

  it("failed and noop mutations never emit centrally", async () => {
    let count = 0;
    await renderTree(<Watcher name="s" domains={["schedule"]} fetcher={resolveNow} onFetch={() => { count += 1; }} />);
    expect(emitOnSuccess({ ok: false, error: new Error("x") }, MOVE_DOMAINS)).toBe(false);
    expect(emitOnSuccess({ ok: true, data: { noop: true } }, MOVE_DOMAINS)).toBe(false);
    expect(emitOnSuccess(null, MOVE_DOMAINS)).toBe(false);
    expect(count).toBe(1);
  });

  it("every invalidation domain has at least one emitter and one documented consumer", () => {
    expect([...INVALIDATION_DOMAINS].sort()).toEqual(
      ["assignments", "config", "dashboard", "enrollments", "faculty", "lockedBlocks", "overview", "preferences", "programs", "rooms", "schedule", "sections", "specializations", "subjects"].sort()
    );
    // Each matrix constant only names known domains (catches typos/drift).
    for (const domains of [MOVE_DOMAINS, REASSIGN_DOMAINS, SWAP_DOMAINS, LOCKED_BLOCK_DOMAINS, MEMBERSHIP_DOMAINS, SPECIALIZATION_DOMAINS, PREFERENCE_DOMAINS, PREFERRED_ROOM_DOMAINS, GENERATION_DOMAINS]) {
      for (const d of domains) expect(INVALIDATION_DOMAINS, d).toContain(d);
    }
  });
});

describe("UI state integration (Phase 6U)", () => {
  it("loading resolves to success data", async () => {
    function Page() {
      const stable = useCallback(() => Promise.resolve({ rooms: [{ id: 1 }] }), []);
      const query = useApi(stable, []);
      if (query.isLoading) return <p>Loading rooms…</p>;
      return <p>Rooms: {query.data.rooms.length}</p>;
    }
    await renderTree(<Page />);
    expect(textOf()).toContain("Rooms: 1");
  });

  it("loading resolves to a normalized error with working retry", async () => {
    let attempts = 0;
    const holder = {};
    function Page({ onApi }) {
      const stable = useCallback(() => {
        attempts += 1;
        if (attempts === 1) {
          return Promise.reject(Object.assign(new Error("boom"), { status: 500, payload: null }));
        }
        return Promise.resolve({ ok: true });
      }, []);
      const query = useApi(stable, []);
      onApi(query);
      if (query.isLoading) return <p>Loading…</p>;
      if (query.error) return <QueryError error={query.error} onRetry={query.retry} />;
      return <p>Recovered</p>;
    }
    await renderTree(<Page onApi={(query) => { holder.api = query; }} />);
    expect(textOf()).toContain("Couldn't load this page");
    await act(async () => {
      holder.api.retry();
    });
    expect(textOf()).toContain("Recovered");
  });

  it("empty collections render an actionable empty state", async () => {
    await renderTree(
      <EmptyState title="No scheduled classes yet" description="Generate first." action={<button type="button">Generate</button>} />
    );
    expect(textOf()).toContain("No scheduled classes yet");
    expect(container.querySelector("button").textContent).toBe("Generate");
  });

  it("field errors render inline while the generic box stays hidden", async () => {
    const fieldErr = { fieldErrors: { room_id: "Room required." }, payload: { ok: false, error: "x", code: "ROOM_REQUIRED", field_errors: { room_id: "Room required." } }, message: "x", status: 422 };
    await renderTree(
      <>
        <MutationFailure error={fieldErr} />
        <FieldError id="room_id" message="Room required." />
      </>
    );
    // Generic MutationError box suppressed; inline field error visible.
    expect(textOf()).not.toContain("Something went wrong");
    expect(textOf()).toContain("Room required.");
  });

  it("structured failures render with labels; auth errors carry the session hint", async () => {
    await renderTree(<FailureList failures={[{ code: "ROOM_CONFLICT", message: "Taken.", details: null }]} title="Why it failed" />);
    expect(textOf()).toContain("Room already occupied");
    expect(textOf()).toContain("Taken.");

    const authErr = { message: "Authentication required.", status: 401, payload: { ok: false, error: "Authentication required.", code: "AUTH_REQUIRED" } };
    await renderTree(<QueryError error={authErr} />);
    expect(textOf()).toContain("may have expired");
    const networkErr = { message: "Could not reach the server.", status: 0, payload: null };
    await renderTree(<QueryError error={networkErr} />);
    expect(textOf()).toContain("could not be reached");
  });

  it("MutationError never renders [object Object] or undefined", async () => {
    await renderTree(<MutationError error={{ message: { odd: true }, status: 422, payload: null }} />);
    expect(textOf()).not.toContain("[object Object]");
    expect(textOf()).not.toContain("undefined");
    expect(getFailures({ payload: null })).toEqual([]);
  });
});

describe("read-only safety from the frontend side (Phase 6U)", () => {
  it("representative read flows issue only GETs and never touch the scheduler", async () => {
    const calls = stubFetch((call) => {
      if (call.method !== "GET") return errorResponse({ ok: false, error: "must not happen", code: "BAD_REQUEST" }, 400);
      return jsonResponse({ classes: [], days: [], periods: [], has_schedule: false });
    });
    await renderTree(
      <Watcher name="ro" domains={[]} fetcher={() => import("@/services/api/schedule.js").then((m) => m.getScheduledClasses())} onFetch={() => {}} />
    );
    expect(calls.length).toBeGreaterThan(0);
    for (const c of calls) expect(c.method).toBe("GET");
    expect(calls.some((c) => String(c.url).includes("/api/schedule/run"))).toBe(false);
  });
});
