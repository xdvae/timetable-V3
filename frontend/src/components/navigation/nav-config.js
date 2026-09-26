import {
  BookOpen,
  CalendarDays,
  ClipboardCheck,
  DoorOpen,
  KeyRound,
  LayoutGrid,
  Lock,
  LogOut,
  Pencil,
  School,
  SlidersHorizontal,
  Upload,
  UserCheck,
  Users,
  UsersRound,
} from "lucide-react";

/**
 * Sidebar navigation, mirroring the existing application's architecture.
 * `end: true` = exact match (used where a sibling route shares the prefix).
 * `action: "logout"` = session sign-out instead of navigation.
 */
export const NAV_GROUPS = [
  {
    label: "Setup",
    items: [
      { to: "/config", label: "Config", icon: SlidersHorizontal },
      { to: "/rooms", label: "Rooms", icon: DoorOpen },
    ],
  },
  {
    label: "People",
    items: [
      { to: "/faculty", label: "Faculty", icon: Users },
      { to: "/programs", label: "Programs", icon: School },
    ],
  },
  {
    label: "Academics",
    items: [
      { to: "/enrollments", label: "Enrollments & Sections", icon: UsersRound },
      { to: "/subjects", label: "Subjects", icon: BookOpen },
      { to: "/assignments", label: "Teaching Assignments", icon: ClipboardCheck },
      { to: "/overview", label: "Overview", icon: LayoutGrid },
    ],
  },
  {
    label: "Data",
    items: [{ to: "/import", label: "Import CSV", icon: Upload }],
  },
  {
    label: "Timetable",
    items: [
      { to: "/timetable", label: "Timetable", icon: CalendarDays, end: true },
      { to: "/timetable/editor", label: "Editor", icon: Pencil },
      { to: "/timetable/free", label: "Who's Free", icon: UserCheck },
      { to: "/timetable/locked-blocks", label: "Fixed Blocks", icon: Lock },
    ],
  },
  {
    label: "Account",
    items: [
      { to: "/account/change-password", label: "Change Password", icon: KeyRound },
      { to: null, label: "Log Out", icon: LogOut, action: "logout" },
    ],
  },
];
