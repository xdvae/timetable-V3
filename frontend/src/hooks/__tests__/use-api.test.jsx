// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useApi } from "@/hooks/use-api.js";
import { emitInvalidation, resetInvalidationForTests } from "@/lib/invalidation.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function Probe({ fetcher, domains, onApi }) {
  const api = useApi(fetcher, domains);
  onApi(api);
  return null;
}

function countingFetcher(calls, failFirst = false) {
  return () => {
    calls.push(1);
    if (failFirst && calls.length === 1) return Promise.reject(new Error("boom"));
    return Promise.resolve({ n: calls.length });
  };
}

describe("useApi invalidation subscription (Phase 6P.3)", () => {
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
  });

  async function renderProbe(props) {
    let api = null;
    await act(async () => {
      root.render(
        <Probe {...props} onApi={(next) => { api = next; }} />
      );
    });
    return () => api;
  }

  it("fetches on mount and refetches when a subscribed domain emits", async () => {
    const calls = [];
    const getApi = await renderProbe({ fetcher: countingFetcher(calls), domains: ["schedule"] });
    expect(calls.length).toBe(1);
    await act(async () => {
      emitInvalidation(["schedule"]);
    });
    expect(calls.length).toBe(2);
    expect(getApi().data).toEqual({ n: 2 });
    expect(getApi().isLoading).toBe(false);
  });

  it("ignores emissions for unrelated domains", async () => {
    const calls = [];
    await renderProbe({ fetcher: countingFetcher(calls), domains: ["preferences"] });
    expect(calls.length).toBe(1);
    await act(async () => {
      emitInvalidation(["schedule"]);
    });
    expect(calls.length).toBe(1);
  });

  it("refetches exactly once for a multi-domain emission matching twice", async () => {
    const calls = [];
    await renderProbe({ fetcher: countingFetcher(calls), domains: ["schedule", "overview"] });
    expect(calls.length).toBe(1);
    await act(async () => {
      emitInvalidation(["schedule", "overview"]);
    });
    expect(calls.length).toBe(2);
  });

  it("does not refetch after unmount and does not leak the subscription", async () => {
    const calls = [];
    await renderProbe({ fetcher: countingFetcher(calls), domains: ["schedule"] });
    expect(calls.length).toBe(1);
    await act(async () => {
      root.unmount();
    });
    await act(async () => {
      emitInvalidation(["schedule"]);
    });
    expect(calls.length).toBe(1);
  });

  it("does not create duplicate subscriptions across rerenders", async () => {
    const calls = [];
    const props = { fetcher: countingFetcher(calls), domains: ["schedule"] };
    let api = null;
    await act(async () => {
      root.render(<Probe {...props} onApi={(next) => { api = next; }} />);
    });
    await act(async () => {
      root.render(<Probe {...props} onApi={(next) => { api = next; }} />);
    });
    await act(async () => {
      root.render(<Probe {...props} onApi={(next) => { api = next; }} />);
    });
    expect(calls.length).toBe(1);
    expect(api).not.toBe(null);
    await act(async () => {
      emitInvalidation(["schedule"]);
    });
    expect(calls.length).toBe(2);
  });

  it("resubscribes when the domain set changes", async () => {
    const calls = [];
    const fetcher = countingFetcher(calls);
    let api = null;
    await act(async () => {
      root.render(<Probe fetcher={fetcher} domains={["schedule"]} onApi={(next) => { api = next; }} />);
    });
    expect(api).not.toBe(null);
    await act(async () => {
      root.render(<Probe fetcher={fetcher} domains={["overview"]} onApi={(next) => { api = next; }} />);
    });
    await act(async () => {
      emitInvalidation(["schedule"]);
    });
    expect(calls.length).toBe(1);
    await act(async () => {
      emitInvalidation(["overview"]);
    });
    expect(calls.length).toBe(2);
  });

  it("manual retry still works alongside the subscription", async () => {
    const calls = [];
    const getApi = await renderProbe({ fetcher: countingFetcher(calls), domains: ["schedule"] });
    await act(async () => {
      getApi().retry();
    });
    expect(calls.length).toBe(2);
    await act(async () => {
      emitInvalidation(["schedule"]);
    });
    expect(calls.length).toBe(3);
  });

  it("local retry and central emission in the same tick collapse to one GET", async () => {
    const calls = [];
    const getApi = await renderProbe({ fetcher: countingFetcher(calls), domains: ["schedule"] });
    expect(calls.length).toBe(1);
    await act(async () => {
      getApi().retry();
      emitInvalidation(["schedule"]);
    });
    expect(calls.length).toBe(2);
  });

  it("preserves loading and error behavior with subscriptions active", async () => {
    const calls = [];
    const getApi = await renderProbe({ fetcher: countingFetcher(calls, true), domains: ["schedule"] });
    expect(calls.length).toBe(1);
    expect(getApi().error?.message).toBe("boom");
    expect(getApi().isLoading).toBe(false);
    await act(async () => {
      getApi().retry();
    });
    expect(calls.length).toBe(2);
    expect(getApi().error).toBe(null);
    expect(getApi().data).toEqual({ n: 2 });
  });

  it("works with the object form { invalidateOn }", async () => {
    const calls = [];
    await renderProbe({ fetcher: countingFetcher(calls), domains: { invalidateOn: ["rooms"] } });
    await act(async () => {
      emitInvalidation(["rooms"]);
    });
    expect(calls.length).toBe(2);
  });

  it("works without domains exactly like before Phase 6P", async () => {
    const calls = [];
    const getApi = await renderProbe({ fetcher: countingFetcher(calls) });
    expect(calls.length).toBe(1);
    await act(async () => {
      emitInvalidation(["schedule"]);
    });
    expect(calls.length).toBe(1);
    await act(async () => {
      getApi().retry();
    });
    expect(calls.length).toBe(2);
  });
});
