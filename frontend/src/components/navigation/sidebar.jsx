import { Link, NavLink, useNavigate } from "react-router";
import { CalendarRange, CircleUserRound, Search } from "lucide-react";

import { useAuth } from "@/hooks/use-auth.js";
import { NAV_GROUPS } from "@/components/navigation/nav-config.js";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter as ShadcnSidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader as ShadcnSidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarSeparator,
} from "@/components/ui/sidebar.jsx";
import { useSidebar } from "@/hooks/use-sidebar.js";
import { cn } from "@/lib/utils.js";

/**
 * UniSchedule official shadcn Sidebar integration.
 * Supports expanded state with clear typography and grouped navigation,
 * and icon-collapse rail state with centered icons and tooltips.
 */
export function AppSidebar({ onOpenSearch }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { setOpenMobile, state } = useSidebar();

  const handleLogout = async () => {
    setOpenMobile(false);
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <Sidebar collapsible="icon" className="border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      {/* Header: UniSchedule Branding and Optional Search quick-button */}
      <ShadcnSidebarHeader className="p-3">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              asChild
              tooltip="UniSchedule Home"
              className="hover:bg-white/5 active:bg-white/10"
            >
              <Link
                to="/"
                onClick={() => setOpenMobile(false)}
                className="flex items-center gap-3 no-underline outline-none focus-visible:ring-2 focus-visible:ring-brass"
              >
                <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brass/15 text-brass">
                  <CalendarRange className="size-5" aria-hidden="true" />
                </div>
                <div className="flex flex-col truncate leading-none">
                  <span className="font-display text-base font-semibold text-white tracking-tight">
                    UniSchedule
                  </span>
                  <span className="mt-1 text-[11px] text-[#8A96B5]">University scheduling</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>

        {/* Search quick button */}
        {onOpenSearch ? (
          <div className="mt-1 group-data-[collapsible=icon]:hidden">
            <button
              type="button"
              onClick={() => {
                setOpenMobile(false);
                onOpenSearch();
              }}
              className="flex w-full items-center justify-between rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-[#C9D2E5] transition-colors hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-brass"
              aria-label="Open universal search (Ctrl+K)"
            >
              <span className="flex items-center gap-2">
                <Search className="size-3.5 text-[#8A96B5]" aria-hidden="true" />
                <span className="truncate">Search UniSchedule...</span>
              </span>
              <kbd className="rounded border border-white/15 bg-white/10 px-1 py-0.5 text-[10px] text-[#C9D2E5]">
                ⌘K
              </kbd>
            </button>
          </div>
        ) : null}

        {/* Collapsed Search Icon Trigger Button */}
        {onOpenSearch && state === "collapsed" ? (
          <SidebarMenu className="hidden group-data-[collapsible=icon]:flex">
            <SidebarMenuItem>
              <SidebarMenuButton
                onClick={() => onOpenSearch()}
                tooltip="Search (Ctrl+K)"
                aria-label="Open universal search (Ctrl+K)"
                className="justify-center hover:bg-white/10 hover:text-white"
              >
                <Search className="size-4 text-[#8A96B5]" aria-hidden="true" />
                <span className="sr-only">Search</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        ) : null}
      </ShadcnSidebarHeader>

      <SidebarSeparator />

      {/* Main Nav Content grouped by section */}
      <SidebarContent className="px-2 py-1">
        {NAV_GROUPS.map((group) => {
          // If this group is Account, we will render it with special account controls or in the menu
          return (
            <SidebarGroup key={group.label} className="py-1">
              <SidebarGroupLabel className="px-2 text-[0.68rem] font-semibold tracking-[0.08em] text-[#7583A6] uppercase">
                {group.label}
              </SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {group.items.map((item) => {
                    const Icon = item.icon;

                    if (item.action === "logout") {
                      return (
                        <SidebarMenuItem key={item.label}>
                          <SidebarMenuButton
                            onClick={handleLogout}
                            tooltip={item.label}
                            className="text-[#C9D2E5] hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-brass"
                          >
                            <Icon className="size-4 shrink-0 opacity-85" aria-hidden="true" />
                            <span>{item.label}</span>
                          </SidebarMenuButton>
                        </SidebarMenuItem>
                      );
                    }

                    return (
                      <SidebarMenuItem key={item.to}>
                        <NavLink
                          to={item.to}
                          end={item.end}
                          onClick={() => setOpenMobile(false)}
                          className={({ isActive }) =>
                            cn(
                              "w-full block no-underline",
                              isActive ? "pointer-events-auto" : ""
                            )
                          }
                        >
                          {({ isActive }) => (
                            <SidebarMenuButton
                              isActive={isActive}
                              tooltip={item.label}
                              className={cn(
                                "w-full text-[#C9D2E5] hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-brass",
                                isActive &&
                                  "bg-brass font-semibold text-[#241A0C] hover:bg-brass hover:text-[#241A0C]"
                              )}
                            >
                              <Icon
                                className={cn(
                                  "size-4 shrink-0 opacity-85",
                                  isActive && "opacity-100 text-[#241A0C]"
                                )}
                                aria-hidden="true"
                              />
                              <span className="truncate">{item.label}</span>
                            </SidebarMenuButton>
                          )}
                        </NavLink>
                      </SidebarMenuItem>
                    );
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          );
        })}
      </SidebarContent>

      <SidebarSeparator />

      {/* Footer: User profile / Account summary anchored at bottom */}
      <ShadcnSidebarFooter className="p-2">
        {user ? (
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                size="lg"
                tooltip={`Signed in as ${user.username}`}
                className="hover:bg-white/5 active:bg-white/10 cursor-default"
              >
                <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-[#C9D2E5]">
                  <CircleUserRound className="size-5 text-[#8A96B5]" aria-hidden="true" />
                </div>
                <div className="flex flex-col truncate leading-tight group-data-[collapsible=icon]:hidden">
                  <span className="text-[11px] text-[#8A96B5]">Signed in as</span>
                  <span className="truncate text-xs font-medium text-white">{user.username}</span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        ) : null}
      </ShadcnSidebarFooter>

      {/* Interactive desktop drag/toggle rail */}
      <SidebarRail />
    </Sidebar>
  );
}

/**
 * Backward-compatible SidebarBody export for any existing consumer or test.
 */
export function SidebarBody({ onNavigate, onOpenSearch }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    onNavigate?.();
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4 bg-sidebar text-sidebar-foreground">
      {/* Brand */}
      <div className="mb-4">
        <Link
          to="/"
          onClick={onNavigate}
          className="flex items-center gap-2 font-display text-[1.2rem] font-semibold text-white no-underline outline-none focus-visible:ring-2 focus-visible:ring-brass"
        >
          <CalendarRange className="size-5 text-brass" aria-hidden="true" />
          UniSchedule
        </Link>
        <span className="mt-0.5 block text-xs text-[#8A96B5]">University scheduling</span>

        {onOpenSearch ? (
          <button
            type="button"
            onClick={() => {
              onNavigate?.();
              onOpenSearch();
            }}
            className="mt-3 flex w-full items-center justify-between rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-[#C9D2E5] transition-colors hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-brass"
            aria-label="Open universal search (Ctrl+K)"
          >
            <span className="flex items-center gap-2">
              <Search className="size-3.5 text-[#8A96B5]" aria-hidden="true" />
              <span>Search UniSchedule...</span>
            </span>
            <kbd className="rounded border border-white/15 bg-white/10 px-1 py-0.5 text-[10px] text-[#C9D2E5]">
              ⌘K
            </kbd>
          </button>
        ) : null}
      </div>

      {/* Nav list */}
      <nav aria-label="Primary" className="flex flex-1 flex-col gap-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            <p className="mb-1.5 px-2.5 text-[0.68rem] font-medium tracking-[0.07em] text-[#7583A6] uppercase">
              {group.label}
            </p>
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                const linkClass = ({ isActive }) =>
                  cn(
                    "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[0.87rem] text-[#C9D2E5] no-underline transition-colors outline-none hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-brass",
                    isActive && "bg-brass font-semibold text-[#241A0C] hover:bg-brass hover:text-[#241A0C]"
                  );
                if (item.action === "logout") {
                  return (
                    <li key={item.label}>
                      <button
                        type="button"
                        onClick={handleLogout}
                        className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-[0.87rem] text-[#C9D2E5] transition-colors outline-none hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-brass"
                      >
                        <Icon className="size-4 w-[1.1rem] shrink-0 text-center opacity-85" aria-hidden="true" />
                        {item.label}
                      </button>
                    </li>
                  );
                }
                return (
                  <li key={item.to}>
                    <NavLink to={item.to} end={item.end} onClick={onNavigate} className={linkClass}>
                      <Icon className="size-4 w-[1.1rem] shrink-0 text-center opacity-85" aria-hidden="true" />
                      {item.label}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Footer */}
      {user ? (
        <div className="mt-6 flex items-center gap-2 border-t border-white/10 px-2.5 pt-4 text-xs text-[#8A96B5]">
          <CircleUserRound className="size-4 shrink-0" aria-hidden="true" />
          <span className="truncate">
            Signed in as <span className="font-medium text-[#C9D2E5]">{user.username}</span>
          </span>
        </div>
      ) : null}
    </div>
  );
}
