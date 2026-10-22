import { useState } from "react";
import { ArrowLeftRight, ClipboardCheck, Plus, Repeat, Trash2 } from "lucide-react";

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
import { DeleteConfirmDialog, FailureList, FieldError, LoadWarning, MutationError, MutationFailure } from "@/components/feedback/mutation.jsx";
import { getFailures } from "@/lib/failures.js";
import { ASSIGNMENT_WRITE_DOMAINS, emitOnSuccess, REASSIGN_DOMAINS, SWAP_DOMAINS } from "@/lib/propagation.js";
import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import {
  createAssignment,
  deleteAssignment,
  getAssignments,
  reassignFaculty,
  swapFaculty,
  validateFacultySwap,
  validateReassignFaculty,
} from "@/services/api/assignments.js";

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
      // Phase 6P: assignment rows changed (load/counts derived in overview).
      // Persisted schedule rows are untouched until the next generation.
      emitOnSuccess(result, ASSIGNMENT_WRITE_DOMAINS);
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
          <MutationFailure error={error} />
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

function assignmentLabel(assignment) {
  if (!assignment) return "";
  return `${assignment.faculty_name} — ${assignment.subject_name} (${assignment.group})`;
}

/**
 * Reassign one assignment's faculty: pick a target, dry-run validate,
 * confirm, then apply. Placements never move (no regeneration); the
 * mutation endpoint stays authoritative. Refresh is owned by the parent
 * via onApplied.
 */
function ReassignFacultyDialog({ open, onOpenChange, onApplied, assignment, faculty }) {
  const toast = useToast();
  const options = (faculty ?? []).filter(
    (member) => String(member.id) !== String(assignment.faculty_id)
  );
  const [targetId, setTargetId] = useState(
    options[0] != null ? String(options[0].id) : ""
  );
  const [phase, setPhase] = useState("select");
  const [validResult, setValidResult] = useState(null);
  const validate = useMutation(({ assignmentId, facultyId }) =>
    validateReassignFaculty(assignmentId, facultyId)
  );
  const apply = useMutation(({ assignmentId, facultyId }) =>
    reassignFaculty(assignmentId, facultyId)
  );
  const busy = validate.isSubmitting || apply.isSubmitting;
  const target = (faculty ?? []).find((member) => String(member.id) === targetId);

  function handleTargetChange(nextId) {
    setTargetId(nextId);
    setPhase("select");
    setValidResult(null);
    validate.reset();
    apply.reset();
  }

  function handleBack() {
    setPhase("select");
    apply.reset();
  }

  async function handleValidate(event) {
    event.preventDefault();
    const result = await validate.execute({
      assignmentId: assignment.id,
      facultyId: targetId,
    });
    if (result.ok) {
      setValidResult(result.data);
      setPhase("confirm");
    } else if (result.error) {
      toast.error(result.error.message || "Could not validate reassignment.");
    }
  }

  async function handleConfirm() {
    const result = await apply.execute({
      assignmentId: assignment.id,
      facultyId: targetId,
    });
    if (result.ok) {
      toast.success(result.data.message || "Faculty reassigned.");
      const warning = result.data?.result?.warning;
      if (warning?.exceeded) {
        toast.warning(warning.message || "Weekly load exceeded.", { title: "Weekly load" });
      }
      onApplied();
      // Phase 6P: ownership + class faculty labels + loads changed. A true
      // noop writes nothing and emits nothing. Validation never reaches here.
      emitOnSuccess(result, REASSIGN_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not reassign faculty.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={busy ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reassign faculty</DialogTitle>
          <DialogDescription>
            {assignmentLabel(assignment)} · {assignment.periods_per_week} hrs/week
          </DialogDescription>
        </DialogHeader>
        {phase === "select" ? (
          <form onSubmit={handleValidate} className="space-y-4">
            <MutationFailure error={validate.error} />
            {options.length === 0 ? (
              <p className="text-sm font-medium text-signal" role="alert">
                No other faculty available for reassignment.
              </p>
            ) : (
              <div>
                <Label htmlFor="reassign-faculty">New faculty</Label>
                <Select value={targetId} onValueChange={handleTargetChange} disabled={busy}>
                  <SelectTrigger id="reassign-faculty" className="mt-1.5">
                    <SelectValue placeholder="Select faculty" />
                  </SelectTrigger>
                  <SelectContent>
                    {options.map((member) => (
                      <SelectItem key={member.id} value={String(member.id)}>
                        {member.name} — {member.weekly_load ?? 0} hrs/wk currently
                        {member.weekly_max_hours ? ` (max ${member.weekly_max_hours})` : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              Current faculty: {assignment.faculty_name}. Validation runs first — nothing
              changes until you confirm.
            </p>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" disabled={busy || !targetId}>
                {validate.isSubmitting ? "Validating…" : "Validate Reassignment"}
              </Button>
            </DialogFooter>
          </form>
        ) : validResult?.noop ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              This assignment already uses {assignment.faculty_name}; nothing to change.
            </p>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Close
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4">
            <MutationFailure error={apply.error} />
            <div className="rounded-lg border px-4 py-3 text-sm">
              <p className="font-medium text-ink">{assignmentLabel(assignment)}</p>
              <p className="mt-1 text-muted-foreground">Current: {assignment.faculty_name}</p>
              <p className="text-muted-foreground">New: {target?.name ?? "—"}</p>
            </div>
            <LoadWarning warning={validResult?.warning} />
            <p className="text-xs text-muted-foreground">
              Existing timetable placements stay in their current periods. Only the
              assignment&apos;s faculty changes — the timetable is not regenerated.
            </p>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={handleBack} disabled={busy}>
                Back
              </Button>
              <Button type="button" onClick={handleConfirm} disabled={busy}>
                {apply.isSubmitting ? "Reassigning…" : "Confirm Reassignment"}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/**
 * Swap two assignments' faculties atomically via the dedicated swap API
 * (never two reassignments). Dry-run first with failures grouped by
 * swap_side, then confirm and apply. Refresh is owned by the parent.
 */
function SwapFacultyDialog({ open, onOpenChange, onApplied, assignments }) {
  const toast = useToast();
  const [aId, setAId] = useState("");
  const [bId, setBId] = useState("");
  const [phase, setPhase] = useState("select");
  const [validResult, setValidResult] = useState(null);
  const validate = useMutation(({ assignmentAId, assignmentBId }) =>
    validateFacultySwap(assignmentAId, assignmentBId)
  );
  const apply = useMutation(({ assignmentAId, assignmentBId }) =>
    swapFaculty(assignmentAId, assignmentBId)
  );
  const busy = validate.isSubmitting || apply.isSubmitting;
  const failures = getFailures(validate.error);
  const applyFailures = getFailures(apply.error);
  const assignmentA = (assignments ?? []).find((a) => String(a.id) === aId) ?? null;
  const assignmentB = (assignments ?? []).find((a) => String(a.id) === bId) ?? null;
  const bOptions = (assignments ?? []).filter((a) => String(a.id) !== aId);
  const canValidate = aId !== "" && bId !== "" && aId !== bId;

  function resetToSelect() {
    setPhase("select");
    setValidResult(null);
    validate.reset();
    apply.reset();
  }

  function handleAChange(nextId) {
    setAId(nextId);
    if (nextId === bId) setBId("");
    resetToSelect();
  }

  function handleBChange(nextId) {
    setBId(nextId);
    resetToSelect();
  }

  function failuresFor(list, side) {
    return list.filter((failure) => failure.details?.swap_side === side);
  }

  function ungrouped(list) {
    return list.filter((failure) => failure.details?.swap_side == null);
  }

  async function handleValidate(event) {
    event.preventDefault();
    const result = await validate.execute({ assignmentAId: aId, assignmentBId: bId });
    if (result.ok) {
      setValidResult(result.data);
      setPhase("confirm");
    } else if (result.error) {
      toast.error(result.error.message || "Could not validate swap.");
    }
  }

  async function handleConfirm() {
    const result = await apply.execute({ assignmentAId: aId, assignmentBId: bId });
    if (result.ok) {
      toast.success(result.data.message || "Faculties swapped.");
      for (const warning of result.data?.result?.warnings ?? []) {
        if (warning?.exceeded) {
          toast.warning(warning.message || "Weekly load exceeded.", { title: "Weekly load" });
        }
      }
      onApplied();
      // Phase 6P: both ownerships + labels + loads changed (noop emits nothing).
      emitOnSuccess(result, SWAP_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not swap faculties.");
    }
  }

  function renderFailureGroups(list) {
    const sideA = failuresFor(list, "A");
    const sideB = failuresFor(list, "B");
    const rest = ungrouped(list);
    if (list.length === 0) return null;
    return (
      <div className="grid gap-2">
        {sideA.length > 0 ? (
          <FailureList failures={sideA} title={`Assignment A — ${assignmentLabel(assignmentA)}`} />
        ) : null}
        {sideB.length > 0 ? (
          <FailureList failures={sideB} title={`Assignment B — ${assignmentLabel(assignmentB)}`} />
        ) : null}
        {rest.length > 0 ? <FailureList failures={rest} /> : null}
      </div>
    );
  }

  return (
    <Dialog open={open} onOpenChange={busy ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Swap faculty</DialogTitle>
          <DialogDescription>
            Exchange the faculties of two assignments in one atomic step.
          </DialogDescription>
        </DialogHeader>
        {phase === "select" ? (
          <form onSubmit={handleValidate} className="space-y-4">
            {failures.length > 0 ? (
              renderFailureGroups(failures)
            ) : (
              <MutationError error={validate.error} />
            )}
            <div>
              <Label htmlFor="swap-a">Assignment A</Label>
              <Select value={aId} onValueChange={handleAChange} disabled={busy}>
                <SelectTrigger id="swap-a" className="mt-1.5">
                  <SelectValue placeholder="Select first assignment" />
                </SelectTrigger>
                <SelectContent>
                  {(assignments ?? []).map((assignment) => (
                    <SelectItem key={assignment.id} value={String(assignment.id)}>
                      {assignmentLabel(assignment)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="swap-b">Assignment B</Label>
              <Select value={bId} onValueChange={handleBChange} disabled={busy || aId === ""}>
                <SelectTrigger id="swap-b" className="mt-1.5">
                  <SelectValue placeholder={aId === "" ? "Select A first" : "Select second assignment"} />
                </SelectTrigger>
                <SelectContent>
                  {bOptions.map((assignment) => (
                    <SelectItem key={assignment.id} value={String(assignment.id)}>
                      {assignmentLabel(assignment)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" disabled={busy || !canValidate}>
                {validate.isSubmitting ? "Validating…" : "Validate Swap"}
              </Button>
            </DialogFooter>
          </form>
        ) : validResult?.noop ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Both assignments already use the same faculty; nothing to change.
            </p>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Close
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4">
            {applyFailures.length > 0 ? (
              renderFailureGroups(applyFailures)
            ) : (
              <MutationError error={apply.error} />
            )}
            <div className="rounded-lg border px-4 py-3 text-sm">
              <p className="font-medium text-ink">Assignment A</p>
              <p className="text-muted-foreground">{assignmentLabel(assignmentA)}</p>
              <p className="mt-1 text-muted-foreground">
                {assignmentA?.faculty_name} → {assignmentB?.faculty_name}
              </p>
            </div>
            <div className="rounded-lg border px-4 py-3 text-sm">
              <p className="font-medium text-ink">Assignment B</p>
              <p className="text-muted-foreground">{assignmentLabel(assignmentB)}</p>
              <p className="mt-1 text-muted-foreground">
                {assignmentB?.faculty_name} → {assignmentA?.faculty_name}
              </p>
            </div>
            {(validResult?.warnings ?? []).map((warning) => (
              <LoadWarning key={warning.faculty_id} warning={warning} />
            ))}
            <p className="text-xs text-muted-foreground">
              Either both faculties change or neither does. Placements stay put — the
              timetable is not regenerated.
            </p>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setPhase("select")}
                disabled={busy}
              >
                Back
              </Button>
              <Button type="button" onClick={handleConfirm} disabled={busy}>
                {apply.isSubmitting ? "Swapping…" : "Confirm Swap"}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function AssignmentsPage() {
  const toast = useToast();
  const { data, error, isLoading, retry } = useApi(getAssignments, ["assignments"]);
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [pendingDelete, setPendingDelete] = useState(null);
  const deletion = useMutation(deleteAssignment);
  const [reassignTarget, setReassignTarget] = useState(null);
  const [reassignKey, setReassignKey] = useState(0);
  const [swapOpen, setSwapOpen] = useState(false);
  const [swapKey, setSwapKey] = useState(0);

  function openAddDialog() {
    setAddKey((key) => key + 1);
    setAddOpen(true);
  }

  function openReassignDialog(assignment) {
    setReassignKey((key) => key + 1);
    setReassignTarget(assignment);
  }

  function openSwapDialog() {
    setSwapKey((key) => key + 1);
    setSwapOpen(true);
  }

  function handleReassigned() {
    setReassignTarget(null);
    retry();
  }

  function handleSwapped() {
    setSwapOpen(false);
    retry();
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    const result = await deletion.execute(pendingDelete.id);
    if (result.ok) {
      toast.success(result.data.message || "Assignment deleted.");
      setPendingDelete(null);
      retry();
      emitOnSuccess(result, ASSIGNMENT_WRITE_DOMAINS);
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
        <div className="flex gap-2">
          <Button variant="outline" onClick={openSwapDialog}>
            <ArrowLeftRight aria-hidden="true" />
            Swap Faculty
          </Button>
          <Button onClick={openAddDialog}>
            <Plus aria-hidden="true" />
            Add Assignment
          </Button>
        </div>
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
                  <TableCell>
                    {assignment.group}
                    {assignment.specialization_id != null ? (
                      <span className="mt-1 block">
                        <Badge variant="secondary" title="Specialization classes stay synchronized across the enrollment and cannot be moved independently.">
                          Specialization
                        </Badge>
                      </span>
                    ) : null}
                  </TableCell>
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
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openReassignDialog(assignment)}
                        aria-label={`Reassign faculty for ${assignment.faculty_name} ${assignment.subject_name} ${assignment.group}`}
                      >
                        <Repeat aria-hidden="true" />
                        Reassign
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPendingDelete(assignment)}
                        aria-label={`Delete assignment ${assignment.faculty_name} ${assignment.subject_name} ${assignment.group}`}
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
      {reassignTarget ? (
        <ReassignFacultyDialog
          key={reassignKey}
          open={reassignTarget !== null}
          onOpenChange={(open) => {
            if (!open) setReassignTarget(null);
          }}
          onApplied={handleReassigned}
          assignment={reassignTarget}
          faculty={data.faculty ?? []}
        />
      ) : null}
      {swapOpen ? (
        <SwapFacultyDialog
          key={swapKey}
          open={swapOpen}
          onOpenChange={setSwapOpen}
          onApplied={handleSwapped}
          assignments={assignments}
        />
      ) : null}
    </Page>
  );
}
