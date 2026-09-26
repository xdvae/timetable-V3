import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, Layers, Plus, Trash2, UsersRound } from "lucide-react";

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
import { DeleteConfirmDialog, FailureList, FieldError, MutationError } from "@/components/feedback/mutation.jsx";
import { getFailures } from "@/lib/failures.js";
import { emitOnSuccess, ENROLLMENTS_DOMAINS, PREFERRED_ROOM_DOMAINS } from "@/lib/propagation.js";
import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import {
  createEnrollment,
  deleteEnrollment,
  getEnrollmentSections,
  getEnrollments,
  setPreferredTheoryRoom,
} from "@/services/api/enrollments.js";
import { getRooms } from "@/services/api/rooms.js";

function AddEnrollmentDialog({ open, onOpenChange, onCreated, programs }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation(createEnrollment);
  const [programId, setProgramId] = useState(programs[0]?.id != null ? String(programs[0].id) : "");
  const [yearLabel, setYearLabel] = useState("");
  const [totalStudents, setTotalStudents] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute({
      program_id: programId,
      year_label: yearLabel,
      total_students: totalStudents,
    });
    if (result.ok) {
      toast.success(result.data.message || "Enrollment added.");
      onOpenChange(false);
      onCreated();
      emitOnSuccess(result, ENROLLMENTS_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not add enrollment.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add enrollment</DialogTitle>
          <DialogDescription>
            Sections and lab groups are auto-generated from the student count.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationError error={error && !error.fieldErrors ? error : null} />
          <div>
            <Label htmlFor="enrollment-program">Program</Label>
            <Select value={programId} onValueChange={setProgramId} disabled={isSubmitting}>
              <SelectTrigger id="enrollment-program" className="mt-1.5">
                <SelectValue placeholder="Select a program" />
              </SelectTrigger>
              <SelectContent>
                {programs.map((program) => (
                  <SelectItem key={program.id} value={String(program.id)}>
                    {program.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldError id="enrollment-program-error" message={fieldErrors.program_id} />
          </div>
          <div>
            <Label htmlFor="enrollment-year">Year / Semester label</Label>
            <Input
              id="enrollment-year"
              className="mt-1.5"
              required
              value={yearLabel}
              onChange={(e) => setYearLabel(e.target.value)}
              placeholder="e.g. 1st Year or Sem II"
              disabled={isSubmitting}
              aria-describedby={fieldErrors.year_label ? "enrollment-year-error" : undefined}
            />
            <FieldError id="enrollment-year-error" message={fieldErrors.year_label} />
          </div>
          <div>
            <Label htmlFor="enrollment-students">Total students</Label>
            <Input
              id="enrollment-students"
              className="mt-1.5"
              type="number"
              required
              value={totalStudents}
              onChange={(e) => setTotalStudents(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={fieldErrors.total_students ? "enrollment-students-error" : undefined}
            />
            <FieldError id="enrollment-students-error" message={fieldErrors.total_students} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || programs.length === 0}>
              {isSubmitting ? "Adding…" : "Add Enrollment"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function EnrollmentsPage() {
  const toast = useToast();
  const { data, error, isLoading, retry } = useApi(getEnrollments, ["enrollments"]);
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [pendingDelete, setPendingDelete] = useState(null);
  const deletion = useMutation(deleteEnrollment);

  function openAddDialog() {
    setAddKey((key) => key + 1);
    setAddOpen(true);
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    const result = await deletion.execute(pendingDelete.id);
    if (result.ok) {
      toast.success(result.data.message || "Enrollment deleted.");
      setPendingDelete(null);
      retry();
      emitOnSuccess(result, ENROLLMENTS_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not delete enrollment.");
    }
  }

  if (isLoading && !data) {
    return (
      <Page
        title="Enrollments & Sections"
        subtitle="Cohorts with auto-generated sections and lab groups."
      >
        <PageLoading rows={6} label="Loading enrollments…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page
        title="Enrollments & Sections"
        subtitle="Cohorts with auto-generated sections and lab groups."
      >
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const enrollments = data.enrollments ?? [];
  const programs = data.programs ?? [];
  const deleteLabel = pendingDelete
    ? `${pendingDelete.program_name} ${pendingDelete.year_label}`
    : "";

  return (
    <Page
      title="Enrollments & Sections"
      subtitle={
        enrollments.length === 0
          ? "Cohorts with auto-generated sections and lab groups."
          : `${enrollments.length} ${enrollments.length === 1 ? "enrollment" : "enrollments"} · program → enrollment → section → lab group`
      }
      actions={
        <Button onClick={openAddDialog}>
          <Plus aria-hidden="true" />
          Add Enrollment
        </Button>
      }
    >
      {enrollments.length === 0 ? (
        <EmptyState
          icon={UsersRound}
          title="No enrollments yet"
          description={
            programs.length === 0
              ? "Add a program first, then add your first enrollment cohort."
              : "Add your first enrollment cohort to get started."
          }
          action={
            <Button onClick={openAddDialog} className="mt-2">
              <Plus aria-hidden="true" />
              Add Enrollment
            </Button>
          }
        />
      ) : (
        <Panel accent="steel" title="All enrollments">
          <Table aria-label="Enrollments">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Program</TableHead>
                <TableHead scope="col">Year</TableHead>
                <TableHead scope="col">Total Students</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {enrollments.map((enrollment) => (
                <TableRow key={enrollment.id}>
                  <TableCell className="font-medium text-ink">{enrollment.program_name}</TableCell>
                  <TableCell>{enrollment.year_label}</TableCell>
                  <TableCell className="tabular-nums">
                    {enrollment.total_students} students
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button asChild variant="outline" size="sm">
                        <Link
                          to={`/enrollments/${enrollment.id}/sections`}
                          aria-label={`View sections for ${enrollment.program_name} ${enrollment.year_label}`}
                        >
                          <Layers aria-hidden="true" />
                          View Sections
                        </Link>
                      </Button>
                      <Button asChild variant="outline" size="sm">
                        <Link
                          to={`/enrollments/${enrollment.id}/specializations`}
                          aria-label={`Manage specializations for ${enrollment.program_name} ${enrollment.year_label}`}
                        >
                          Specializations
                        </Link>
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPendingDelete(enrollment)}
                        aria-label={`Delete enrollment ${enrollment.program_name} ${enrollment.year_label}`}
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

      <AddEnrollmentDialog
        key={addKey}
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={retry}
        programs={programs}
      />
      <DeleteConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
            deletion.reset();
          }
        }}
        title={`Delete enrollment ${deleteLabel}?`}
        description="This also deletes its sections and lab groups. This cannot be undone."
        confirmLabel="Delete"
        onConfirm={handleDelete}
        isConfirming={deletion.isSubmitting}
        error={deletion.error}
      />
    </Page>
  );
}

function roomLabel(room) {
  const kind = room.room_type === "lab" ? "Lab" : "Classroom";
  return `${room.name} — ${kind} — ${room.capacity} seats`;
}

/**
 * Per-section preferred theory room editor. Inline select + save using
 * the shared mutation/toast/feedback patterns; the parent refetches
 * authoritative section data via onSaved. Never touches the timetable:
 * the preference only affects future generations.
 */
function PreferredRoomControl({ section, rooms, roomsLoading, roomsUnavailable, onSaved }) {
  const toast = useToast();
  const { execute, isSubmitting, error } = useMutation(({ sectionId, roomId }) =>
    setPreferredTheoryRoom(sectionId, roomId)
  );
  const current = section.preferred_theory_room_id ?? null;
  const [selected, setSelected] = useState(current == null ? "none" : String(current));
  const [touched, setTouched] = useState(false);
  const failures = getFailures(error);
  const stale =
    current != null && !(rooms ?? []).some((room) => String(room.id) === String(current));
  // A stale (dangling) preference displays as "No preferred room" with an
  // explanatory note above until the user picks a value; it is never
  // silently replaced.
  const effectiveValue = !touched && stale ? "none" : selected;
  const normalized = effectiveValue === "none" ? null : Number(effectiveValue);
  const unchanged = normalized === current;
  const disabled = isSubmitting || roomsLoading || roomsUnavailable || (rooms ?? []).length === 0;

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute({ sectionId: section.id, roomId: normalized });
    if (result.ok) {
      toast.success(result.data.message || "Preferred room saved.");
      const warning = result.data.warning;
      if (warning) {
        toast.warning(warning.message || "Room saved with a warning.", {
          title: "Preferred room",
        });
      }
      onSaved();
      // Phase 6P: a section preference for future generations only; the
      // existing generated timetable is intentionally NOT invalidated.
      emitOnSuccess(result, PREFERRED_ROOM_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not save preferred room.");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-4 space-y-3 border-t pt-4">
      <div>
        <Label htmlFor={`preferred-room-${section.id}`}>Preferred theory room</Label>
        {stale ? (
          <p className="mt-1 text-xs font-medium text-signal" role="alert">
            Previously set room (ID {current}) is no longer available. Pick a room or
            save “No preferred room” to clear it.
          </p>
        ) : null}
        <Select
          value={effectiveValue}
          onValueChange={(next) => {
            setSelected(next);
            setTouched(true);
          }}
          disabled={disabled}
        >
          <SelectTrigger id={`preferred-room-${section.id}`} className="mt-1.5">
            <SelectValue placeholder={roomsLoading ? "Loading rooms…" : "Select a room"} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">No preferred room</SelectItem>
            {(rooms ?? []).map((room) => (
              <SelectItem key={room.id} value={String(room.id)}>
                {roomLabel(room)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {failures.length > 0 ? (
        <FailureList failures={failures} />
      ) : (
        <MutationError error={error} />
      )}
      <p className="text-xs text-muted-foreground">
        Preferred room is a scheduling preference. If it is unavailable or
        incompatible, the scheduler may use another valid room. Applies to future
        timetable generations; the current timetable is unchanged.
      </p>
      <div>
        <Button type="submit" size="sm" disabled={disabled || unchanged}>
          {isSubmitting ? "Saving…" : "Save Preferred Room"}
        </Button>
      </div>
    </form>
  );
}

export function SectionsPage() {
  const { eid } = useParams();
  const fetcher = useCallback(() => getEnrollmentSections(eid), [eid]);
  const { data, error, isLoading, retry } = useApi(fetcher, ["sections"]);
  const roomsQuery = useApi(getRooms, ["rooms"]);

  if (isLoading && !data) {
    return (
      <Page
        title="Sections"
        subtitle="Auto-generated sections and lab groups for one enrollment."
        breadcrumbs={[
          { label: "Enrollments", to: "/enrollments" },
          { label: "Sections" },
        ]}
      >
        <PageLoading rows={5} label="Loading sections…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page
        title="Sections"
        subtitle="Auto-generated sections and lab groups for one enrollment."
        breadcrumbs={[
          { label: "Enrollments", to: "/enrollments" },
          { label: "Sections" },
        ]}
      >
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const enrollment = data.enrollment ?? {};
  const sections = data.sections ?? [];
  const rooms = roomsQuery.data ?? [];
  const roomsLoading = roomsQuery.isLoading && !roomsQuery.data;
  const roomsUnavailable = roomsQuery.error != null && !roomsQuery.data;
  const labGroupCount = sections.reduce(
    (total, section) => total + (section.lab_groups?.length ?? 0),
    0
  );
  const contextLabel = `${enrollment.program_name ?? "?"} · ${enrollment.year_label ?? "?"}`;

  return (
    <Page
      title={`Sections — ${contextLabel}`}
      subtitle={
        sections.length === 0
          ? "Auto-generated sections and lab groups for one enrollment."
          : `${sections.length} ${sections.length === 1 ? "section" : "sections"} · ${labGroupCount} lab ${labGroupCount === 1 ? "group" : "groups"} · ${enrollment.total_students ?? 0} students total`
      }
      breadcrumbs={[
        { label: "Enrollments", to: "/enrollments" },
        { label: contextLabel },
      ]}
      actions={
        <div className="flex gap-2">
          <Button asChild size="sm">
            <Link to={`/enrollments/${eid}/specializations`}>
              <Layers aria-hidden="true" />
              Specializations
            </Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link to="/enrollments">
              <ArrowLeft aria-hidden="true" />
              Back to Enrollments
            </Link>
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        <Panel
          accent="brass"
          title="Enrollment"
          description="Program, year, and total students for this cohort."
        >
          <dl className="grid gap-3 sm:grid-cols-3">
            <div>
              <dt className="text-xs text-muted-foreground">Program</dt>
              <dd className="mt-0.5 text-sm font-medium text-ink">
                {enrollment.program_name ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Year</dt>
              <dd className="mt-0.5 text-sm font-medium text-ink">
                {enrollment.year_label ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Total students</dt>
              <dd className="mt-0.5 text-sm font-medium text-ink tabular-nums">
                {enrollment.total_students ?? "—"}
              </dd>
            </div>
          </dl>
        </Panel>

        {sections.length === 0 ? (
          <EmptyState
            icon={Layers}
            title="No sections for this enrollment"
            description="Sections are auto-generated when the enrollment is created in the backend."
          />
        ) : (
          <div className="grid gap-5 xl:grid-cols-2">
            {sections.map((section) => (
              <Panel
                key={section.id}
                accent="steel"
                title={section.name}
                description={`${section.student_count} students · ${section.lab_groups?.length ?? 0} lab ${(section.lab_groups?.length ?? 0) === 1 ? "group" : "groups"}`}
              >
                {(section.lab_groups?.length ?? 0) === 0 ? (
                  <p className="text-sm text-muted-foreground">No lab groups in this section.</p>
                ) : (
                  <Table aria-label={`Lab groups in ${section.name}`}>
                    <TableHeader>
                      <TableRow>
                        <TableHead scope="col">Lab Group</TableHead>
                        <TableHead scope="col">Students</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(section.lab_groups ?? []).map((group) => (
                        <TableRow key={group.id}>
                          <TableCell>
                            <Badge variant="secondary">{group.name}</Badge>
                          </TableCell>
                          <TableCell className="tabular-nums">
                            {group.student_count} students
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
                {roomsUnavailable ? (
                  <p className="mt-4 text-xs font-medium text-signal" role="alert">
                    Room list unavailable — preferred room cannot be changed right now.
                  </p>
                ) : (
                  <PreferredRoomControl
                    key={`${section.id}-${section.preferred_theory_room_id ?? "none"}`}
                    section={section}
                    rooms={rooms}
                    roomsLoading={roomsLoading}
                    roomsUnavailable={false}
                    onSaved={retry}
                  />
                )}
              </Panel>
            ))}
          </div>
        )}
      </div>
    </Page>
  );
}
