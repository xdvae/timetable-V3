import { useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, FlaskConical, TriangleAlert, Users } from "lucide-react";

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
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select.jsx";
import { FailureList, FieldError, MutationError } from "@/components/feedback/mutation.jsx";
import { getFailures } from "@/lib/failures.js";
import { ASSIGNMENT_WRITE_DOMAINS, emitOnSuccess } from "@/lib/propagation.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import { cn } from "@/lib/utils";
import { createAssignmentsBulk } from "@/services/api/assignments.js";

const naturalCompare = (a, b) =>
  String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });

/** Theory vs lab for a subject: whichever it has default hours for. */
function preferredType(defaults, current) {
  const theory = Number(defaults?.theory) > 0;
  const practical = Number(defaults?.practical) > 0;
  if (practical && !theory) return "practical";
  if (theory && !practical) return "theory";
  return current;
}

function hoursFor(defaults, type) {
  if (type === "practical") {
    return {
      periods: defaults?.practical ? String(defaults.practical) : null,
      block: String(defaults?.block || 2),
    };
  }
  return { periods: defaults?.theory ? String(defaults.theory) : null, block: "1" };
}

function classLabel(subject) {
  return `${subject.program_name} ${subject.year_label}`.trim();
}

/** Native checkbox that can also show the "some selected" state. */
function TriStateCheckbox({ checked, indeterminate, className, ...props }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = Boolean(indeterminate) && !checked;
  }, [indeterminate, checked]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      className={cn("size-4 shrink-0 cursor-pointer accent-brass disabled:cursor-not-allowed", className)}
      {...props}
    />
  );
}

/** One selectable section / lab-group tile. */
function TargetTile({ target, checked, takenBy, disabled, onToggle }) {
  const locked = Boolean(takenBy);
  return (
    <label
      className={cn(
        "group relative flex min-h-[3.75rem] cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors",
        checked && !locked
          ? "border-brass bg-brass/10 shadow-[inset_0_0_0_1px_var(--brass)]"
          : "border-border bg-background hover:border-brass/50 hover:bg-brass/5",
        (locked || disabled) && "cursor-not-allowed opacity-60 hover:border-border hover:bg-background"
      )}
      title={locked ? `Already taught by ${takenBy}` : undefined}
    >
      <TriStateCheckbox
        className="mt-0.5"
        checked={checked && !locked}
        disabled={locked || disabled}
        onChange={() => onToggle(target.id)}
        aria-label={`${target.name}${locked ? `, already taught by ${takenBy}` : ""}`}
      />
      <span className="min-w-0">
        <span className="block truncate text-sm font-semibold text-ink">{target.name}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {locked ? (
            <>Taught by {takenBy}</>
          ) : (
            <>
              {target.student_count} {target.student_count === 1 ? "student" : "students"}
            </>
          )}
        </span>
      </span>
    </label>
  );
}

/**
 * Assign one teacher + one subject to many sections (theory) or lab groups
 * (practical) in a single step. Sections are limited to the subject's own
 * class/year; ones that already have this subject are shown but locked
 * (with the current teacher) so nothing gets double-booked. The backend
 * validates everything again and creates all rows atomically.
 */
export function BulkAssignDialog({ open, onOpenChange, onCreated, options }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation(createAssignmentsBulk);
  const { faculty, subjects, sections, labGroups, subjectDefaults, assignments } = options;

  const sortedSubjects = useMemo(
    () =>
      [...subjects].sort(
        (a, b) => naturalCompare(classLabel(a), classLabel(b)) || naturalCompare(a.name, b.name)
      ),
    [subjects]
  );
  const subjectGroups = useMemo(() => {
    const groups = [];
    for (const subject of sortedSubjects) {
      const label = classLabel(subject);
      const last = groups[groups.length - 1];
      if (last && last.label === label) last.items.push(subject);
      else groups.push({ label, items: [subject] });
    }
    return groups;
  }, [sortedSubjects]);

  const [facultyId, setFacultyId] = useState(faculty[0]?.id != null ? String(faculty[0].id) : "");
  const [subjectId, setSubjectId] = useState(
    sortedSubjects[0]?.id != null ? String(sortedSubjects[0].id) : ""
  );
  const initialDefaults = subjectDefaults[sortedSubjects[0]?.id];
  const initialType = preferredType(initialDefaults, "theory");
  const [sessionType, setSessionType] = useState(initialType);
  const [periodsPerWeek, setPeriodsPerWeek] = useState(
    () => hoursFor(initialDefaults, initialType).periods ?? (initialType === "practical" ? "2" : "3")
  );
  const [blockLength, setBlockLength] = useState(() => hoursFor(initialDefaults, initialType).block);
  const [selected, setSelected] = useState(() => new Set());

  const subject = sortedSubjects.find((s) => String(s.id) === subjectId) ?? null;
  const teacher = faculty.find((f) => String(f.id) === facultyId) ?? null;

  // Sections of the subject's class/year, and their lab groups.
  const classSections = useMemo(() => {
    if (!subject) return [];
    return sections
      .filter((s) => s.enrollment_id === subject.enrollment_id)
      .sort((a, b) => naturalCompare(a.name, b.name));
  }, [sections, subject]);
  const groupsBySection = useMemo(() => {
    const map = new Map();
    for (const section of classSections) map.set(section.id, []);
    for (const group of labGroups) {
      if (map.has(group.section_id)) map.get(group.section_id).push(group);
    }
    for (const list of map.values()) list.sort((a, b) => naturalCompare(a.name, b.name));
    return map;
  }, [classSections, labGroups]);

  // Who already teaches this subject (same type) to each section / lab group.
  const takenBy = useMemo(() => {
    const map = new Map();
    if (!subject) return map;
    for (const a of assignments) {
      if (a.subject_id !== subject.id || a.session_type !== sessionType) continue;
      const key = sessionType === "theory" ? a.section_id : a.lab_group_id;
      if (key != null) map.set(key, a.faculty_name);
    }
    return map;
  }, [assignments, subject, sessionType]);

  const targets = useMemo(() => {
    if (sessionType === "theory") return classSections;
    return classSections.flatMap((section) => groupsBySection.get(section.id) ?? []);
  }, [sessionType, classSections, groupsBySection]);
  const available = targets.filter((t) => !takenBy.has(t.id));
  const chosen = available.filter((t) => selected.has(t.id));

  function applyDefaults(nextSubjectId, nextType) {
    const { periods, block } = hoursFor(subjectDefaults[nextSubjectId], nextType);
    if (periods) setPeriodsPerWeek(periods);
    setBlockLength(block);
  }

  function handleSubjectChange(nextId) {
    const nextType = preferredType(subjectDefaults[nextId], sessionType);
    setSubjectId(nextId);
    setSessionType(nextType);
    setSelected(new Set());
    applyDefaults(nextId, nextType);
  }

  function handleTypeChange(nextType) {
    if (nextType === sessionType) return;
    setSessionType(nextType);
    setSelected(new Set());
    applyDefaults(subjectId, nextType);
  }

  function toggle(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function setMany(ids, on) {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }

  const allIds = available.map((t) => t.id);
  const allChecked = allIds.length > 0 && allIds.every((id) => selected.has(id));
  const someChecked = allIds.some((id) => selected.has(id));

  const hours = Number(periodsPerWeek) || 0;
  const currentLoad = Number(teacher?.weekly_load) || 0;
  const newLoad = currentLoad + hours * chosen.length;
  const maxLoad = Number(teacher?.weekly_max_hours) > 0 ? Number(teacher.weekly_max_hours) : null;
  const overLimit = maxLoad !== null && chosen.length > 0 && newLoad > maxLoad;

  const missing = [];
  if (faculty.length === 0) missing.push("faculty");
  if (subjects.length === 0) missing.push("subjects");

  const noun = sessionType === "theory" ? "section" : "lab group";
  const failures = getFailures(error);

  async function handleSubmit(event) {
    event.preventDefault();
    if (chosen.length === 0) return;
    const ids = chosen.map((t) => t.id);
    const result = await execute({
      faculty_id: facultyId,
      subject_id: subjectId,
      session_type: sessionType,
      periods_per_week: periodsPerWeek,
      block_length: blockLength,
      section_ids: sessionType === "theory" ? ids : [],
      lab_group_ids: sessionType === "practical" ? ids : [],
    });
    if (result.ok) {
      const message = result.data.message || "Teaching assignments added.";
      if (result.data.category === "warning") toast.warning(message, { title: "Assignments added" });
      else toast.success(message, { title: "Assignments added" });
      onOpenChange(false);
      onCreated();
      emitOnSuccess(result, ASSIGNMENT_WRITE_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not add the assignments.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent className="flex max-h-[92svh] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="shrink-0 border-b px-6 pt-6 pb-4 pr-12">
          <DialogTitle>Add assignment</DialogTitle>
          <DialogDescription>
            Pick a teacher and a subject, then tick every section they teach. One click creates
            them all.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-col">
          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-5">
            {failures.length > 0 ? <FailureList failures={failures} /> : <MutationError error={error} />}
            {missing.length > 0 ? (
              <p className="text-sm font-medium text-signal" role="alert">
                Add {missing.join(" and ")} first before creating an assignment.
              </p>
            ) : null}

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label htmlFor="assignment-faculty">Teacher</Label>
                <Select value={facultyId} onValueChange={setFacultyId} disabled={isSubmitting}>
                  <SelectTrigger id="assignment-faculty" className="mt-1.5 w-full">
                    <SelectValue placeholder="Select a teacher" />
                  </SelectTrigger>
                  <SelectContent className="max-h-80">
                    {faculty.map((member) => (
                      <SelectItem key={member.id} value={String(member.id)}>
                        {member.name}
                        <span className="text-muted-foreground"> · {member.weekly_load ?? 0} hrs/week</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FieldError id="assignment-faculty-error" message={fieldErrors.faculty_id} />
              </div>
              <div>
                <Label htmlFor="assignment-subject">Subject</Label>
                <Select value={subjectId} onValueChange={handleSubjectChange} disabled={isSubmitting}>
                  <SelectTrigger id="assignment-subject" className="mt-1.5 w-full">
                    <SelectValue placeholder="Select a subject" />
                  </SelectTrigger>
                  <SelectContent className="max-h-80">
                    {subjectGroups.map((group) => (
                      <SelectGroup key={group.label}>
                        <SelectLabel>{group.label}</SelectLabel>
                        {group.items.map((item) => (
                          <SelectItem key={item.id} value={String(item.id)}>
                            {item.name}
                            {item.code ? <span className="text-muted-foreground"> · {item.code}</span> : null}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    ))}
                  </SelectContent>
                </Select>
                <FieldError id="assignment-subject-error" message={fieldErrors.subject_id} />
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)]">
              <div>
                <span className="text-sm font-medium" id="assignment-type-label">
                  Session type
                </span>
                <div
                  role="radiogroup"
                  aria-labelledby="assignment-type-label"
                  className="mt-1.5 grid grid-cols-2 gap-1 rounded-lg border bg-muted/40 p-1"
                >
                  {[
                    { value: "theory", label: "Theory", Icon: BookOpen },
                    { value: "practical", label: "Lab", Icon: FlaskConical },
                  ].map(({ value, label, Icon }) => (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={sessionType === value}
                      disabled={isSubmitting}
                      onClick={() => handleTypeChange(value)}
                      className={cn(
                        "flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                        sessionType === value
                          ? "bg-background text-ink shadow-sm"
                          : "text-muted-foreground hover:text-ink"
                      )}
                    >
                      <Icon aria-hidden="true" className="size-4" />
                      {label}
                    </button>
                  ))}
                </div>
                <FieldError id="assignment-type-error" message={fieldErrors.session_type} />
              </div>
              <div>
                <Label htmlFor="assignment-periods">Hours/week (each)</Label>
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
                <Label htmlFor="assignment-block">Hours per class</Label>
                <Input
                  id="assignment-block"
                  className="mt-1.5"
                  type="number"
                  min="1"
                  required
                  value={blockLength}
                  onChange={(e) => setBlockLength(e.target.value)}
                  disabled={isSubmitting}
                  aria-describedby={fieldErrors.block_length ? "assignment-block-error" : "assignment-block-hint"}
                />
                <FieldError id="assignment-block-error" message={fieldErrors.block_length} />
              </div>
            </div>
            <p id="assignment-block-hint" className="-mt-3 text-xs text-muted-foreground">
              Hours per class: 1 = one-hour theory class. Labs default to a 2-hour block — set 1 to split
              a lab into separate 1-hour sessions.
            </p>

            <div
              role="group"
              aria-labelledby="assignment-targets-label"
              className="rounded-xl border bg-muted/20 p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span id="assignment-targets-label" className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <Users aria-hidden="true" className="size-4 text-brass" />
                  {subject ? `Assign to ${classLabel(subject)} ${noun}s` : `Assign to ${noun}s`}
                </span>
                {available.length > 0 ? (
                  <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
                    <TriStateCheckbox
                      checked={allChecked}
                      indeterminate={someChecked}
                      disabled={isSubmitting}
                      onChange={() => setMany(allIds, !allChecked)}
                    />
                    Select all ({available.length})
                  </label>
                ) : null}
              </div>

              {!subject ? (
                <p className="mt-3 text-sm text-muted-foreground">Pick a subject to see its sections.</p>
              ) : classSections.length === 0 ? (
                <p className="mt-3 text-sm text-muted-foreground">
                  {classLabel(subject)} has no sections yet. Add the class on the Enrollments page first.
                </p>
              ) : sessionType === "theory" ? (
                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                  {classSections.map((section) => (
                    <TargetTile
                      key={section.id}
                      target={section}
                      checked={selected.has(section.id)}
                      takenBy={takenBy.get(section.id)}
                      disabled={isSubmitting}
                      onToggle={toggle}
                    />
                  ))}
                </div>
              ) : (
                <div className="mt-3 space-y-3">
                  {classSections.map((section) => {
                    const groups = groupsBySection.get(section.id) ?? [];
                    const free = groups.filter((g) => !takenBy.has(g.id)).map((g) => g.id);
                    const every = free.length > 0 && free.every((id) => selected.has(id));
                    const some = free.some((id) => selected.has(id));
                    return (
                      <div key={section.id}>
                        <label className="flex w-fit cursor-pointer items-center gap-2 text-xs font-semibold tracking-wide text-ink-soft uppercase">
                          <TriStateCheckbox
                            checked={every}
                            indeterminate={some}
                            disabled={isSubmitting || free.length === 0}
                            onChange={() => setMany(free, !every)}
                            aria-label={`All lab groups of ${section.name}`}
                          />
                          {section.name}
                        </label>
                        {groups.length === 0 ? (
                          <p className="mt-1 text-xs text-muted-foreground">No lab groups in this section.</p>
                        ) : (
                          <div className="mt-1.5 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                            {groups.map((group) => (
                              <TargetTile
                                key={group.id}
                                target={group}
                                checked={selected.has(group.id)}
                                takenBy={takenBy.get(group.id)}
                                disabled={isSubmitting}
                                onToggle={toggle}
                              />
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              {subject && targets.length > 0 && available.length === 0 ? (
                <p className="mt-3 text-sm text-muted-foreground">
                  Every {classLabel(subject)} {noun} already has this subject. Use Reassign in the
                  table to change a teacher.
                </p>
              ) : null}
              <FieldError
                id="assignment-targets-error"
                message={fieldErrors.section_ids || fieldErrors.lab_group_ids}
              />
            </div>
          </div>

          <DialogFooter className="shrink-0 items-center gap-3 border-t bg-muted/30 px-6 py-4 sm:justify-between">
            <div className="text-sm" aria-live="polite">
              {chosen.length === 0 ? (
                <span className="text-muted-foreground">Tick at least one {noun}.</span>
              ) : (
                <span className={cn("tabular-nums", overLimit ? "text-signal" : "text-ink-soft")}>
                  {overLimit ? <TriangleAlert aria-hidden="true" className="mr-1 inline size-4 align-[-3px]" /> : null}
                  {teacher?.name ?? "Teacher"}: {currentLoad} → <strong>{newLoad} hrs/week</strong>
                  {overLimit ? ` (limit ${maxLoad})` : ""}
                </span>
              )}
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting || missing.length > 0 || chosen.length === 0}>
                {isSubmitting
                  ? "Assigning…"
                  : chosen.length > 1
                    ? `Assign to ${chosen.length} ${noun}s`
                    : "Add Assignment"}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
