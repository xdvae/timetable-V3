import { createBrowserRouter } from "react-router";

import { RequireAuth } from "./auth.jsx";
import { AppShell } from "@/components/layout/app-shell.jsx";
import { LoginPage } from "@/pages/Login/LoginPage.jsx";
import { DashboardPage } from "@/pages/Dashboard/DashboardPage.jsx";
import { ConfigPage } from "@/pages/Config/ConfigPage.jsx";
import { RoomsPage } from "@/pages/Rooms/RoomsPage.jsx";
import { FacultyAvailabilityPage, FacultyPage, FacultyPreferencesPage } from "@/pages/Faculty/FacultyPage.jsx";
import { ProgramsPage } from "@/pages/Programs/ProgramsPage.jsx";
import { EnrollmentsPage, SectionsPage } from "@/pages/Enrollments/EnrollmentsPage.jsx";
import { SpecializationDetailPage, SpecializationsPage } from "@/pages/Specializations/SpecializationsPage.jsx";
import { SubjectsPage } from "@/pages/Subjects/SubjectsPage.jsx";
import { AssignmentsPage } from "@/pages/Assignments/AssignmentsPage.jsx";
import { ImportPage } from "@/pages/Import/ImportPage.jsx";
import { OverviewPage } from "@/pages/Overview/OverviewPage.jsx";
import { TimetablePage, TimetableViewPage } from "@/pages/Timetable/TimetablePage.jsx";
import { FreeFacultyPage } from "@/pages/FreeFaculty/FreeFacultyPage.jsx";
import { ChangePasswordPage } from "@/pages/Account/ChangePasswordPage.jsx";
import { NotFoundPage } from "@/pages/NotFoundPage.jsx";

/**
 * Route structure mirroring the existing Flask application.
 * /login is public; everything else sits behind RequireAuth + AppShell.
 */
export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "config", element: <ConfigPage /> },
      { path: "rooms", element: <RoomsPage /> },
      { path: "faculty", element: <FacultyPage /> },
      { path: "faculty/:fid/availability", element: <FacultyAvailabilityPage /> },
      { path: "faculty/:fid/preferences", element: <FacultyPreferencesPage /> },
      { path: "programs", element: <ProgramsPage /> },
      { path: "enrollments", element: <EnrollmentsPage /> },
      { path: "enrollments/:eid/sections", element: <SectionsPage /> },
      { path: "enrollments/:eid/specializations", element: <SpecializationsPage /> },
      { path: "enrollments/:eid/specializations/:sid", element: <SpecializationDetailPage /> },
      { path: "subjects", element: <SubjectsPage /> },
      { path: "assignments", element: <AssignmentsPage /> },
      { path: "import", element: <ImportPage /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "timetable", element: <TimetablePage /> },
      { path: "timetable/free", element: <FreeFacultyPage /> },
      { path: "timetable/:view/:id", element: <TimetableViewPage /> },
      { path: "account/change-password", element: <ChangePasswordPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
