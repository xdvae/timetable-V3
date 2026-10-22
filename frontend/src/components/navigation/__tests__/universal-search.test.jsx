// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";

import { UniversalSearchModal } from "@/components/navigation/UniversalSearchModal.jsx";
import * as roomsApi from "@/services/api/rooms.js";
import * as facultyApi from "@/services/api/faculty.js";
import * as programsApi from "@/services/api/programs.js";
import * as enrollmentsApi from "@/services/api/enrollments.js";
import * as subjectsApi from "@/services/api/subjects.js";
import * as assignmentsApi from "@/services/api/assignments.js";
import * as specsApi from "@/services/api/specializations.js";
import * as scheduleApi from "@/services/api/schedule.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mockRooms = [
  { id: 1, name: "101", room_type: "theory", capacity: 60, equipment_count: null },
  { id: 2, name: "Lab A", room_type: "lab", capacity: 30, equipment_count: 30 },
];

const mockFaculty = [
  { id: 10, name: "Dr. Sharma", department: "Computer Science", faculty_type: "regular", weekly_load: 12, weekly_max_hours: 24 },
  { id: 11, name: "Prof. Gupta", department: "Mathematics", faculty_type: "visiting", weekly_load: 6, weekly_max_hours: 12 },
];

const mockPrograms = [
  { id: 100, name: "BCA", department: "Computer Applications" },
];

const mockEnrollments = {
  enrollments: [
    { id: 200, program_id: 100, program_name: "BCA", year_label: "1st Year", total_students: 60 },
  ],
};

const mockSubjects = {
  subjects: [
    { id: 300, code: "CS101", name: "Data Structures", program_name: "BCA", year_label: "1st Year", credits: 4, theory_hours_per_week: 3, practical_hours_per_week: 2 },
  ],
};

const mockAssignments = {
  assignments: [
    { id: 400, faculty_id: 10, faculty_name: "Dr. Sharma", subject_id: 300, subject_name: "Data Structures", session_type: "theory", group: "BCA-1-A", periods_per_week: 3, block_length: 1 },
  ],
  sections: [
    { id: 500, name: "BCA-1-A", student_count: 60 },
  ],
};

const mockSpecializations = {
  specializations: [
    { id: 600, name: "Cyber Security", session_type: "theory", periods_per_week: 2, enrollment_id: 200 },
  ],
};

const mockScheduledClasses = {
  classes: [
    { id: 700, assignment_id: 400, day: "Mon", start_period: 0, length: 1, room: "101", room_id: 1, subject: "Data Structures", faculty: "Dr. Sharma", faculty_id: 10, section: "BCA-1-A", section_id: 500, is_locked: false },
  ],
};

describe("UniversalSearchModal", () => {
  let container;
  let root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    vi.spyOn(roomsApi, "getRooms").mockResolvedValue(mockRooms);
    vi.spyOn(facultyApi, "getFaculty").mockResolvedValue(mockFaculty);
    vi.spyOn(programsApi, "getPrograms").mockResolvedValue(mockPrograms);
    vi.spyOn(enrollmentsApi, "getEnrollments").mockResolvedValue(mockEnrollments);
    vi.spyOn(subjectsApi, "getSubjects").mockResolvedValue(mockSubjects);
    vi.spyOn(assignmentsApi, "getAssignments").mockResolvedValue(mockAssignments);
    vi.spyOn(specsApi, "getSpecializations").mockResolvedValue(mockSpecializations);
    vi.spyOn(scheduleApi, "getScheduledClasses").mockResolvedValue(mockScheduledClasses);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  it("does not render when closed", () => {
    act(() => {
      root.render(
        <MemoryRouter>
          <UniversalSearchModal open={false} onOpenChange={() => {}} />
        </MemoryRouter>
      );
    });

    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });

  it("renders search dialog and fetches authoritative data when opened", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <UniversalSearchModal open={true} onOpenChange={() => {}} />
        </MemoryRouter>
      );
    });

    const dialog = container.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog.getAttribute("aria-label")).toBe("Universal Search");

    expect(roomsApi.getRooms).toHaveBeenCalled();
    expect(facultyApi.getFaculty).toHaveBeenCalled();
    expect(programsApi.getPrograms).toHaveBeenCalled();
    expect(enrollmentsApi.getEnrollments).toHaveBeenCalled();
    expect(subjectsApi.getSubjects).toHaveBeenCalled();
    expect(assignmentsApi.getAssignments).toHaveBeenCalled();
    expect(specsApi.getSpecializations).toHaveBeenCalled();
    expect(scheduleApi.getScheduledClasses).toHaveBeenCalled();
  });

  it("filters and groups universal results across categories", async () => {
    vi.useFakeTimers();

    await act(async () => {
      root.render(
        <MemoryRouter>
          <UniversalSearchModal open={true} onOpenChange={() => {}} />
        </MemoryRouter>
      );
    });

    const input = container.querySelector("#universal-search-gooey-input");
    expect(input).not.toBeNull();

    // Type query matching Dr. Sharma
    act(() => {
      input.value = "Sharma";
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });

    act(() => {
      vi.advanceTimersByTime(200);
    });

    // Check if faculty and teaching assignments are found and grouped
    const contentText = container.textContent;
    expect(contentText).toContain("Dr. Sharma");
    expect(contentText).toContain("Faculty");
    expect(contentText).toContain("Teaching Assignments");

    vi.useRealTimers();
  });

  it("filters navigation pages correctly", async () => {
    vi.useFakeTimers();

    await act(async () => {
      root.render(
        <MemoryRouter>
          <UniversalSearchModal open={true} onOpenChange={() => {}} />
        </MemoryRouter>
      );
    });

    const input = container.querySelector("#universal-search-gooey-input");

    act(() => {
      input.value = "Editor";
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });

    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(container.textContent).toContain("Pages & Navigation");
    expect(container.textContent).toContain("Editor");

    vi.useRealTimers();
  });

  it("handles empty results gracefully", async () => {
    vi.useFakeTimers();

    await act(async () => {
      root.render(
        <MemoryRouter>
          <UniversalSearchModal open={true} onOpenChange={() => {}} />
        </MemoryRouter>
      );
    });

    const input = container.querySelector("#universal-search-gooey-input");

    act(() => {
      input.value = "NonExistentEntity999";
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });

    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(container.textContent).toContain("No results found");

    vi.useRealTimers();
  });

  it("closes on Escape key press", async () => {
    const onOpenChange = vi.fn();

    await act(async () => {
      root.render(
        <MemoryRouter>
          <UniversalSearchModal open={true} onOpenChange={onOpenChange} />
        </MemoryRouter>
      );
    });

    const dialog = container.querySelector('[role="dialog"]');
    act(() => {
      dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
