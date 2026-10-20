import { useState, useEffect } from "react";
import { Link, Outlet } from "react-router";
import { CalendarRange, Menu, Search } from "lucide-react";

import { SidebarBody } from "@/components/navigation/sidebar.jsx";
import { UniversalSearchModal } from "@/components/navigation/UniversalSearchModal.jsx";
import { Button } from "@/components/ui/button.jsx";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet.jsx";
import { useIsMobile } from "@/hooks/use-media-query.js";

/**
 * Shared application shell: persistent 246px sidebar on desktop,
 * off-canvas drawer + hamburger on mobile, content outlet otherwise.
 * Houses the universal search trigger and modal with Ctrl+K / Cmd+K shortcut.
 */
export function AppShell() {
  const isMobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);
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
    <div className="flex min-h-svh bg-paper">
      {!isMobile ? (
        <aside className="sticky top-0 hidden h-svh w-[246px] shrink-0 bg-ink text-[#C9D2E5] lg:block" aria-label="Sidebar">
          <SidebarBody onOpenSearch={() => setSearchOpen(true)} />
        </aside>
      ) : null}

      <div className="min-w-0 flex-1">
        {isMobile ? (
          <div className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-panel px-4 py-3">
            <div className="flex items-center gap-3">
              <Button variant="outline" size="sm" onClick={() => setDrawerOpen(true)} aria-label="Open navigation menu">
                <Menu aria-hidden="true" />
                Menu
              </Button>
              <Link to="/" className="flex items-center gap-2 font-display font-semibold text-ink no-underline">
                <CalendarRange className="size-5 text-brass" aria-hidden="true" />
                UniSchedule
              </Link>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSearchOpen(true)}
              aria-label="Open universal search"
              className="gap-1.5"
            >
              <Search className="size-4" aria-hidden="true" />
              <span className="sr-only sm:not-sr-only">Search</span>
            </Button>
          </div>
        ) : null}

        <main>
          <Outlet />
        </main>
      </div>

      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="left" className="w-[280px] border-r-0 bg-ink p-0 text-[#C9D2E5] sm:max-w-xs">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SidebarBody
            onNavigate={() => setDrawerOpen(false)}
            onOpenSearch={() => {
              setDrawerOpen(false);
              setSearchOpen(true);
            }}
          />
        </SheetContent>
      </Sheet>

      <UniversalSearchModal open={searchOpen} onOpenChange={setSearchOpen} />
    </div>
  );
}
