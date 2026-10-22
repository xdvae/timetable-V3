import { useCallback, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, CalendarClock, Plus, SlidersHorizontal, Trash2, Users } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
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
import { Input } from "@/components/ui/input.jsx";
import { Label } from "@/components/ui/label.jsx";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select.jsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.jsx";
import { DeleteConfirmDialog, FieldError, MutationError, MutationFailure } from "@/components/feedback/mutation.jsx";
import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import { emitOnSuccess, FACULTY_DOMAINS, PREFERENCE_DOMAINS } from "@/lib/propagation.js";
import {
  createFaculty,
  createFacultyPreference,
  deleteFaculty,
  deleteFacultyPreference,
  getFaculty,
  getFacultyAvailability,
  getFacultyPreferences,
  saveFacultyAvailability,
  updateFacultyPreference,
} from "@/services/api/faculty.js";
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

function AddFacultyDialog({ open, onOpenChange, onCreated }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation(createFaculty);
  const [name, setName] = useState("");
  const [department, setDepartment] = useState("");
  const [facultyType, setFacultyType] = useState("regular");
  const [weeklyMaxHours, setWeeklyMaxHours] = useState("24");

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute({
      name,
      department,
      faculty_type: facultyType,
      weekly_max_hours: weeklyMaxHours,
    });
    if (result.ok) {
      toast.success(result.data.message || "Faculty added.");
      onOpenChange(false);
      onCreated();
      emitOnSuccess(result, FACULTY_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not add faculty.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add faculty</DialogTitle>
          <DialogDescription>Roster entry with type and weekly hour limit.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationFailure error={error} />
          <div>
            <Label htmlFor="faculty-name">Name</Label>
            <Input
              id="faculty-name"
              className="mt-1.5"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={fieldErrors.name ? "faculty-name-error" : undefined}
            />
            <FieldError id="faculty-name-error" message={fieldErrors.name} />
          </div>
          <div>
            <Label htmlFor="faculty-department">Department</Label>
            <Input
              id="faculty-department"
              className="mt-1.5"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={fieldErrors.department ? "faculty-department-error" : undefined}
            />
            <FieldError id="faculty-department-error" message={fieldErrors.department} />
          </div>
          <div>
            <Label htmlFor="faculty-type">Type</Label>
            <Select value={facultyType} onValueChange={setFacultyType} disabled={isSubmitting}>
              <SelectTrigger id="faculty-type" className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="regular">Regular</SelectItem>
                <SelectItem value="inter-department">Inter-department</SelectItem>
                <SelectItem value="visiting">Visiting</SelectItem>
              </SelectContent>
            </Select>
            <FieldError id="faculty-type-error" message={fieldErrors.faculty_type} />
          </div>
          <div>
            <Label htmlFor="faculty-max-hours">Weekly max hours</Label>
            <Input
              id="faculty-max-hours"
              className="mt-1.5"
              type="number"
              value={weeklyMaxHours}
              onChange={(e) => setWeeklyMaxHours(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={fieldErrors.weekly_max_hours ? "faculty-max-hours-error" : undefined}
            />
            <FieldError id="faculty-max-hours-error" message={fieldErrors.weekly_max_hours} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Adding…" : "Add Faculty"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function FacultyPage() {
  const toast = useToast();
  const { data: faculty, error, isLoading, retry } = useApi(getFaculty, ["faculty"]);
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [pendingDelete, setPendingDelete] = useState(null);
  const deletion = useMutation(deleteFaculty);

  function openAddDialog() {
    setAddKey((key) => key + 1);
    setAddOpen(true);
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    const result = await deletion.execute(pendingDelete.id);
    if (result.ok) {
      toast.success(result.data.message || "Faculty deleted.");
      setPendingDelete(null);
      retry();
      emitOnSuccess(result, FACULTY_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not delete faculty.");
    }
  }

  if (isLoading && !faculty) {
    return (
      <Page title="Faculty" subtitle="Roster, weekly loads, availability, and soft scheduling preferences.">
        <PageLoading rows={6} label="Loading faculty…" />
      </Page>
    );
  }

  if (error && !faculty) {
    return (
      <Page title="Faculty" subtitle="Roster, weekly loads, availability, and soft scheduling preferences.">
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  return (
    <Page
      title="Faculty"
      subtitle={faculty.length === 0 ? "Roster, weekly loads, availability, and soft scheduling preferences." : `${faculty.length} faculty members`}
      actions={
        <Button onClick={openAddDialog}>
          <Plus aria-hidden="true" />
          Add Faculty
        </Button>
      }
    >
      {faculty.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No faculty yet"
          description="Add your first faculty member to get started."
          action={
            <Button onClick={openAddDialog} className="mt-2">
              <Plus aria-hidden="true" />
              Add Faculty
            </Button>
          }
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
                    <div className="flex justify-end gap-2">
                      <Button asChild variant="outline" size="sm">
                        <Link to={`/faculty/${member.id}/availability`} aria-label={`Availability for ${member.name}`}>
                          <CalendarClock aria-hidden="true" />
                          Availability
                        </Link>
                      </Button>
                      <Button asChild variant="outline" size="sm">
                        <Link to={`/faculty/${member.id}/preferences`} aria-label={`Scheduling preferences for ${member.name}`}>
                          <SlidersHorizontal aria-hidden="true" />
                          Preferences
                        </Link>
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPendingDelete(member)}
                        aria-label={`Delete faculty ${member.name}`}
                      >
                        <Trash2 aria-hidden="true" className="text-signal" />
                        Delete
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Panel>
      )}

      <AddFacultyDialog key={addKey} open={addOpen} onOpenChange={setAddOpen} onCreated={retry} />
      <DeleteConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
            deletion.reset();
          }
        }}
        title={`Delete faculty ${pendingDelete?.name ?? ""}?`}
        description="The faculty record will be removed. This cannot be undone."
        confirmLabel="Delete"
        onConfirm={handleDelete}
        isConfirming={deletion.isSubmitting}
        error={deletion.error}
      />
    </Page>
  );
}

export function FacultyAvailabilityPage() {
  const toast = useToast();
  const { fid } = useParams();
  const fetcher = useCallback(() => getFacultyAvailability(fid), [fid]);
  const { data, error, isLoading, retry } = useApi(fetcher, ["faculty"]);
  const saver = useMutation((unavailable) => saveFacultyAvailability(fid, unavailable));
  const [selected, setSelected] = useState(null);

  const savedSet = useMemo(() => new Set(data?.unavailable ?? []), [data]);
  const active = selected ?? savedSet;
  const isDirty =
    selected !== null &&
    (selected.size !== savedSet.size || [...selected].some((slot) => !savedSet.has(slot)));

  function toggleSlot(key) {
    setSelected((prev) => {
      const base = prev ?? savedSet;
      const next = new Set(base);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function handleSave(event) {
    event.preventDefault();
    const result = await saver.execute([...active]);
    if (result.ok) {
      toast.success(result.data.message || "Availability updated.");
      setSelected(new Set(result.data.unavailable ?? [...active]));
      retry();
      emitOnSuccess(result, FACULTY_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not save availability.");
    }
  }

  if (isLoading && !data) {
    return (
      <Page
        title="Faculty Availability"
        subtitle="Unavailable day × period slots per faculty member."
        breadcrumbs={[{ label: "Faculty", to: "/faculty" }, { label: "Availability" }]}
      >
        <PageLoading rows={6} label="Loading availability…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page
        title="Faculty Availability"
        subtitle="Unavailable day × period slots per faculty member."
        breadcrumbs={[{ label: "Faculty", to: "/faculty" }, { label: "Availability" }]}
      >
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const days = data.days ?? [];
  const periods = data.periods ?? [];
  const facultyName = data.faculty?.name ?? "Faculty";

  return (
    <Page
      title={`Availability — ${facultyName}`}
      subtitle="Check the boxes for slots this faculty member is NOT available."
      breadcrumbs={[{ label: "Faculty", to: "/faculty" }, { label: facultyName }]}
    >
      <form onSubmit={handleSave}>
        <Panel accent="steel" title="Unavailable slots">
          <MutationError error={saver.error} />
          <Table aria-label={`Unavailable slots for ${facultyName}`}>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Day \ Period</TableHead>
                {periods.map((period, index) => (
                  <TableHead key={`${period}-${index}`} scope="col" className="text-center tabular-nums">
                    {index}
                    <span className="block text-[0.7rem] font-normal text-muted-foreground">{period}</span>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {days.map((day) => (
                <TableRow key={day}>
                  <TableCell className="font-semibold text-ink">{day}</TableCell>
                  {periods.map((period, periodIndex) => {
                    const key = `${day}:${periodIndex}`;
                    const checked = active.has(key);
                    return (
                      <TableCell key={key} className="text-center">
                        <input
                          type="checkbox"
                          className="size-4 accent-[#B8873A]"
                          checked={checked}
                          onChange={() => toggleSlot(key)}
                          disabled={saver.isSubmitting}
                          aria-label={`${day} period ${periodIndex + 1} (${period}) unavailable`}
                        />
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button type="submit" disabled={saver.isSubmitting}>
              {saver.isSubmitting ? "Saving…" : "Save Availability"}
            </Button>
            <Button asChild variant="outline" disabled={saver.isSubmitting}>
              <Link to="/faculty">
                <ArrowLeft aria-hidden="true" />
                Cancel
              </Link>
            </Button>
            {isDirty && !saver.isSubmitting ? (
              <span className="text-xs text-muted-foreground">Unsaved changes.</span>
            ) : null}
          </div>
        </Panel>
      </form>
    </Page>
  );
}

const PREFERENCE_KINDS = [
  { value: "TIME_WINDOW", label: "Preferred time window" },
  { value: "DAY_OFF_PREFERENCE", label: "Preferred day off" },
];

function preferenceKindLabel(kind) {
  return PREFERENCE_KINDS.find((k) => k.value === kind)?.label ?? kind;
}

/**
 * Plain-language summary of one stored preference. Period indexes are
 * rendered with their configured time labels so administrators never
 * have to guess what "period 2" means.
 */
function describePreference(pref, periods) {
  const days = (pref.days ?? []).join(", ") || "all working days";
  if (pref.kind === "DAY_OFF_PREFERENCE") {
    return `Prefers no teaching on ${days}.`;
  }
  const label = (index) => {
    const text = periods?.[index];
    return text ? `period ${index} (${text})` : `period ${index}`;
  };
  return `Prefers teaching ${label(pref.start_period)} – ${label(pref.end_period)} (end-exclusive) on ${days}.`;
}

function PreferenceFormFields({
  kind,
  onKindChange,
  selectedDays,
  onToggleDay,
  startPeriod,
  onStartChange,
  endPeriod,
  onEndChange,
  weight,
  onWeightChange,
  enabled,
  onEnabledChange,
  allDays,
  periods,
  fieldErrors,
  disabled,
  idPrefix,
}) {
  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor={`${idPrefix}-kind`}>Preference kind</Label>
        <Select value={kind} onValueChange={onKindChange} disabled={disabled}>
          <SelectTrigger id={`${idPrefix}-kind`} className="mt-1.5">
            <SelectValue placeholder="Select a kind" />
          </SelectTrigger>
          <SelectContent>
            {PREFERENCE_KINDS.map((k) => (
              <SelectItem key={k.value} value={k.value}>
                {k.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <FieldError id={`${idPrefix}-kind-error`} message={fieldErrors.preference} />
      </div>
      <fieldset disabled={disabled}>
        <legend className="text-sm font-medium text-ink">
          {kind === "DAY_OFF_PREFERENCE" ? "Days off (at least one)" : "Days (blank means all working days)"}
        </legend>
        <div className="mt-1.5 flex flex-wrap gap-2">
          {allDays.map((day) => (
            <label
              key={day}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-sm"
            >
              <input
                type="checkbox"
                className="size-4 accent-[#B8873A]"
                checked={selectedDays.has(day)}
                onChange={() => onToggleDay(day)}
                aria-label={`Include ${day}`}
              />
              {day}
            </label>
          ))}
        </div>
      </fieldset>
      {kind === "TIME_WINDOW" ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor={`${idPrefix}-start`}>From period</Label>
            <Select value={startPeriod} onValueChange={onStartChange} disabled={disabled}>
              <SelectTrigger id={`${idPrefix}-start`} className="mt-1.5">
                <SelectValue placeholder="Start period" />
              </SelectTrigger>
              <SelectContent>
                {periods.map((period, index) => (
                  <SelectItem key={`${period}-${index}`} value={String(index)}>
                    {index} — {period}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor={`${idPrefix}-end`}>To period (exclusive)</Label>
            <Select value={endPeriod} onValueChange={onEndChange} disabled={disabled}>
              <SelectTrigger id={`${idPrefix}-end`} className="mt-1.5">
                <SelectValue placeholder="End period" />
              </SelectTrigger>
              <SelectContent>
                {periods.map((period, index) => (
                  <SelectItem key={`${period}-${index}`} value={String(index)}>
                    {index} — {period}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label htmlFor={`${idPrefix}-weight`}>Weight (1–10)</Label>
          <Select value={String(weight)} onValueChange={(next) => onWeightChange(Number(next))} disabled={disabled}>
            <SelectTrigger id={`${idPrefix}-weight`} className="mt-1.5">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Array.from({ length: 10 }, (_, i) => i + 1).map((w) => (
                <SelectItem key={w} value={String(w)}>
                  {w}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="mt-1 text-xs text-muted-foreground">
            Stored for future prioritization; every preference currently counts equally.
          </p>
        </div>
        <div className="flex items-end pb-1">
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm font-medium text-ink">
            <input
              type="checkbox"
              className="size-4 accent-[#B8873A]"
              checked={enabled}
              onChange={(e) => onEnabledChange(e.target.checked)}
              disabled={disabled}
            />
            Enabled (disabled preferences are ignored)
          </label>
        </div>
      </div>
    </div>
  );
}

function usePreferenceDraft(initial) {
  const [kind, setKind] = useState(initial?.kind ?? "TIME_WINDOW");
  const [selectedDays, setSelectedDays] = useState(() => new Set(initial?.days ?? []));
  const [startPeriod, setStartPeriod] = useState(
    initial?.start_period == null ? "" : String(initial.start_period)
  );
  const [endPeriod, setEndPeriod] = useState(
    initial?.end_period == null ? "" : String(initial.end_period)
  );
  const [weight, setWeight] = useState(initial?.weight ?? 5);
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);

  function toggleDay(day) {
    setSelectedDays((prev) => {
      const next = new Set(prev);
      if (next.has(day)) next.delete(day);
      else next.add(day);
      return next;
    });
  }

  function toPayload() {
    const payload = {
      kind,
      days: [...selectedDays],
      weight,
      enabled,
    };
    if (kind === "TIME_WINDOW") {
      payload.start_period = startPeriod === "" ? null : Number(startPeriod);
      payload.end_period = endPeriod === "" ? null : Number(endPeriod);
    } else {
      payload.start_period = null;
      payload.end_period = null;
    }
    return payload;
  }

  return {
    kind, setKind, selectedDays, toggleDay,
    startPeriod, setStartPeriod, endPeriod, setEndPeriod,
    weight, setWeight, enabled, setEnabled, toPayload,
  };
}

function AddPreferenceDialog({ open, onOpenChange, facultyId, allDays, periods, onSaved }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation((payload) =>
    createFacultyPreference(facultyId, payload)
  );
  const draft = usePreferenceDraft(null);

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute(draft.toPayload());
    if (result.ok) {
      toast.success(result.data.message || "Preference saved.");
      onOpenChange(false);
      onSaved();
      // Phase 6P: preferences are configuration for future generations only;
      // the existing generated timetable is intentionally NOT invalidated.
      emitOnSuccess(result, PREFERENCE_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not save preference.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add preference</DialogTitle>
          <DialogDescription>
            A soft scheduling hint for future timetable generations. It can never block a
            valid placement.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationFailure error={error} />
          <PreferenceFormFields
            idPrefix="pref-add"
            kind={draft.kind}
            onKindChange={draft.setKind}
            selectedDays={draft.selectedDays}
            onToggleDay={draft.toggleDay}
            startPeriod={draft.startPeriod}
            onStartChange={draft.setStartPeriod}
            endPeriod={draft.endPeriod}
            onEndChange={draft.setEndPeriod}
            weight={draft.weight}
            onWeightChange={draft.setWeight}
            enabled={draft.enabled}
            onEnabledChange={draft.setEnabled}
            allDays={allDays}
            periods={periods}
            fieldErrors={fieldErrors}
            disabled={isSubmitting}
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Saving…" : "Save Preference"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditPreferenceDialog({ preference, onOpenChange, allDays, periods, onSaved }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation((payload) =>
    updateFacultyPreference(preference.id, payload)
  );
  const draft = usePreferenceDraft(preference);

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute(draft.toPayload());
    if (result.ok) {
      toast.success(result.data.message || "Preference updated.");
      onOpenChange(false);
      onSaved();
      // Phase 6P: see above — future generations only, not the live schedule.
      emitOnSuccess(result, PREFERENCE_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not update preference.");
    }
  }

  return (
    <Dialog open={preference !== null} onOpenChange={isSubmitting ? undefined : () => onOpenChange(null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit preference</DialogTitle>
          <DialogDescription>
            Changes apply to future timetable generations; the current timetable is
            unchanged.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationFailure error={error} />
          <PreferenceFormFields
            idPrefix={`pref-edit-${preference.id}`}
            kind={draft.kind}
            onKindChange={draft.setKind}
            selectedDays={draft.selectedDays}
            onToggleDay={draft.toggleDay}
            startPeriod={draft.startPeriod}
            onStartChange={draft.setStartPeriod}
            endPeriod={draft.endPeriod}
            onEndChange={draft.setEndPeriod}
            weight={draft.weight}
            onWeightChange={draft.setWeight}
            enabled={draft.enabled}
            onEnabledChange={draft.setEnabled}
            allDays={allDays}
            periods={periods}
            fieldErrors={fieldErrors}
            disabled={isSubmitting}
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(null)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Saving…" : "Save Changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function FacultyPreferencesPage() {
  const toast = useToast();
  const { fid } = useParams();
  const fetcher = useCallback(() => getFacultyPreferences(fid), [fid]);
  const { data, error, isLoading, retry } = useApi(fetcher, ["preferences"]);
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [editing, setEditing] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  const deletion = useMutation(deleteFacultyPreference);

  async function handleDelete() {
    if (!pendingDelete) return;
    const result = await deletion.execute(pendingDelete.id);
    if (result.ok) {
      toast.success(result.data.message || "Preference deleted.");
      setPendingDelete(null);
      retry();
      emitOnSuccess(result, PREFERENCE_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not delete preference.");
    }
  }

  if (isLoading && !data) {
    return (
      <Page
        title="Faculty Preferences"
        subtitle="Soft scheduling hints for one faculty member."
        breadcrumbs={[{ label: "Faculty", to: "/faculty" }, { label: "Preferences" }]}
      >
        <PageLoading rows={5} label="Loading preferences…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page
        title="Faculty Preferences"
        subtitle="Soft scheduling hints for one faculty member."
        breadcrumbs={[{ label: "Faculty", to: "/faculty" }, { label: "Preferences" }]}
      >
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const facultyName = data.faculty?.name ?? "Faculty";
  const allDays = data.days ?? [];
  const periods = data.periods ?? [];
  const preferences = data.preferences ?? [];

  return (
    <Page
      title={`Preferences — ${facultyName}`}
      subtitle={`${preferences.length} soft preference${preferences.length === 1 ? "" : "s"} (future generations only)`}
      breadcrumbs={[{ label: "Faculty", to: "/faculty" }, { label: facultyName }]}
      actions={
        <Button
          onClick={() => {
            setAddKey((key) => key + 1);
            setAddOpen(true);
          }}
        >
          <Plus aria-hidden="true" />
          Add Preference
        </Button>
      }
    >
      <Alert variant="info" className="mb-4">
        <SlidersHorizontal aria-hidden="true" />
        <AlertTitle>Soft preferences — not unavailability</AlertTitle>
        <AlertDescription>
          Preferences only nudge <strong>future</strong> timetable generations toward
          convenient slots; a class may still be scheduled outside a preference when
          nothing better fits, and saving here never moves the current timetable. Hard
          blocks stay on the{" "}
          <Link className="underline" to={`/faculty/${fid}/availability`}>
            availability grid
          </Link>
          , where a checked slot can never hold a class.
        </AlertDescription>
      </Alert>
      {preferences.length === 0 ? (
        <EmptyState
          icon={SlidersHorizontal}
          title="No preferences yet"
          description="Add a preferred time window or a preferred day off. The scheduler treats them as hints, never as hard rules."
          action={
            <Button
              onClick={() => {
                setAddKey((key) => key + 1);
                setAddOpen(true);
              }}
              className="mt-2"
            >
              <Plus aria-hidden="true" />
              Add Preference
            </Button>
          }
        />
      ) : (
        <Panel accent="brass" title="Configured preferences">
          <Table aria-label={`Scheduling preferences for ${facultyName}`}>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Kind</TableHead>
                <TableHead scope="col">Preference</TableHead>
                <TableHead scope="col">Status</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {preferences.map((pref) => (
                <TableRow key={pref.id}>
                  <TableCell className="font-medium text-ink">{preferenceKindLabel(pref.kind)}</TableCell>
                  <TableCell>{describePreference(pref, periods)}</TableCell>
                  <TableCell>
                    <Badge variant={pref.enabled ? "secondary" : "outline"}>
                      {pref.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button variant="outline" size="sm" onClick={() => setEditing(pref)}>
                        Edit
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPendingDelete(pref)}
                        aria-label={`Delete preference ${preferenceKindLabel(pref.kind)}`}
                      >
                        <Trash2 aria-hidden="true" className="text-signal" />
                        Delete
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-3 text-xs text-muted-foreground">
            Preferences affect future schedule generation, not the already-generated
            timetable. Moving a class away from a preference in the timetable editor
            remains valid.
          </p>
        </Panel>
      )}
      <AddPreferenceDialog
        key={addKey}
        open={addOpen}
        onOpenChange={setAddOpen}
        facultyId={fid}
        allDays={allDays}
        periods={periods}
        onSaved={retry}
      />
      {editing ? (
        <EditPreferenceDialog
          key={editing.id}
          preference={editing}
          onOpenChange={(next) => {
            if (next === null) setEditing(null);
          }}
          allDays={allDays}
          periods={periods}
          onSaved={retry}
        />
      ) : null}
      <DeleteConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
            deletion.reset();
          }
        }}
        title="Delete this preference?"
        description="The scheduler will no longer consider it in future generations. The current timetable is unchanged."
        confirmLabel="Delete"
        onConfirm={handleDelete}
        isConfirming={deletion.isSubmitting}
        error={deletion.error}
      />
    </Page>
  );
}
