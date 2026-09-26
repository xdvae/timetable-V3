// @vitest-environment jsdom
import { act, useCallback } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useApi } from "@/hooks/use-api.js";
import { emitInvalidation, resetInvalidationForTests } from "@/lib/invalidation.js";
import {
  ASSIGNMENT_WRITE_DOMAINS,
  GENERATION_DOMAINS,
  IMPORT_WORKLOAD_DOMAINS,
  LOCKED_BLOCK_DOMAINS,
  MEMBERSHIP_DOMAINS,
  MOVE_DOMAINS,
  PREFERENCE_DOMAINS,
  PREFERRED_ROOM_DOMAINS,
  REASSIGN_DOMAINS,
  SPECIALIZATION_DOMAINS,
  SWAP_DOMAINS,
} from "@/lib/propagation.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ALL_SINGLE = [
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
];

function Consumer({ name, domains, onFetch }) {
  // Stable fetcher identity: useApi refetches whenever `fetcher` changes,
  // so an inline arrow here would loop forever.
  const fetcher = useCallback(() => {
    onFetch(name);
    return Promise.resolve({ name });
  }, [name, onFetch]);
  useApi(fetcher, domains);
  return null;
}

describe("cross-surface propagation matrix (Phase 6P.4)", () => {
  let container;
  let root;
  let counters;
  let onFetch;

  beforeEach(async () => {
    resetInvalidationForTests();
    counters = Object.fromEntries([...ALL_SINGLE, "lockedPage"].map((name) => [name, 0]));
    // Plain (non-component) recorder: mutating this test-local object here
    // is fine — only component/hook bodies forbid prop mutation.
    onFetch = (name) => {
      counters[name] += 1;
    };
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(
        <>
          {ALL_SINGLE.map((name) => (
            <Consumer key={name} name={name} domains={[name]} onFetch={onFetch} />
          ))}
          {/* Mirrors LockedBlocksPage: one query over four reads. */}
          <Consumer
            name="lockedPage"
            domains={["lockedBlocks", "assignments", "rooms", "config"]}
            onFetch={onFetch}
          />
        </>
      );
    });
    for (const name of Object.keys(counters)) expect(counters[name]).toBe(1);
    for (const name of Object.keys(counters)) counters[name] = 0;
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  async function emitAndSnapshot(domains) {
    await act(async () => {
      emitInvalidation(domains);
    });
    return { ...counters };
  }

  function refetched(snapshot) {
    return Object.keys(snapshot).filter((name) => snapshot[name] === 1).sort();
  }

  function expectExact(snapshot, names) {
    expect(refetched(snapshot)).toEqual([...names].sort());
    for (const count of Object.values(snapshot)) expect(count).toBeLessThanOrEqual(1);
  }

  it("move class → schedule surfaces only", async () => {
    expectExact(await emitAndSnapshot(MOVE_DOMAINS), ["schedule"]);
  });

  it("reassign faculty → assignments + schedule + faculty + overview (+ locked page via assignments)", async () => {
    expectExact(await emitAndSnapshot(REASSIGN_DOMAINS), [
      "assignments",
      "faculty",
      "lockedPage",
      "overview",
      "schedule",
    ]);
  });

  it("swap faculty → same surfaces as reassignment", async () => {
    expectExact(await emitAndSnapshot(SWAP_DOMAINS), [
      "assignments",
      "faculty",
      "lockedPage",
      "overview",
      "schedule",
    ]);
  });

  it("assignment create/delete → assignments + overview (+ locked page)", async () => {
    expectExact(await emitAndSnapshot(ASSIGNMENT_WRITE_DOMAINS), [
      "assignments",
      "lockedPage",
      "overview",
    ]);
  });

  it("specialization membership → specializations + sections; schedule untouched", async () => {
    expectExact(await emitAndSnapshot(MEMBERSHIP_DOMAINS), ["sections", "specializations"]);
  });

  it("specialization create/delete → specializations only", async () => {
    expectExact(await emitAndSnapshot(SPECIALIZATION_DOMAINS), ["specializations"]);
  });

  it("locked block create/delete → fixed blocks + schedule + assignments (+ locked page)", async () => {
    expectExact(await emitAndSnapshot(LOCKED_BLOCK_DOMAINS), [
      "assignments",
      "lockedBlocks",
      "lockedPage",
      "schedule",
    ]);
  });

  it("preferred room → sections only; existing schedule unchanged", async () => {
    expectExact(await emitAndSnapshot(PREFERRED_ROOM_DOMAINS), ["sections"]);
  });

  it("faculty preference → preferences only; existing schedule unchanged", async () => {
    expectExact(await emitAndSnapshot(PREFERENCE_DOMAINS), ["preferences"]);
  });

  it("workload import → every domain the importer writes (+ locked page via assignments)", async () => {
    expectExact(await emitAndSnapshot(IMPORT_WORKLOAD_DOMAINS), [
      "assignments",
      "enrollments",
      "faculty",
      "lockedPage",
      "overview",
      "programs",
      "sections",
      "subjects",
    ]);
  });

  it("generate schedule → all schedule-dependent consumers, no config-only domain", async () => {
    expectExact(await emitAndSnapshot(GENERATION_DOMAINS), [
      "assignments",
      "dashboard",
      "lockedBlocks",
      "lockedPage",
      "overview",
      "schedule",
      "specializations",
    ]);
  });
});
