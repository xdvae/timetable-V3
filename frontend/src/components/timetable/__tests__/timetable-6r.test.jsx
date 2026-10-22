// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { TimetableClassBlock } from "@/components/timetable/TimetableClassBlock.jsx";
import { TimetableGrid } from "@/components/timetable/TimetableGrid.jsx";
import { TimetableLegend } from "@/components/timetable/TimetableLegend.jsx";
import {
  filterDayRows,
  groupLabel,
  isLocked,
  isMovable,
  isSpecialization,
  summarizeDayRows,
  summarizeEditorClasses,
  todayAbbrev,
} from "@/components/timetable/timetable-helpers.js";
import { FailureList } from "@/components/feedback/mutation.jsx";
import { normalizeFailure } from "@/lib/failures.js";

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

function cell(overrides = {}) {
  return {
    assignment_id: 1,
    subject: "Algebra",
    faculty: "F1",
    group: "BCA-1-A",
    room: "R101",
    session_type: "theory",
    kind: "Theory",
    css_class: "cell-theory",
    start_period: 0,
    length: 1,
    day: "Mon",
    is_locked: false,
    locked_block_id: null,
    specialization_id: null,
    specialization: null,
    ...overrides,
  };
}

describe("timetable helpers (Phase 6R)", () => {
  it("todayAbbrev maps JS weekdays to backend abbreviations", () => {
    // 2026-09-28 is a Monday; 2026-10-04 is a Sunday.
    expect(todayAbbrev(new Date(2026, 8, 28))).toBe("Mon");
    expect(todayAbbrev(new Date(2026, 9, 4))).toBe("Sun");
    expect(todayAbbrev(null)).toBe(null);
    expect(todayAbbrev("nonsense")).toBe(null);
  });

  it("lock/spec/movable predicates agree with the editor rules", () => {
    const plain = { section: "A" };
    const locked = { section: "A", is_locked: true };
    const lockLinked = { section: "A", locked_block_id: 7 };
    const spec = { section: "A", specialization_id: 3, specialization: "Cyber" };
    const slotLinked = { section: "A", slot_id: 9 };
    expect(isMovable(plain)).toBe(true);
    expect(isLocked(locked)).toBe(true);
    expect(isLocked(lockLinked)).toBe(true);
    expect(isSpecialization(spec)).toBe(true);
    expect(isSpecialization(slotLinked)).toBe(true);
    expect(isMovable(locked)).toBe(false);
    expect(isMovable(spec)).toBe(false);
    expect(isMovable(null)).toBe(false);
    expect(groupLabel({ specialization: "Cyber" })).toBe("Cyber");
    expect(groupLabel({ lab_group: "L1" })).toBe("L1");
    expect(groupLabel({ section: "S1" })).toBe("S1");
    expect(groupLabel({})).toBe("?");
  });

  it("filterDayRows only hides rows locally", () => {
    const rows = [{ day: "Mon", lanes: [] }, { day: "Tue", lanes: [] }];
    expect(filterDayRows(rows, "all")).toEqual(rows);
    expect(filterDayRows(rows, "Mon")).toEqual([{ day: "Mon", lanes: [] }]);
    expect(filterDayRows(rows, "Wed")).toEqual([]);
    expect(filterDayRows(null, "Mon")).toEqual([]);
  });

  it("summarizeDayRows counts kinds without touching data", () => {
    const rows = [
      {
        day: "Mon",
        lanes: [
          [
            { empty: true, colspan: 1 },
            { empty: false, colspan: 2, class: cell() },
            { empty: false, colspan: 1, class: cell({ session_type: "practical", kind: "Lab", length: 2 }) },
          ],
          [{ empty: false, colspan: 3, class: cell({ is_locked: true, locked_block_id: 4 }) }],
        ],
      },
      {
        day: "Tue",
        lanes: [[{ empty: false, colspan: 1, class: cell({ specialization_id: 2, specialization: "AI" }) }]],
      },
    ];
    expect(summarizeDayRows(rows)).toEqual({
      total: 4, theory: 3, lab: 1, multi: 1, fixed: 1, spec: 1,
    });
    expect(summarizeDayRows([])).toEqual({
      total: 0, theory: 0, lab: 0, multi: 0, fixed: 0, spec: 0,
    });
  });

  it("summarizeEditorClasses splits movable/fixed/spec", () => {
    const classes = [
      { id: 1, length: 1, section: "A" },
      { id: 2, length: 2, section: "A" },
      { id: 3, length: 1, section: "A", is_locked: true },
      { id: 4, length: 1, section: "A", specialization_id: 5 },
    ];
    expect(summarizeEditorClasses(classes)).toEqual({
      total: 4, movable: 2, fixed: 1, spec: 1, multi: 1,
    });
  });
});

describe("timetable cards and legend (Phase 6R)", () => {
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

  it("renders theory/lab state as text, never color alone", async () => {
    const theory = await show(<TimetableClassBlock classInfo={cell()} />);
    expect(theory.textContent).toContain("Theory");
    const lab = await show(
      <TimetableClassBlock classInfo={cell({ session_type: "practical", kind: "Lab" })} />
    );
    expect(lab.textContent).toContain("Lab");
  });

  it("badges multi-period, fixed, and specialization state", async () => {
    const multi = await show(<TimetableClassBlock classInfo={cell({ length: 3 })} />);
    expect(multi.textContent).toContain("× 3 periods");
    const fixed = await show(<TimetableClassBlock classInfo={cell({ is_locked: true })} />);
    expect(fixed.textContent).toContain("Fixed");
    const spec = await show(
      <TimetableClassBlock classInfo={cell({ specialization_id: 2, specialization: "Cyber" })} />
    );
    expect(spec.textContent).toContain("Spec");
    expect(spec.textContent).toContain("Cyber");
  });

  it("locked wins over spec and unknown values pass through safely", async () => {
    const both = await show(
      <TimetableClassBlock
        classInfo={cell({ is_locked: true, specialization_id: 2, specialization: "Cyber" })}
      />
    );
    expect(both.textContent).toContain("Fixed");
    expect(both.textContent).not.toContain("Spec");
    const unknown = await show(<TimetableClassBlock classInfo={cell({ subject: "?" })} />);
    expect(unknown.textContent).toContain("?");
    expect(unknown.innerHTML).not.toContain("undefined");
  });

  it("legend names every card state in words", async () => {
    const container = await show(<TimetableLegend />);
    for (const word of ["Theory", "Lab", "Fixed", "Specialization", "Multi-period"]) {
      expect(container.textContent).toContain(word);
    }
  });

  it("grid highlights today only when it matches a backend day", async () => {
    const rows = [
      { day: "Mon", lanes: [[{ empty: false, colspan: 1, class: cell() }]] },
      { day: "Tue", lanes: [[{ empty: true, colspan: 1 }]] },
    ];
    const withToday = await show(
      <TimetableGrid periods={["08:00"]} dayRows={rows} labelledBy="h" today="Mon" />
    );
    expect(withToday.textContent).toContain("Today");
    const withoutToday = await show(
      <TimetableGrid periods={["08:00"]} dayRows={rows} labelledBy="h" today="Sun" />
    );
    expect(withoutToday.textContent).not.toContain("Today");
    const noToday = await show(
      <TimetableGrid periods={["08:00"]} dayRows={rows} labelledBy="h" today={null} />
    );
    expect(noToday.textContent).not.toContain("Today");
  });
});

describe("move-conflict presentation stays normalized (Phase 6R)", () => {
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

  it("unknown future codes remain safely renderable", async () => {
    const container = await show(
      <FailureList
        failures={[{ code: "FUTURE_CODE_X1", message: "Blocked.", details: { day: "Mon", period: 2 } }]}
        title="Move is not valid — nothing was changed"
      />
    );
    expect(container.textContent).toContain("FUTURE_CODE_X1");
    expect(container.textContent).toContain("Blocked.");
    expect(container.textContent).toContain("Day Mon");
  });

  it("malformed and empty failures never crash the UI", async () => {
    const empty = await show(<FailureList failures={[]} title="t" />);
    expect(empty.innerHTML).toBe("");
    expect(normalizeFailure(undefined).message).toBeTruthy();
    expect(normalizeFailure(null).message).toBeTruthy();
    // Nested-object messages degrade to JSON, never "[object Object]".
    expect(normalizeFailure({ message: { evil: 1 } }).message).not.toContain("[object Object]");
    expect(
      normalizeFailure({ status: 500, payload: { error: { message: { evil: 1 } } } }).message
    ).not.toContain("[object Object]");
  });
});
