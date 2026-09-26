import { Link } from "react-router";
import {
  BookOpen,
  CalendarCheck,
  CheckCircle2,
  ClipboardCheck,
  DoorOpen,
  School,
  Users,
  UsersRound,
} from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { StatCard } from "@/components/dashboard/StatCard.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { Button } from "@/components/ui/button.jsx";
import { useApi } from "@/hooks/use-api.js";
import { getDashboard } from "@/services/api/dashboard.js";
import { cn } from "@/lib/utils";

const TILES = [
  { key: "rooms", label: "Rooms", to: "/rooms", icon: DoorOpen },
  { key: "faculty", label: "Faculty", to: "/faculty", icon: Users },
  { key: "programs", label: "Programs", to: "/programs", icon: School },
  { key: "enrollments", label: "Enrollments", to: "/enrollments", icon: UsersRound },
  { key: "sections", label: "Sections (auto-generated)", to: "/enrollments", icon: UsersRound },
  { key: "subjects", label: "Subjects", to: "/subjects", icon: BookOpen },
  { key: "assignments", label: "Teaching Assignments", to: "/assignments", icon: ClipboardCheck },
  { key: "scheduled", label: "Scheduled Class Blocks", to: "/timetable", icon: CalendarCheck },
];

function GettingStarted({ counts }) {
  // Step completion is derived from real counts — no fabricated progress.
  const steps = [
    { label: "Config", to: "/config", done: true, hint: "working days, periods, breaks, size limits" },
    { label: "Rooms", to: "/rooms", done: counts.rooms > 0, hint: "theory rooms and labs with capacity" },
    { label: "Faculty", to: "/faculty", done: counts.faculty > 0, hint: "roster, loads, availability" },
    { label: "Programs", to: "/programs", done: counts.programs > 0, hint: "e.g. BCA, B.Tech CSE" },
    { label: "Enrollments", to: "/enrollments", done: counts.enrollments > 0, hint: "sections auto-generated" },
    { label: "Subjects", to: "/subjects", done: counts.subjects > 0, hint: "per enrollment" },
    { label: "Teaching Assignments", to: "/assignments", done: counts.assignments > 0, hint: "who teaches what" },
    { label: "Timetable", to: "/timetable", done: counts.scheduled > 0, hint: "generate the schedule" },
  ];
  return (
    <Panel accent="brass" title="Getting started">
      <ol className="space-y-2.5">
        {steps.map((step, index) => (
          <li key={step.label} className="flex items-start gap-3 text-sm">
            {step.done ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-sage" aria-label="Done" />
            ) : (
              <span
                className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border border-line text-[0.65rem] text-muted-foreground"
                aria-hidden="true"
              >
                {index + 1}
              </span>
            )}
            <span className={cn(!step.done && "text-muted-foreground")}>
              <Link to={step.to} className="font-medium text-steel underline-offset-4 hover:underline">
                {step.label}
              </Link>{" "}
              <span className="text-muted-foreground">— {step.hint}.</span>
            </span>
          </li>
        ))}
      </ol>
      <div className="mt-5 flex flex-wrap gap-2">
        <Button asChild>
          <Link to="/timetable">Go to Timetable</Link>
        </Button>
        <Button asChild variant="outline">
          <Link to="/import">Or import from CSV</Link>
        </Button>
      </div>
    </Panel>
  );
}

export function DashboardPage() {
  const { data, error, isLoading, retry } = useApi(getDashboard, ["dashboard"]);

  if (isLoading && !data) {
    return (
      <Page title="Dashboard" subtitle="A quick look at what's been set up so far.">
        <PageLoading rows={8} label="Loading dashboard…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page title="Dashboard" subtitle="A quick look at what's been set up so far.">
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const counts = data.counts ?? {};
  const tiles = TILES.map((tile) => ({ ...tile, value: counts[tile.key] ?? 0 }));

  return (
    <Page title="Dashboard" subtitle={data.session_name || "A quick look at what's been set up so far."}>
      {tiles.length === 0 ? (
        <EmptyState title="No dashboard data" description="The server returned no summary counts." />
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {tiles.map((tile) => (
            <StatCard key={tile.key} label={tile.label} value={tile.value} icon={tile.icon} to={tile.to} />
          ))}
        </div>
      )}
      <div className="mt-5">
        <GettingStarted counts={counts} />
      </div>
    </Page>
  );
}
