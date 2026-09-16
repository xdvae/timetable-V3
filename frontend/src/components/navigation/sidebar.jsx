import { Link, NavLink, useNavigate } from "react-router";
import { CalendarRange, CircleUserRound } from "lucide-react";

import { useAuth } from "@/hooks/use-auth.js";
import { NAV_GROUPS } from "@/components/navigation/nav-config.js";
import { cn } from "@/lib/utils";

function SidebarNavList({ onNavigate }) {
  const { logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    onNavigate?.();
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <nav aria-label="Primary" className="flex flex-col gap-4">
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
  );
}

function SidebarBrand({ onNavigate }) {
  return (
    <div className="mb-6">
      <Link
        to="/"
        onClick={onNavigate}
        className="flex items-center gap-2 font-display text-[1.2rem] font-semibold text-white no-underline outline-none focus-visible:ring-2 focus-visible:ring-brass"
      >
        <CalendarRange className="size-5 text-brass" aria-hidden="true" />
        UniSchedule
      </Link>
      <span className="mt-0.5 block text-xs text-[#8A96B5]">University scheduling</span>
    </div>
  );
}

function SidebarFooter() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <div className="mt-6 flex items-center gap-2 border-t border-white/10 px-2.5 pt-4 text-xs text-[#8A96B5]">
      <CircleUserRound className="size-4 shrink-0" aria-hidden="true" />
      <span className="truncate">
        Signed in as <span className="font-medium text-[#C9D2E5]">{user.username}</span>
      </span>
    </div>
  );
}

/** Shared sidebar body used by both the desktop panel and the mobile drawer. */
export function SidebarBody({ onNavigate }) {
  return (
    <div className="flex h-full flex-col overflow-y-auto p-4">
      <SidebarBrand onNavigate={onNavigate} />
      <div className="flex-1">
        <SidebarNavList onNavigate={onNavigate} />
      </div>
      <SidebarFooter />
    </div>
  );
}
