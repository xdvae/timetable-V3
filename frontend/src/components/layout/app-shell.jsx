import { useState, useEffect } from "react";
import { Link, Outlet } from "react-router";
import { CalendarRange, Search } from "lucide-react";

import { AppSidebar } from "@/components/navigation/sidebar.jsx";
import { UniversalSearchModal } from "@/components/navigation/UniversalSearchModal.jsx";
import { Button } from "@/components/ui/button.jsx";
import { SidebarProvider, SidebarTrigger, SidebarInset } from "@/components/ui/sidebar.jsx";

/**
 * Shared application shell using official shadcn Sidebar components:
 * - SidebarProvider manages collapsible state, mobile drawer, and keyboard shortcut (Ctrl/Cmd+B).
 * - AppSidebar renders shadcn Sidebar in 'icon' collapsible mode.
 * - SidebarTrigger is positioned prominently in the sticky top header for seamless collapsing.
 * - Houses the Universal Gooey Search trigger and modal with Ctrl+K / Cmd+K shortcut.
 */
export function AppShell() {
  const [searchOpen, setSearchOpen] = useState(false);

  // Global keyboard shortcut for universal search: Ctrl+K / Cmd+K
  useEffect(() => {
    function handleKeyDown(e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setSearchOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <SidebarProvider defaultOpen={true}>
      <div className="flex min-h-svh w-full bg-paper">
        {/* Official shadcn Sidebar with icon collapsible rail and mobile drawer support */}
        <AppSidebar onOpenSearch={() => setSearchOpen(true)} />

        {/* Content area that fluidly resizes when sidebar expands or collapses */}
        <SidebarInset className="flex flex-1 flex-col bg-paper min-w-0">
          {/* Top navigation bar with SidebarTrigger and Universal Search */}
          <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between border-b border-line bg-panel/95 px-4 backdrop-blur-sm transition-[width,height] ease-linear">
            <div className="flex items-center gap-2">
              <SidebarTrigger
                className="size-8 text-ink-soft hover:bg-black/5 hover:text-ink focus-visible:ring-2 focus-visible:ring-brass"
                aria-label="Toggle navigation sidebar"
              />
              <div className="h-4 w-px bg-line/80 mx-1 md:hidden" aria-hidden="true" />
              <Link
                to="/"
                className="flex items-center gap-2 font-display font-semibold text-ink no-underline md:hidden"
              >
                <CalendarRange className="size-5 text-brass" aria-hidden="true" />
                <span>UniSchedule</span>
              </Link>
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setSearchOpen(true)}
                aria-label="Open universal search (Ctrl+K)"
                className="gap-2 border-line bg-white text-ink-soft hover:bg-neutral-50 hover:text-ink shadow-xs"
              >
                <Search className="size-3.5 text-ink-soft" aria-hidden="true" />
                <span className="hidden sm:inline text-xs font-normal text-ink-soft">Search UniSchedule...</span>
                <kbd className="hidden sm:inline-flex items-center rounded border border-line bg-muted px-1.5 py-0.5 text-[10px] font-mono text-ink-soft">
                  ⌘K
                </kbd>
              </Button>
            </div>
          </header>

          {/* Page content */}
          <main className="flex-1 p-0 min-w-0">
            <Outlet />
          </main>
        </SidebarInset>

        {/* Universal Search Modal */}
        <UniversalSearchModal open={searchOpen} onOpenChange={setSearchOpen} />
      </div>
    </SidebarProvider>
  );
}
