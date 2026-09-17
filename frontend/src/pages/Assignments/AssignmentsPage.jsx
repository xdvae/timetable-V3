import { useState } from "react";
import { ClipboardCheck, Plus, Trash2 } from "lucide-react";

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
import { createAssignment, deleteAssignment, getAssignments } from "@/services/api/assignments.js";

function SessionTypeBadge({ sessionType }) {
  const isPractical = sessionType === "practical";
  return <Badge variant={isPractical ? "lab" : "theory"}>{isPractical ? "Lab" : "Theory"}</Badge>;
}

/**
 * Add-assignment form mirroring the Jinja assignment form: picking a subject
 * auto-fills its usual hours (still fully editable), and the group selector
 * switches between sections (theory) and lab groups (practical). The
 * block-length rule and load accounting stay server-side.
 */
function AddAssignmentDialog({ open, onOpenChange, onCreated, options }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation(createAssignment);
  const { faculty, subjects, sections, labGroups, subjectDefaults } = options;
  const [facultyId, setFacultyId] = useState(faculty[0]?.id != null ? String(faculty[0].id) : "");
  const [subjectId, setSubjectId] = useState(subjects[0]?.id != null ? String(subjects[0].id) : "");
  const [sessionType, setSessionType] = useState("theory");
  const [sectionId, setSectionId] = useState(sections[0]?.id != null ? String(sections[0].id) : "");
  const [labGroupId, setLabGroupId] = useState(labGroups[0]?.id != null ? String(labGroups[0].id) : "");
  const [periodsPerWeek, setPeriodsPerWeek] = useState("3");
  const [blockLength, setBlockLength] = useState("1");

  function applyDefaults(nextSubjectId, nextType) {
    const defaults = subjectDefaults[nextSubjectId];
    if (!defaults) return;
    if (nextType === "theory" && defaults.theory) {
      setPeriodsPerWeek(String(defaults.theory));
      setBlockLength("1");
    } else if (nextType === "practical" && defaults.practical) {
      setPeriodsPerWeek(String(defaults.practical));
      setBlockLength(String(defaults.block || 2));
    }
  }

  function handleSubjectChange(nextSubjectId) {
    setSubjectId(nextSubjectId);
    applyDefaults(nextSubjectId, sessionType);
  }

  function handleTypeChange(nextType) {
    setSessionType(nextType);
    applyDefaults(subjectId, nextType);
  }

  const missing = [];
  if (faculty.length === 0) missing.push("faculty");
  if (subjects.length === 0) missing.push("subjects");
  if (sessionType === "theory" && sections.length === 0) missing.push("sections");
  if (sessionType === "practical" && labGroups.length === 0) missing.push("lab groups");

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute({
      faculty_id: facultyId,
      subject_id: subjectId,
      session_type: sessionType,
      section_id: sessionType === "theory" ? sectionId : "",
      lab_group_id: sessionType === "practical" ? labGroupId : "",
      periods_per_week: periodsPerWeek,
      block_length: blockLength,
    });
    if (result.ok) {
      const message = result.data.message || "Teaching assignment added.";
      if (result.data.category === "warning") toast.warning(message, { title: "Assignment added" });
      else toast.success(message, { title: "Assignment added" });
      onOpenChange(false);
      onCreated();
    } else if (result.error) {
      toast.error(result.error.message || "Could not add assignment.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add assignment</DialogTitle>
          <DialogDescription>
            Who teaches what, to which section (theory) or lab group (practical), and how many
            hours/week. Picking a subject auto-fills its usual hours — still fully editable.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationError error={error && !error.fieldErrors ? error : null} />
          {missing.length > 0 ? (
            <p className="text-sm font-medium text-signal" role="alert">
              Add {missing.join(", ")} first before creating an assignment.
            </p>
          ) : null}
          <div>
            <Label htmlFor="assignment-faculty">Faculty</Label>
            <Select value={facultyId} onValueChange={setFacultyId} disabled={isSubmitting}>
              <SelectTrigger id="assignment-faculty" className="mt-1.5">
                <SelectValue placeholder="Select faculty" />
              </SelectTrigger>
              <SelectContent>
                {faculty.map((member) => (
                  <SelectItem key={member.id} value={String(member.id)}>
                    {member.name} — {member.weekly_load ?? 0} hrs/wk currently
                    {member.weekly_max_hours ? ` (max ${member.weekly_max_hours})` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldError id="assignment-faculty-error" message={fieldErrors.faculty_id} />
          </div>
          <div>
            <Label htmlFor="assignment-subject">Subject</Label>
            <Select value={subjectId} onValueChange={handleSubjectChange} disabled={isSubmitting}>
              <SelectTrigger id="assignment-subject" className="mt-1.5">
                <SelectValue placeholder="Select a subject" />
              </SelectTrigger>
              <SelectContent>
                {subjects.map((subject) => (
                  <SelectItem key={subject.id} value={String(subject.id)}>
                    {subject.name} ({subject.program_name} {subject.year_label})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldError id="assignment-subject-error" message={fieldErrors.subject_id} />
          </div>
          <div>
            <Label htmlFor="assignment-type">Session type</Label>
            <Select value={sessionType} onValueChange={handleTypeChange} disabled={isSubmitting}>
              <SelectTrigger id="assignment-type" className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="theory">Theory</SelectItem>
                <SelectItem value="practical">Practical (Lab)</SelectItem>
              </SelectContent>
            </Select>
            <FieldError id="assignment-type-error" message={fieldErrors.session_type} />
          </div>
          {sessionType === "theory" ? (
            <div>
              <Label htmlFor="assignment-section">Section</Label>
              <Select value={sectionId} onValueChange={setSectionId} disabled={isSubmitting}>
                <SelectTrigger id="assignment-section" className="mt-1.5">
                  <SelectValue placeholder="Select a section" />
                </SelectTrigger>
                <SelectContent>
                  {sections.map((section) => (
                    <SelectItem key={section.id} value={String(section.id)}>
                      {section.name} ({section.student_count})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldError id="assignment-section-error" message={fieldErrors.section_id} />
            </div>
          ) : (
            <div>
              <Label htmlFor="assignment-labgroup">Lab Group</Label>
              <Select value={labGroupId} onValueChange={setLabGroupId} disabled={isSubmitting}>
                <SelectTrigger id="assignment-labgroup" className="mt-1.5">
                  <SelectValue placeholder="Select a lab group" />
                </SelectTrigger>
                <SelectContent>
                  {labGroups.map((group) => (
                    <SelectItem key={group.id} value={String(group.id)}>
                      {group.name} ({group.student_count})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldError id="assignment-labgroup-error" message={fieldErrors.lab_group_id} />
            </div>
          )}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="assignment-periods">Hours/week</Label>
              <Input
                id="assignment-periods"
                className="mt-1.5"
                type="number"
                min="1"
                required
                value={periodsPerWeek}
                onChange={(e) => setPeriodsPerWeek(e.target.value)}
                disabled={isSubmitting}
                aria-describedby={fieldErrors.periods_per_week ? "assignment-periods-error" : undefined}
              />
              <FieldError id="assignment-periods-error" message={fieldErrors.periods_per_week} />
            </div>
            <div>
              <Label htmlFor="assignment-block">Block length (hrs/session)</Label>
              <Input
                id="assignment-block"
                className="mt-1.5"
                type="number"
                min="1"
                required
                value={blockLength}
                onChange={(e) => setBlockLength(e.target.value)}
                disabled={isSubmitting}
                aria-describedby={fieldErrors.block_length ? "assignment-block-error" : undefined}
              />
              <FieldError id="assignment-block-error" message={fieldErrors.block_length} />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            1 = one-hour theory class. Labs default to a 2-hr block — set to 1 to split a lab into two
            1-hr sessions instead.
          </p>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || missing.length > 0}>
              {isSubmitting ? "Adding…" : "Add Assignment"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function AssignmentsPage() {
  const toast = useToast();
  const { data, error, isLoading, retry } = useApi(getAssignments);
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [pendingDelete, setPendingDelete] = useState(null);
  const deletion = useMutation(deleteAssignment);

  function openAddDialog() {
    setAddKey((key) => key + 1);
    setAddOpen(true);
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    const result = await deletion.execute(pendingDelete.id);
    if (result.ok) {
      toast.success(result.data.message || "Assignment deleted.");
      setPendingDelete(null);
      retry();
    } else if (result.error) {
      toast.error(result.error.message || "Could not delete assignment.");
    }
  }

  if (isLoading && !data) {
    return (
      <Page
        title="Teaching Assignments"
        subtitle="Who teaches what, to which section or lab group."
      >
        <PageLoading rows={6} label="Loading teaching assignments…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page
        title="Teaching Assignments"
        subtitle="Who teaches what, to which section or lab group."
      >
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const assignments = data.assignments ?? [];
  const deleteLabel = pendingDelete
    ? `${pendingDelete.faculty_name} — ${pendingDelete.subject_name} (${pendingDelete.group})`
    : "";

  return (
    <Page
      title="Teaching Assignments"
      subtitle={
        assignments.length === 0
          ? "Who teaches what, to which section or lab group."
          : `${assignments.length} ${assignments.length === 1 ? "assignment" : "assignments"} · the main input to timetable generation`
      }
      actions={
        <Button onClick={openAddDialog}>
          <Plus aria-hidden="true" />
          Add Assignment
        </Button>
      }
    >
      {assignments.length === 0 ? (
        <EmptyState
          icon={ClipboardCheck}
          title="No teaching assignments yet"
          description="Add your first assignment: faculty, subject, group, session type, and weekly periods."
          action={
            <Button onClick={openAddDialog} className="mt-2">
              <Plus aria-hidden="true" />
              Add Assignment
            </Button>
          }
        />
      ) : (
        <Panel accent="steel" title="All teaching assignments">
          <Table aria-label="Teaching assignments">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Faculty</TableHead>
                <TableHead scope="col">Subject</TableHead>
                <TableHead scope="col">Group / Section</TableHead>
                <TableHead scope="col">Session Type</TableHead>
                <TableHead scope="col">Periods / Week</TableHead>
                <TableHead scope="col">Block Length</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {assignments.map((assignment) => (
                <TableRow key={assignment.id}>
                  <TableCell className="font-medium text-ink">{assignment.faculty_name}</TableCell>
                  <TableCell>{assignment.subject_name}</TableCell>
                  <TableCell>{assignment.group}</TableCell>
                  <TableCell>
                    <SessionTypeBadge sessionType={assignment.session_type} />
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {assignment.periods_per_week} / week
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {assignment.block_length} {assignment.block_length === 1 ? "period" : "periods"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPendingDelete(assignment)}
                      aria-label={`Delete assignment ${assignment.faculty_name} ${assignment.subject_name} ${assignment.group}`}
                    >
                      <Trash2 aria-hidden="true" className="text-signal" />
                      Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Panel>
      )}

      <AddAssignmentDialog
        key={addKey}
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={retry}
        options={{
          faculty: data.faculty ?? [],
          subjects: data.subjects ?? [],
          sections: data.sections ?? [],
          labGroups: data.labGroups ?? [],
          subjectDefaults: data.subjectDefaults ?? {},
        }}
      />
      <DeleteConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
            deletion.reset();
          }
        }}
        title="Delete this assignment?"
        description={`${deleteLabel} will be removed. This cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={handleDelete}
        isConfirming={deletion.isSubmitting}
        error={deletion.error}
      />
    </Page>
  );
}
