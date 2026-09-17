import { useCallback } from "react";
import { Link, useParams } from "react-router";
import {
  ArrowLeft,
  CalendarDays,
  CheckCircle2,
  Download,
  Printer,
  UserCheck,
} from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { Button } from "@/components/ui/button.jsx";
import { useApi } from "@/hooks/use-api.js";
import { exportUrl, getTimetableHome, getTimetableView } from "@/services/api/timetable.js";
import { TimetableGrid } from "@/components/timetable/TimetableGrid.jsx";
import { TimetableLegend } from "@/components/timetable/TimetableLegend.jsx";

const VALID_VIEWS = ["section", "faculty", "room"];

/** True when at least one scheduled block exists anywhere in the rows. */
function hasScheduledClasses(dayRows) {
  return (dayRows ?? []).some((row) =>
    (row.lanes ?? []).some((lane) => (lane ?? []).some((cell) => !cell.empty))
  );
}

export function TimetablePage() {
  const { data, error, isLoading, retry } = useApi(getTimetableHome);

  if (isLoading && !data) {
    return (
      <Page title="Timetable" subtitle="Generate the schedule, then look it up by section, faculty member, or room.">
        <PageLoading rows={6} label="Loading timetable…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page title="Timetable" subtitle="Generate the schedule, then look it up by section, faculty member, or room.">
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const sections = data.sections ?? [];
  const faculty = data.faculty ?? [];
  const rooms = data.rooms ?? [];

  return (
    <Page title="Timetable" subtitle="Generate the schedule, then look it up by section, faculty member, or room.">
      <div className="space-y-5">
        {data.has_schedule ? (
          <p className="flex items-center gap-2 text-sm font-medium text-sage">
            <CheckCircle2 className="size-4" aria-hidden="true" />
            A timetable has been generated — pick a view below.
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">
            No timetable has been generated yet. Schedule generation ships in a later phase — the views
            below unlock once a schedule exists.
          </p>
        )}

        <Link
          to="/timetable/free"
          className="flex max-w-[520px] items-center gap-3 rounded-lg border border-line bg-panel p-4 outline-none transition-colors hover:border-steel focus-visible:ring-2 focus-visible:ring-ring"
        >
          <UserCheck className="size-6 shrink-0 text-sage" aria-hidden="true" />
          <span>
            <span className="block text-sm font-semibold text-ink">Who&apos;s free when</span>
            <span className="block text-sm text-muted-foreground">
              See every faculty member&apos;s status hour-by-hour for a chosen day.
            </span>
          </span>
        </Link>

        <div className="grid gap-5 lg:grid-cols-3">
          <Panel accent="steel" title="By Section">
            {sections.length === 0 ? (
              <p className="text-sm text-muted-foreground">No sections yet.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {sections.map((section) => (
                  <Button key={section.id} asChild variant="outline" size="sm">
                    <Link to={`/timetable/section/${section.id}`}>{section.name}</Link>
                  </Button>
                ))}
              </div>
            )}
          </Panel>
          <Panel accent="steel" title="By Faculty">
            {faculty.length === 0 ? (
              <p className="text-sm text-muted-foreground">No faculty yet.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {faculty.map((member) => (
                  <Button key={member.id} asChild variant="outline" size="sm">
                    <Link to={`/timetable/faculty/${member.id}`}>{member.name}</Link>
                  </Button>
                ))}
              </div>
            )}
          </Panel>
          <Panel accent="steel" title="By Room">
            {rooms.length === 0 ? (
              <p className="text-sm text-muted-foreground">No rooms yet.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {rooms.map((room) => (
                  <Button key={room.id} asChild variant="outline" size="sm">
                    <Link to={`/timetable/room/${room.id}`}>Room {room.name}</Link>
                  </Button>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </Page>
  );
}

export function TimetableViewPage() {
  const { view, id } = useParams();
  const isValidView = VALID_VIEWS.includes(view);
  const fetcher = useCallback(() => getTimetableView(view, id), [view, id]);
  const { data, error, isLoading, retry } = useApi(fetcher);

  if (!isValidView) {
    return (
      <Page
        title="Timetable"
        subtitle="Day × period grid for one section, faculty member, or room."
        breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Not found" }]}
      >
        <QueryError
          error={{ message: `Invalid view "${view}". Use 'section', 'faculty', or 'room'.`, status: 404 }}
        />
      </Page>
    );
  }

  if (isLoading && !data) {
    return (
      <Page
        title="Timetable"
        subtitle="Day × period grid for one section, faculty member, or room."
        breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Loading…" }]}
      >
        <PageLoading rows={8} label="Loading timetable…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page
        title="Timetable"
        subtitle="Day × period grid for one section, faculty member, or room."
        breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Error" }]}
      >
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const periods = data.periods ?? [];
  const dayRows = data.day_rows ?? [];
  const multiLaneDays = dayRows.filter((row) => (row.lanes?.length ?? 0) > 1).map((row) => row.day);
  const empty = !hasScheduledClasses(dayRows);

  return (
    <Page
      title={data.title}
      subtitle={data.extra || "Day × period grid for one section, faculty member, or room."}
      breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: data.title }]}
      actions={
        <>
          <Button asChild variant="outline" size="sm">
            <a href={exportUrl(view, id, "xlsx")}>
              <Download aria-hidden="true" />
              Excel
            </a>
          </Button>
          <Button asChild variant="outline" size="sm">
            <a href={exportUrl(view, id, "csv")}>
              <Download aria-hidden="true" />
              CSV
            </a>
          </Button>
          <Button asChild variant="outline" size="sm">
            <a href={exportUrl(view, id, "html")} target="_blank" rel="noreferrer">
              <Printer aria-hidden="true" />
              Print
            </a>
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <TimetableLegend />
        {empty ? (
          <EmptyState
            icon={CalendarDays}
            title="No scheduled classes yet"
            description="Nothing is placed for this view. Generate the timetable once scheduling ships, then return here."
          />
        ) : (
          <>
            <h2 id="timetable-grid-heading" className="sr-only">
              {data.title} grid
            </h2>
            <TimetableGrid periods={periods} dayRows={dayRows} labelledBy="timetable-grid-heading" />
            {multiLaneDays.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                {multiLaneDays.join(", ")} {multiLaneDays.length === 1 ? "shows" : "show"} more than one
                row because different sub-groups have genuinely simultaneous classes in different rooms —
                not a conflict.
              </p>
            ) : null}
          </>
        )}
        <div>
          <Button asChild variant="outline" size="sm">
            <Link to="/timetable">
              <ArrowLeft aria-hidden="true" />
              Back
            </Link>
          </Button>
        </div>
      </div>
    </Page>
  );
}
