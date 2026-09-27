import { useCallback, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import {
  ArrowLeft,
  CalendarDays,
  CheckCircle2,
  CircleCheck,
  Download,
  LoaderCircle,
  Pencil,
  Printer,
  TriangleAlert,
  UserCheck,
} from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { FailureList } from "@/components/feedback/mutation.jsx";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert.jsx";
import { Badge } from "@/components/ui/badge.jsx";
import { Button } from "@/components/ui/button.jsx";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog.jsx";
import { Label } from "@/components/ui/label.jsx";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select.jsx";
import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import { getFailures, safeMessage } from "@/lib/failures.js";
import { emitOnSuccess, GENERATION_DOMAINS } from "@/lib/propagation.js";
import { exportUrl, getTimetableHome, getTimetableView, runScheduler } from "@/services/api/timetable.js";
import { TimetableGrid } from "@/components/timetable/TimetableGrid.jsx";
import { TimetableLegend } from "@/components/timetable/TimetableLegend.jsx";
import { filterDayRows, summarizeDayRows, todayAbbrev } from "@/components/timetable/timetable-helpers.js";

const VALID_VIEWS = ["section", "faculty", "room"];

const VIEW_LABELS = { section: "Section", faculty: "Faculty", room: "Room" };

/** True when at least one scheduled block exists anywhere in the rows. */
function hasScheduledClasses(dayRows) {
  return (dayRows ?? []).some((row) =>
    (row.lanes ?? []).some((lane) => (lane ?? []).some((cell) => !cell.empty))
  );
}

/**
 * Schedule generation panel. Invokes the existing OR-Tools scheduler via
 * POST /api/schedule/run and displays its result; all solving stays
 * server-side. Generation REPLACES the stored timetable, so confirmation
 * is required. The run can take up to ~30s: the button stays disabled with
 * a textual progress indicator (the backend exposes no progress events).
 */
function GeneratePanel({ onGenerated }) {
  const toast = useToast();
  const { execute, isSubmitting } = useMutation(runScheduler);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [result, setResult] = useState(null);

  async function handleConfirm() {
    setConfirmOpen(false);
    setResult(null);
    const res = await execute();
    if (res.ok) {
      setResult({ ok: true, data: res.data });
      toast.success(res.data.message || "Timetable generated.", { title: "Schedule generated" });
      onGenerated();
      // Phase 6P: generation replaced the persisted schedule (non-locked rows
      // + specialization slots); every schedule-dependent domain emits.
      emitOnSuccess(res, GENERATION_DOMAINS);
    } else if (res.error) {
      // Backend message preserved verbatim (e.g. "Scheduling failed: …");
      // structured infeasibility/conflict failures (SCHEDULING_INFEASIBLE,
      // specialization codes) render below with their details intact.
      // The previous schedule, if any, is left untouched server-side, so a
      // failed generation emits nothing and triggers no refetch.
      setResult({ ok: false, error: res.error });
      toast.error(safeMessage(res.error.message, "Scheduling failed."), { title: "Scheduling failed" });
    }
  }

  return (
    <Panel
      accent="brass"
      title="Generate the timetable"
      description="Runs the scheduler against everything currently entered. Usually takes a few seconds to under a minute."
      actions={
        <Button onClick={() => setConfirmOpen(true)} disabled={isSubmitting} size="lg">
          {isSubmitting ? (
            <>
              <LoaderCircle className="animate-spin" aria-hidden="true" />
              Generating…
            </>
          ) : (
            "Generate Timetable"
          )}
        </Button>
      }
    >
      {isSubmitting ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          Schedule generation is in progress. This usually takes a few seconds to under a minute —
          please wait.
        </p>
      ) : null}
      {result?.ok ? (
        <Alert variant="success">
          <CircleCheck aria-hidden="true" />
          <AlertTitle>Schedule generated</AlertTitle>
          <AlertDescription>
            <p>{result.data.message}</p>
            <p className="mt-1 text-xs tabular-nums">
              Status: {result.data.status} · {result.data.placements} class blocks placed
            </p>
          </AlertDescription>
        </Alert>
      ) : null}
      {result && !result.ok ? (
        <Alert variant="destructive">
          <TriangleAlert aria-hidden="true" />
          <AlertTitle>Scheduling failed</AlertTitle>
          <AlertDescription>
            {safeMessage(result.error.message, "The scheduler could not produce a timetable.")}
          </AlertDescription>
        </Alert>
      ) : null}
      {result && !result.ok && getFailures(result.error).length > 0 ? (
        <div className="mt-3">
          <FailureList failures={getFailures(result.error)} title="Why scheduling failed" />
        </div>
      ) : null}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Generate timetable?</DialogTitle>
            <DialogDescription>
              Runs the scheduler against everything currently entered. This replaces the current
              timetable. Usually takes a few seconds to under a minute.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleConfirm}>Generate</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Panel>
  );
}

export function TimetablePage() {
  const { data, error, isLoading, retry } = useApi(getTimetableHome, ["schedule"]);

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
        <GeneratePanel onGenerated={retry} />
        {data.has_schedule ? (
          <p className="flex items-center gap-2 text-sm font-medium text-sage">
            <CheckCircle2 className="size-4" aria-hidden="true" />
            A timetable has been generated — pick a view below.
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">
            No timetable has been generated yet — use Generate above, then pick a view below.
          </p>
        )}

        <div className="grid max-w-[1060px] gap-3 md:grid-cols-2">
          <Link
            to="/timetable/editor"
            className="flex items-center gap-3 rounded-lg border border-line bg-panel p-4 outline-none transition-colors hover:border-steel focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Pencil className="size-6 shrink-0 text-brass-dark" aria-hidden="true" />
            <span>
              <span className="block text-sm font-semibold text-ink">Edit the timetable</span>
              <span className="block text-sm text-muted-foreground">
                Move classes with backend validation — the timetable is never regenerated here.
              </span>
            </span>
          </Link>
          <Link
            to="/timetable/free"
            className="flex items-center gap-3 rounded-lg border border-line bg-panel p-4 outline-none transition-colors hover:border-steel focus-visible:ring-2 focus-visible:ring-ring"
          >
            <UserCheck className="size-6 shrink-0 text-sage" aria-hidden="true" />
            <span>
              <span className="block text-sm font-semibold text-ink">Who&apos;s free when</span>
              <span className="block text-sm text-muted-foreground">
                See every faculty member&apos;s status hour-by-hour for a chosen day.
              </span>
            </span>
          </Link>
        </div>

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
  const { data, error, isLoading, retry } = useApi(fetcher, ["schedule"]);
  // Phase 6R: display-only day filter + informational today marker.
  // Both derive from the already-fetched payload: no extra GET, no
  // invalidation, no mutation. `today` is computed once (no timer).
  const [dayFilter, setDayFilter] = useState("all");
  const today = useMemo(() => todayAbbrev(), []);
  // A new view/id reuses this component: reset the display filter so a
  // previous day choice never masquerades as missing data. Render-time
  // state adjustment (the sanctioned alternative to a reset effect) —
  // local state only, no GET, no invalidation.
  const [filterScope, setFilterScope] = useState(null);
  const scope = `${view}/${id}`;
  if (filterScope !== scope) {
    setFilterScope(scope);
    setDayFilter("all");
  }

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
  const days = data.days ?? dayRows.map((row) => row.day);
  // Distinguish "no timetable exists" from "timetable exists but this
  // day filter matches nothing": the filter only hides rows locally.
  const hasAny = hasScheduledClasses(dayRows);
  // Plain calls (not hooks): this block runs after the loading/error
  // early returns above, so hooks would be conditional here. The dataset
  // is one view's grid — recomputation per render is negligible.
  const visibleRows = filterDayRows(dayRows, dayFilter);
  const summary = summarizeDayRows(dayRows);
  const multiLaneDays = visibleRows
    .filter((row) => (row.lanes?.length ?? 0) > 1)
    .map((row) => row.day);
  const filteredEmpty = !hasScheduledClasses(visibleRows);
  const todayShown = today != null && days.includes(today);

  const contextBits = [
    `${days.length} ${days.length === 1 ? "day" : "days"} × ${periods.length} ${periods.length === 1 ? "period" : "periods"}`,
    `${summary.total} ${summary.total === 1 ? "class" : "classes"}`,
  ];
  if (summary.multi > 0) {
    contextBits.push(`${summary.multi} multi-period`);
  }
  if (summary.fixed > 0) {
    contextBits.push(`${summary.fixed} fixed`);
  }
  if (summary.spec > 0) {
    contextBits.push(`${summary.spec} specialization`);
  }

  return (
    <Page
      title={data.title}
      subtitle={data.extra || "Day × period grid for one section, faculty member, or room."}
      breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: data.title }]}
      actions={
        <>
          <Button asChild variant="outline" size="sm">
            <Link to="/timetable/editor">
              <Pencil aria-hidden="true" />
              Open in Editor
            </Link>
          </Button>
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
        <div className="flex flex-wrap items-center gap-2" aria-label="Timetable context">
          <Badge variant="secondary">{VIEW_LABELS[view] ?? view} view</Badge>
          <span className="text-xs text-muted-foreground" role="status">
            {contextBits.join(" · ")}
            {todayShown ? ` · Today: ${today}` : null}
          </span>
        </div>
        <TimetableLegend />
        {days.length > 1 ? (
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <Label htmlFor="timetable-day-filter">Day</Label>
              <Select value={dayFilter} onValueChange={setDayFilter}>
                <SelectTrigger id="timetable-day-filter" className="mt-1.5 w-[180px]">
                  <SelectValue placeholder="All days" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All days</SelectItem>
                  {days.map((day) => (
                    <SelectItem key={day} value={day}>
                      {day}
                      {day === today ? " (today)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <p className="pb-2 text-xs text-muted-foreground">
              Display only — filtering never changes the timetable.
            </p>
          </div>
        ) : null}
        {!hasAny ? (
          <EmptyState
            icon={CalendarDays}
            title="No scheduled classes yet"
            description="Nothing is placed for this view. Generate the timetable first, or check that sections, assignments, and configuration are in place."
            action={
              <div className="mt-2 flex flex-wrap justify-center gap-2">
                <Button asChild>
                  <Link to="/timetable">Go to timetable generation</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link to="/assignments">Review teaching assignments</Link>
                </Button>
              </div>
            }
          />
        ) : filteredEmpty ? (
          <EmptyState
            icon={CalendarDays}
            title={`No classes on ${dayFilter}`}
            description="This timetable exists — the selected day just has nothing scheduled for this view."
            action={
              <Button variant="outline" className="mt-2" onClick={() => setDayFilter("all")}>
                Show all days
              </Button>
            }
          />
        ) : (
          <>
            <h2 id="timetable-grid-heading" className="sr-only">
              {data.title} grid
            </h2>
            <TimetableGrid
              periods={periods}
              dayRows={visibleRows}
              labelledBy="timetable-grid-heading"
              today={today}
            />
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
