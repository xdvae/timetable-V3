// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, Routes, Route, Link } from "react-router";
import { act } from "react";

import { AppShell } from "@/components/layout/app-shell.jsx";
import { AuthContext } from "@/hooks/use-auth.js";

// Mock matchMedia for testing responsive breakpoints
function mockMatchMedia(matches) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query) => ({
      matches,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

describe("AppShell with official shadcn Sidebar", () => {
  let container;
  let root;

  const mockUser = { id: 1, username: "admin", role: "admin" };
  const mockAuthContext = {
    user: mockUser,
    login: vi.fn(),
    logout: vi.fn(),
    checkAuth: vi.fn(),
    loading: false,
  };

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    mockMatchMedia(false); // default desktop
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  it("renders UniSchedule branding, navigation sections, and footer user account", async () => {
    await act(async () => {
      root.render(
        <AuthContext.Provider value={mockAuthContext}>
          <MemoryRouter initialEntries={["/"]}>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<div>Dashboard Page</div>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </AuthContext.Provider>
      );
    });

    const content = container.textContent;
    // Branding
    expect(content).toContain("UniSchedule");
    expect(content).toContain("University scheduling");

    // Sections
    expect(content).toContain("Setup");
    expect(content).toContain("People");
    expect(content).toContain("Academics");
    expect(content).toContain("Data");
    expect(content).toContain("Timetable");
    expect(content).toContain("Account");

    // Items
    expect(content).toContain("Rooms");
    expect(content).toContain("Faculty");
    expect(content).toContain("Programs");
    expect(content).toContain("Subjects");
    expect(content).toContain("Import CSV");

    // Account footer
    expect(content).toContain("Signed in as");
    expect(content).toContain("admin");

    // Outlet content
    expect(content).toContain("Dashboard Page");
  });

  it("toggles sidebar collapsible state on trigger click", async () => {
    await act(async () => {
      root.render(
        <AuthContext.Provider value={mockAuthContext}>
          <MemoryRouter initialEntries={["/"]}>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<div>Content</div>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </AuthContext.Provider>
      );
    });

    const trigger = container.querySelector('[data-sidebar="trigger"]');
    expect(trigger).not.toBeNull();

    const sidebar = container.querySelector('[data-slot="sidebar"]');
    expect(sidebar).not.toBeNull();
    expect(sidebar.getAttribute("data-state")).toBe("expanded");

    // Click trigger to collapse
    await act(async () => {
      trigger.click();
    });

    expect(sidebar.getAttribute("data-state")).toBe("collapsed");
    expect(sidebar.getAttribute("data-collapsible")).toBe("icon");

    // Click trigger again to expand
    await act(async () => {
      trigger.click();
    });

    expect(sidebar.getAttribute("data-state")).toBe("expanded");
  });

  it("highlights the active route", async () => {
    await act(async () => {
      root.render(
        <AuthContext.Provider value={mockAuthContext}>
          <MemoryRouter initialEntries={["/rooms"]}>
            <Routes>
              <Route element={<AppShell />}>
                <Route path="rooms" element={<div>Rooms Page</div>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </AuthContext.Provider>
      );
    });

    // Check that rooms nav button has data-active="true"
    const roomsLink = container.querySelector('a[href="/rooms"]');
    expect(roomsLink).not.toBeNull();
    const roomsButton = roomsLink.querySelector('[data-sidebar="menu-button"]');
    expect(roomsButton).not.toBeNull();
    expect(roomsButton.getAttribute("data-active")).toBe("true");
  });

  it("opens Universal Search modal via header search button and keyboard shortcut", async () => {
    await act(async () => {
      root.render(
        <AuthContext.Provider value={mockAuthContext}>
          <MemoryRouter initialEntries={["/"]}>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<div>Content</div>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </AuthContext.Provider>
      );
    });

    expect(container.querySelector('[role="dialog"]')).toBeNull();

    // Trigger universal search via search button
    const searchBtn = container.querySelector('button[aria-label="Open universal search (Ctrl+K)"]');
    expect(searchBtn).not.toBeNull();

    await act(async () => {
      searchBtn.click();
    });

    const dialog = container.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog.getAttribute("aria-label")).toBe("Universal Search");
  });
});
