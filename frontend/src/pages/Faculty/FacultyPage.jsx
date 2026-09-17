import { useCallback, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, CalendarClock, Plus, Trash2, Users } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
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
import { DeleteConfirmDialog, FieldError, MutationError } from "@/components/feedback/mutation.jsx";
import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import {
  createFaculty,
  deleteFaculty,
  getFaculty,
  getFacultyAvailability,
  saveFacultyAvailability,
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
          <MutationError error={error && !error.fieldErrors ? error : null} />
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
  const { data: faculty, error, isLoading, retry } = useApi(getFaculty);
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
    } else if (result.error) {
      toast.error(result.error.message || "Could not delete faculty.");
    }
  }

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
  const { data, error, isLoading, retry } = useApi(fetcher);
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
