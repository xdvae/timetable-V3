import { useCallback, useMemo } from "react";
import { Link, useSearchParams } from "react-router";
import { ArrowLeft, TriangleAlert, UserCheck } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert.jsx";
import { Button } from "@/components/ui/button.jsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.jsx";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs.jsx";
import { useApi } from "@/hooks/use-api.js";
import { getFreeFaculty } from "@/services/api/timetable.js";
import { cn } from "@/lib/utils";

function FreeLegend() {
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground" aria-label="Legend">
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block size-3 rounded-[3px] border border-sage bg-free" aria-hidden="true" />
        Free
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span
          className="inline-block size-3 rounded-[3px] border border-signal bg-signal-tint"
          aria-hidden="true"
        />
        Teaching
      </span>
    </div>
  );
}

export function FreeFacultyPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const dayParam = searchParams.get("day");
  const fetcher = useCallback(() => getFreeFaculty(dayParam ?? undefined), [dayParam]);
  const { data, error, isLoading, retry } = useApi(fetcher, ["schedule"]);

  const busyByCell = useMemo(() => {
    const map = new Map();
    for (const entry of data?.busy ?? []) {
      map.set(`${entry.faculty_id}:${entry.period}`, entry.label);
    }
    return map;
  }, [data]);

  if (isLoading && !data) {
    return (
      <Page
        title="Who's Free, When"
        subtitle="Pick a day to see every faculty member's status hour-by-hour."
        breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Who's Free" }]}
      >
        <PageLoading rows={8} label="Loading availability…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page
        title="Who's Free, When"
        subtitle="Pick a day to see every faculty member's status hour-by-hour."
        breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Who's Free" }]}
      >
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const days = data.days ?? [];
  const periods = data.periods ?? [];
  const faculty = data.faculty ?? [];
  const activeDay = days.includes(dayParam) ? dayParam : (data.selected_day ?? days[0]);

  return (
    <Page
      title="Who's Free, When"
      subtitle="Pick a day to see every faculty member's status hour-by-hour."
      breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Who's Free" }]}
    >
      <div className="space-y-4">
        {data.warning ? (
          <Alert variant="warning">
            <TriangleAlert aria-hidden="true" />
            <AlertTitle>No timetable yet</AlertTitle>
            <AlertDescription>{data.warning}</AlertDescription>
          </Alert>
        ) : null}

        {days.length > 0 ? (
          <Tabs
            value={activeDay}
            onValueChange={(day) => setSearchParams(day ? { day } : {})}
          >
            <TabsList aria-label="Choose a day">
              {days.map((day) => (
                <TabsTrigger key={day} value={day}>
                  {day}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        ) : null}

        <FreeLegend />

        {isLoading ? (
          <PageLoading rows={8} label={`Loading ${activeDay} availability…`} />
        ) : faculty.length === 0 ? (
          <EmptyState
            icon={UserCheck}
            title="No faculty yet"
            description="Faculty added in the backend will appear here with hour-by-hour availability."
          />
        ) : (
          <Panel accent="steel" title={`${activeDay} availability`}>
            <Table aria-label={`Faculty availability for ${activeDay}`}>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Faculty</TableHead>
                  {periods.map((period, index) => (
                    <TableHead key={`${period}-${index}`} scope="col" className="tabular-nums">
                      {period}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {faculty.map((member) => (
                  <TableRow key={member.id}>
                    <TableCell className="bg-steel-tint font-semibold text-ink">{member.name}</TableCell>
                    {periods.map((period, periodIndex) => {
                      const label = busyByCell.get(`${member.id}:${periodIndex}`);
                      return (
                        <TableCell
                          key={`${member.id}-${periodIndex}`}
                          className={cn("text-xs", label ? "busy-cell" : "free-cell")}
                          aria-label={`${member.name}, ${period}: ${label ? `teaching ${label}` : "free"}`}
                        >
                          {label ? (
                            <>
                              <span className="sr-only">Teaching: </span>
                              {label}
                            </>
                          ) : (
                            "Free"
                          )}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Panel>
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
