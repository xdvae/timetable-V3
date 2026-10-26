// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BulkAssignDialog } from "@/pages/Assignments/BulkAssignDialog.jsx";
import { ToastContext } from "@/hooks/use-toast.js";
import { resetInvalidationForTests, subscribeInvalidation } from "@/lib/invalidation.js";
import * as assignmentsApi from "@/services/api/assignments.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const options = () => ({
  faculty: [
    { id: 1, name: "Vaibhav", weekly_load: 0, weekly_max_hours: 24 },
    { id: 2, name: "Dr. Khan", weekly_load: 10, weekly_max_hours: 24 },
  ],
  subjects: [
    { id: 10, name: "Business Computations", code: "BC1", enrollment_id: 100, program_name: "BBA", year_label: "1" },
    { id: 11, name: "Economics", code: "EC2", enrollment_id: 200, program_name: "BBA", year_label: "2" },
  ],
  sections: [
    { id: 1, name: "BBA-1-A", enrollment_id: 100, student_count: 63 },
    { id: 2, name: "BBA-1-B", enrollment_id: 100, student_count: 63 },
    { id: 3, name: "BBA-1-C", enrollment_id: 100, student_count: 62 },
    { id: 4, name: "BBA-2-A", enrollment_id: 200, student_count: 50 },
  ],
  labGroups: [
    { id: 21, name: "BBA-1-A-G1", section_id: 1, student_count: 32 },
    { id: 22, name: "BBA-1-A-G2", section_id: 1, student_count: 31 },
    { id: 23, name: "BBA-1-B-G1", section_id: 2, student_count: 32 },
    { id: 41, name: "BBA-2-A-G1", section_id: 4, student_count: 25 },
  ],
  subjectDefaults: { 10: { theory: 4, practical: 2, block: 2 } },
  assignments: [
    // BBA-1-A already has Business Computations theory with Dr. Khan.
    { id: 900, faculty_id: 2, faculty_name: "Dr. Khan", subject_id: 10, session_type: "theory", section_id: 1, lab_group_id: null },
  ],
});

describe("BulkAssignDialog", () => {
  let container;
  let root;
  let toast;

  beforeEach(() => {
    resetInvalidationForTests();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    toast = { success: vi.fn(), warning: vi.fn(), error: vi.fn() };
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  async function render(props = {}) {
    const onCreated = vi.fn();
    const onOpenChange = vi.fn();
    await act(async () => {
      root.render(
        <ToastContext.Provider value={toast}>
          <BulkAssignDialog open onOpenChange={onOpenChange} onCreated={onCreated} options={options()} {...props} />
        </ToastContext.Provider>
      );
    });
    return { onCreated, onOpenChange };
  }

  const dialog = () => document.querySelector("[role=dialog]");
  const tile = (name) =>
    [...dialog().querySelectorAll("label")].find((l) => l.querySelector("span span")?.textContent === name);
  const submit = () => dialog().querySelector("button[type=submit]");

  it("lists only the subject's own class sections and locks ones already taught", async () => {
    await render();
    const text = dialog().textContent;
    expect(text).toContain("Assign to BBA 1 sections");
    expect(text).toContain("BBA-1-B");
    expect(text).not.toContain("BBA-2-A");
    const taken = tile("BBA-1-A");
    expect(taken.textContent).toContain("Taught by Dr. Khan");
    expect(taken.querySelector("input").disabled).toBe(true);
    expect(submit().disabled).toBe(true);
  });

  it("select-all ticks every free section and submits them in one request", async () => {
    const spy = vi.spyOn(assignmentsApi, "createAssignmentsBulk").mockResolvedValue({
      ok: true, message: "Vaibhav now teaches …", category: "success", created: 2,
    });
    const events = [];
    subscribeInvalidation(["assignments"], (d) => events.push(d));
    const { onCreated, onOpenChange } = await render();

    const selectAll = [...dialog().querySelectorAll("label")].find((l) => l.textContent.includes("Select all"));
    expect(selectAll.textContent).toContain("Select all (2)");
    await act(async () => selectAll.querySelector("input").click());

    expect(submit().textContent).toBe("Assign to 2 sections");
    expect(dialog().textContent).toContain("Vaibhav: 0 → 8 hrs/week");

    await act(async () => submit().click());
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy.mock.calls[0][0]).toEqual({
      faculty_id: "1",
      subject_id: "10",
      session_type: "theory",
      periods_per_week: "4",
      block_length: "1",
      section_ids: [2, 3],
      lab_group_ids: [],
    });
    expect(toast.success).toHaveBeenCalled();
    expect(onCreated).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(events).toHaveLength(1);
  });

  it("lab mode groups lab groups by section with a per-section toggle", async () => {
    const spy = vi.spyOn(assignmentsApi, "createAssignmentsBulk").mockResolvedValue({ ok: true, created: 2 });
    await render();
    const labRadio = [...dialog().querySelectorAll("[role=radio]")].find((b) => b.textContent === "Lab");
    await act(async () => labRadio.click());

    expect(dialog().textContent).toContain("Assign to BBA 1 lab groups");
    expect(dialog().querySelector("#assignment-periods").value).toBe("2");
    expect(dialog().querySelector("#assignment-block").value).toBe("2");
    expect(dialog().textContent).not.toContain("BBA-2-A-G1");

    const sectionToggle = dialog().querySelector('input[aria-label="All lab groups of BBA-1-A"]');
    await act(async () => sectionToggle.click());
    expect(submit().textContent).toBe("Assign to 2 lab groups");

    await act(async () => submit().click());
    expect(spy.mock.calls[0][0]).toMatchObject({
      session_type: "practical",
      section_ids: [],
      lab_group_ids: [21, 22],
      periods_per_week: "2",
      block_length: "2",
    });
  });

  it("warns before going over the teacher's weekly limit", async () => {
    await render();
    const hours = dialog().querySelector("#assignment-periods");
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    await act(async () => {
      setter.call(hours, "13");
      hours.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => tile("BBA-1-B").querySelector("input").click());
    await act(async () => tile("BBA-1-C").querySelector("input").click());
    expect(dialog().textContent).toContain("0 → 26 hrs/week (limit 24)");
  });
});
