// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { FailureList, FieldError, MutationError, MutationFailure } from "@/components/feedback/mutation.jsx";
import { QueryError } from "@/components/feedback/data-states.jsx";
import { ApiError } from "@/services/api/client.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function render(element) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return {
    container,
    async mount() {
      await act(async () => {
        root.render(element);
      });
    },
    async cleanup() {
      await act(async () => {
        root.unmount();
      });
      container.remove();
    },
  };
}

describe("error presentation (Phase 6Q)", () => {
  let views = [];
  beforeEach(() => {
    views = [];
  });
  afterEach(async () => {
    for (const view of views) await view.cleanup();
  });
  async function show(element) {
    const view = render(element);
    views.push(view);
    await view.mount();
    return view.container;
  }

  it("MutationError renders a safe message for object errors", async () => {
    const container = await show(<MutationError error={{ message: { evil: 1 }, status: 500 }} />);
    expect(container.textContent).not.toContain("[object Object]");
    expect(container.textContent).toContain("Something went wrong");
  });

  it("MutationError renders ApiError messages verbatim", async () => {
    const err = new ApiError("Room is taken.", { status: 422, payload: { error: "Room is taken." } });
    const container = await show(<MutationError error={err} />);
    expect(container.textContent).toContain("Room is taken.");
  });

  it("MutationError renders nothing without an error", async () => {
    const container = await show(<MutationError error={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("MutationFailure prefers FailureList for structured failures", async () => {
    const err = new ApiError("Blocked.", {
      status: 422,
      payload: { error: "Blocked.", failures: [{ code: "ROOM_CONFLICT", message: "Taken." }] },
    });
    const container = await show(<MutationFailure error={err} />);
    expect(container.textContent).toContain("Room already occupied");
    expect(container.textContent).toContain("Taken.");
  });

  it("MutationFailure hides the generic box when field errors exist", async () => {
    const err = new ApiError("Bad input.", {
      status: 422,
      fieldErrors: { name: "Required." },
      payload: { error: "Bad input.", field_errors: { name: "Required." } },
    });
    const container = await show(<MutationFailure error={err} />);
    expect(container.innerHTML).toBe("");
  });

  it("FailureList renders unknown codes with a safe fallback", async () => {
    const container = await show(
      <FailureList failures={[{ code: "FUTURE_CODE", message: "Future problem." }]} />
    );
    expect(container.textContent).toContain("FUTURE_CODE");
    expect(container.textContent).toContain("Future problem.");
  });

  it("FailureList renders plain-string entries (import row errors)", async () => {
    const container = await show(<FailureList failures={["Row 2: bad capacity"]} />);
    expect(container.textContent).toContain("Row 2: bad capacity");
  });

  it("FailureList renders scheduler context without crashing", async () => {
    const container = await show(
      <FailureList
        failures={[
          {
            code: "SCHEDULING_INFEASIBLE",
            message: "Locked placements leave no feasible schedule.",
            details: { locked_block_ids: [3] },
          },
        ]}
      />
    );
    expect(container.textContent).toContain("No feasible schedule");
  });

  it("FieldError coerces non-string messages", async () => {
    const container = await show(<FieldError id="f" message={["a", "b"]} />);
    expect(container.textContent).not.toContain("[object Object]");
  });

  it("QueryError distinguishes network failures with retry", async () => {
    const err = new ApiError("Could not reach the server.", { status: 0 });
    let retried = 0;
    const container = await show(<QueryError error={err} onRetry={() => { retried += 1; }} />);
    expect(container.textContent).toContain("could not be reached");
    container.querySelector("button").click();
    expect(retried).toBe(1);
  });

  it("QueryError hints at expired sessions for 401", async () => {
    const err = new ApiError("Authentication required.", {
      status: 401,
      payload: { error: "Authentication required.", code: "AUTH_REQUIRED" },
    });
    const container = await show(<QueryError error={err} onRetry={() => {}} />);
    expect(container.textContent).toContain("session may have expired");
  });

  it("QueryError never shows undefined/null primary text", async () => {
    const container = await show(<QueryError error={{ status: 500 }} onRetry={() => {}} />);
    expect(container.textContent).not.toMatch(/undefined|null/);
    expect(container.textContent).toContain("Couldn't load");
  });
});
