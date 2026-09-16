import { Link } from "react-router";
import { CalendarClock, Users } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { Badge } from "@/components/ui/badge.jsx";
import { Button } from "@/components/ui/button.jsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.jsx";
import { useApi } from "@/hooks/use-api.js";
import { getFaculty } from "@/services/api/faculty.js";
import { cn } from "@/lib/utils";

function FacultyTypeBadge({ facultyType }) {
  return <Badge variant="secondary">{facultyType || "regular"}</Badge>;
}

/**
 * Weekly load shown as text plus a thin bar. The bar is decorative support
 * for the numbers (which carry the meaning); over-max rows add explicit
 * "(over max)" text so color is never the only indicator.
 */
function WeeklyLoad({ load, max }) {
  const safeMax = Number(max) > 0 ? Number(max) : null;
  const ratio = safeMax ? Math.min(load / safeMax, 1) : 0;
  const overMax = safeMax !== null && load > safeMax;
  return (
    <div className="min-w-[140px]">
      <p className={cn("text-sm font-medium tabular-nums", overMax ? "text-signal" : "text-ink")}>
        {load}
        {safeMax !== null ? ` / ${safeMax} hrs` : " hrs"}
        {overMax ? <span className="ml-1 text-xs font-semibold">(over max)</span> : null}
      </p>
      {safeMax !== null ? (
        <div
          className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted"
          role="img"
          aria-label={`Weekly load ${load} of ${safeMax} hours${overMax ? ", over maximum" : ""}`}
        >
          <div
            className={cn("h-full rounded-full", overMax ? "bg-signal" : "bg-steel")}
            style={{ width: `${Math.round(ratio * 100)}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}

export function FacultyPage() {
  const { data: faculty, error, isLoading, retry } = useApi(getFaculty);

  if (isLoading && !faculty) {
    return (
      <Page title="Faculty" subtitle="Roster, weekly loads, and availability.">
        <PageLoading rows={6} label="Loading faculty…" />
      </Page>
    );
  }

  if (error && !faculty) {
    return (
      <Page title="Faculty" subtitle="Roster, weekly loads, and availability.">
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  return (
    <Page
      title="Faculty"
      subtitle={faculty.length === 0 ? "Roster, weekly loads, and availability." : `${faculty.length} faculty members`}
    >
      {faculty.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No faculty yet"
          description="Faculty added in the backend will appear here with weekly loads and availability links."
        />
      ) : (
        <Panel accent="steel" title="All faculty">
          <Table aria-label="Faculty roster">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Name</TableHead>
                <TableHead scope="col">Department</TableHead>
                <TableHead scope="col">Type</TableHead>
                <TableHead scope="col">Weekly Load</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {faculty.map((member) => (
                <TableRow key={member.id}>
                  <TableCell className="font-medium text-ink">{member.name}</TableCell>
                  <TableCell>{member.department || <span className="text-muted-foreground">—</span>}</TableCell>
                  <TableCell>
                    <FacultyTypeBadge facultyType={member.faculty_type} />
                  </TableCell>
                  <TableCell>
                    <WeeklyLoad load={member.weekly_load ?? 0} max={member.weekly_max_hours} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Button asChild variant="outline" size="sm">
                      <Link to={`/faculty/${member.id}/availability`} aria-label={`Availability for ${member.name}`}>
                        <CalendarClock aria-hidden="true" />
                        Availability
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Panel>
      )}
    </Page>
  );
}

export function FacultyAvailabilityPage() {
  return (
    <Page
      title="Faculty Availability"
      subtitle="Unavailable day × period slots per faculty member."
    >
      <Panel accent="brass" title="Coming in a later phase">
        <p className="text-sm text-muted-foreground">
          Availability viewing and editing ships after the remaining read-only pages. Faculty rows
          already link here via React Router.
        </p>
      </Panel>
    </Page>
  );
}
