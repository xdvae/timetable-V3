import { useCallback, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowLeft, BookOpen, Info, Plus, Trash2, UsersRound } from "lucide-react";

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
import { DeleteConfirmDialog, FailureList, FieldError, MutationFailure } from "@/components/feedback/mutation.jsx";
import { getFailures } from "@/lib/failures.js";
import { emitOnSuccess, MEMBERSHIP_DOMAINS, SPECIALIZATION_DOMAINS } from "@/lib/propagation.js";
import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import {
  createSpecialization,
  deleteMembership,
  deleteSpecialization,
  getSpecialization,
  getSpecializations,
  saveMembership,
} from "@/services/api/specializations.js";
import { getEnrollmentSections } from "@/services/api/enrollments.js";

function SessionTypeBadge({ sessionType }) {
  const isPractical = sessionType === "practical";
  return <Badge variant={isPractical ? "lab" : "theory"}>{isPractical ? "Practical" : "Theory"}</Badge>;
}

function SyncNotice() {
  return (
    <Alert variant="info">
      <Info aria-hidden="true" />
      <AlertTitle>How specializations behave</AlertTitle>
      <AlertDescription>
        <p>
          All specializations in one enrollment share identical synchronized slots; participating
          sections are blocked from normal teaching during those slots. Changes here apply to
          future timetable generations — the current timetable is never regenerated.
        </p>
      </AlertDescription>
    </Alert>
  );
}

/**
 * Create-specialization dialog. The enrollment/cohort is fixed by the page
 * route; only the backend-required fields are collected. Block-length and
 * capacity rules stay server-side — the form only rejects trivially
 * invalid input before submitting.
 */
function CreateSpecializationDialog({ open, onOpenChange, onCreated, enrollmentId }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation(createSpecialization);
  const [name, setName] = useState("");
  const [sessionType, setSessionType] = useState("theory");
  const [blockLength, setBlockLength] = useState("1");
  const [periodsPerWeek, setPeriodsPerWeek] = useState("2");

  const localError =
    name.trim() === ""
      ? null
      : Number.isInteger(Number(blockLength)) &&
          Number.isInteger(Number(periodsPerWeek)) &&
          Number(blockLength) >= 1 &&
          Number(periodsPerWeek) >= 1 &&
          Number(blockLength) <= Number(periodsPerWeek)
        ? null
        : "Block length must be at least 1 and cannot exceed periods/week.";

  async function handleSubmit(event) {
    event.preventDefault();
    if (name.trim() === "" || localError) return;
    const result = await execute({
      name: name.trim(),
      enrollment_id: enrollmentId,
      session_type: sessionType,
      block_length: blockLength,
      periods_per_week: periodsPerWeek,
    });
    if (result.ok) {
      toast.success(result.data.message || "Specialization added.");
      onOpenChange(false);
      onCreated();
      emitOnSuccess(result, SPECIALIZATION_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not add specialization.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add specialization</DialogTitle>
          <DialogDescription>
            A cross-section group within this enrollment. Sections join afterwards as members.
            Applies to future timetable generations only.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationFailure error={error} />
          <div>
            <Label htmlFor="spec-name">Name</Label>
            <Input
              id="spec-name"
              className="mt-1.5"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Cyber Security"
              disabled={isSubmitting}
              aria-describedby={fieldErrors.name ? "spec-name-error" : undefined}
            />
            <FieldError id="spec-name-error" message={fieldErrors.name} />
          </div>
          <div>
            <Label htmlFor="spec-type">Session type</Label>
            <Select value={sessionType} onValueChange={setSessionType} disabled={isSubmitting}>
              <SelectTrigger id="spec-type" className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="theory">Theory</SelectItem>
                <SelectItem value="practical">Practical</SelectItem>
              </SelectContent>
            </Select>
            <FieldError id="spec-type-error" message={fieldErrors.session_type} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="spec-periods">Periods/week</Label>
              <Input
                id="spec-periods"
                className="mt-1.5"
                type="number"
                min="1"
                required
                value={periodsPerWeek}
                onChange={(e) => setPeriodsPerWeek(e.target.value)}
                disabled={isSubmitting}
                aria-describedby={fieldErrors.periods_per_week ? "spec-periods-error" : undefined}
              />
              <FieldError id="spec-periods-error" message={fieldErrors.periods_per_week} />
            </div>
            <div>
              <Label htmlFor="spec-block">Block length</Label>
              <Input
                id="spec-block"
                className="mt-1.5"
                type="number"
                min="1"
                required
                value={blockLength}
                onChange={(e) => setBlockLength(e.target.value)}
                disabled={isSubmitting}
                aria-describedby={fieldErrors.block_length ? "spec-block-error" : undefined}
              />
              <FieldError id="spec-block-error" message={fieldErrors.block_length} />
            </div>
          </div>
          {localError && name.trim() !== "" ? (
            <p className="text-xs font-medium text-signal" role="alert">
              {localError}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || name.trim() === "" || localError !== null}>
              {isSubmitting ? "Adding…" : "Add Specialization"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Add-or-update membership dialog. Any section of the enrollment can be
 * picked; picking a section that already participates updates its headcount
 * (the backend upserts). Cohort, duplicate, and capacity rules are enforced
 * server-side and surfaced as structured failures.
 */
function MembershipDialog({ open, onOpenChange, onSaved, specialization, sections }) {
  const toast = useToast();
  const memberships = specialization.memberships ?? [];
  const memberIds = new Set(memberships.map((m) => String(m.section_id)));
  const [sectionId, setSectionId] = useState(
    sections[0] != null ? String(sections[0].id) : ""
  );
  const selectedSection = sections.find((s) => String(s.id) === sectionId) ?? null;
  const existing = memberships.find((m) => String(m.section_id) === sectionId) ?? null;
  const [studentCount, setStudentCount] = useState("");
  const { execute, isSubmitting, error } = useMutation(({ sectionId: sid, studentCount: count }) =>
    saveMembership(specialization.id, { sectionId: sid, studentCount: count })
  );

  function handleSectionChange(nextId) {
    setSectionId(nextId);
    setStudentCount("");
  }

  const effectiveCount =
    studentCount !== "" ? studentCount : selectedSection ? String(selectedSection.student_count) : "";

  async function handleSubmit(event) {
    event.preventDefault();
    if (!sectionId || effectiveCount === "") return;
    const result = await execute({ sectionId, studentCount: effectiveCount });
    if (result.ok) {
      toast.success(result.data.message || "Membership saved.");
      onOpenChange(false);
      onSaved();
      // Phase 6P: membership is configuration; persisted schedule output
      // changes only at the next generation, so only config domains emit.
      emitOnSuccess(result, MEMBERSHIP_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not save membership.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{existing ? "Update membership" : "Add section"}</DialogTitle>
          <DialogDescription>
            {specialization.name} · headcount per originating section. Defaults to the section&apos;s
            full size; the backend enforces cohort and capacity rules.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationFailure error={error} />
          {sections.length === 0 ? (
            <p className="text-sm font-medium text-signal" role="alert">
              No sections exist in this enrollment yet.
            </p>
          ) : (
            <div>
              <Label htmlFor="membership-section">Section</Label>
              <Select value={sectionId} onValueChange={handleSectionChange} disabled={isSubmitting}>
                <SelectTrigger id="membership-section" className="mt-1.5">
                  <SelectValue placeholder="Select a section" />
                </SelectTrigger>
                <SelectContent>
                  {sections.map((section) => (
                    <SelectItem key={section.id} value={String(section.id)}>
                      {section.name} ({section.student_count} students)
                      {memberIds.has(String(section.id)) ? " · already a member" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div>
            <Label htmlFor="membership-count">Students joining</Label>
            <Input
              id="membership-count"
              className="mt-1.5"
              type="number"
              min="1"
              required
              value={effectiveCount}
              onChange={(e) => setStudentCount(e.target.value)}
              disabled={isSubmitting}
              placeholder={selectedSection ? String(selectedSection.student_count) : ""}
            />
            {selectedSection ? (
              <p className="mt-1 text-xs text-muted-foreground">
                {selectedSection.name} has {selectedSection.student_count} students
                {existing ? ` · currently contributing ${existing.student_count}` : ""}.
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || !sectionId || effectiveCount === ""}>
              {isSubmitting ? "Saving…" : existing ? "Update Membership" : "Add Section"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function CapacityPanel({ specialization, sections }) {
  const memberships = specialization.memberships ?? [];
  const sectionById = useMemo(() => {
    const map = new Map();
    for (const section of sections) map.set(String(section.id), section);
    return map;
  }, [sections]);
  const total = specialization.total_students ?? 0;

  if (memberships.length === 0) {
    return (
      <Panel accent="steel" title="Capacity & headcount" description="How many students participate.">
        <p className="text-sm text-muted-foreground">
          No members yet — total headcount is 0. The specialization room must accommodate the total
          once sections join.
        </p>
      </Panel>
    );
  }

  return (
    <Panel
      accent="steel"
      title="Capacity & headcount"
      description={`${memberships.length} ${memberships.length === 1 ? "section participates" : "sections participate"} · ${total} students total. Room capacity is validated server-side at schedule time.`}
    >
      <Table aria-label="Membership headcounts">
        <TableHeader>
          <TableRow>
            <TableHead scope="col">Section</TableHead>
            <TableHead scope="col">Joining</TableHead>
            <TableHead scope="col">Section size</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {memberships.map((membership) => {
            const section = sectionById.get(String(membership.section_id));
            return (
              <TableRow key={membership.id ?? membership.section_id}>
                <TableCell className="font-medium text-ink">
                  {membership.section_name ?? section?.name ?? `Section ${membership.section_id}`}
                </TableCell>
                <TableCell className="tabular-nums">{membership.student_count} students</TableCell>
                <TableCell className="tabular-nums">
                  {section ? `${section.student_count} students` : "—"}
                </TableCell>
              </TableRow>
            );
          })}
          <TableRow>
            <TableCell className="font-medium text-ink">Total</TableCell>
            <TableCell className="tabular-nums font-medium text-ink" colSpan={2}>
              {total} students
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </Panel>
  );
}

function ScheduleFootprintPanel({ specialization }) {
  const slots = specialization.slots ?? [];
  const classes = specialization.scheduled_classes ?? [];

  return (
    <Panel
      accent="brass"
      title="Schedule footprint"
      description="Synchronized slots and placed classes for this specialization (read-only)."
    >
      {slots.length === 0 && classes.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Not yet scheduled. Membership changes apply to future timetable generations — nothing here
          triggers a regeneration.
        </p>
      ) : (
        <div className="space-y-4">
          {slots.length > 0 ? (
            <Table aria-label="Synchronized slots">
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Day</TableHead>
                  <TableHead scope="col">Start period</TableHead>
                  <TableHead scope="col">Length</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {slots.map((slot) => (
                  <TableRow key={slot.id}>
                    <TableCell className="font-medium text-ink">{slot.day}</TableCell>
                    <TableCell className="tabular-nums">{slot.start_period}</TableCell>
                    <TableCell className="tabular-nums">{slot.length}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : null}
          {classes.length > 0 ? (
            <Table aria-label="Scheduled specialization classes">
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Subject</TableHead>
                  <TableHead scope="col">Faculty</TableHead>
                  <TableHead scope="col">Room</TableHead>
                  <TableHead scope="col">Day</TableHead>
                  <TableHead scope="col">Period</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {classes.map((cls) => (
                  <TableRow key={cls.id}>
                    <TableCell className="font-medium text-ink">{cls.subject ?? "—"}</TableCell>
                    <TableCell>{cls.faculty ?? "—"}</TableCell>
                    <TableCell>{cls.room ?? "—"}</TableCell>
                    <TableCell>{cls.day}</TableCell>
                    <TableCell className="tabular-nums">{cls.start_period}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Specialization classes cannot be moved independently — they stay synchronized across the
            enrollment. Use the timetable&apos;s manual editing only for normal classes.
          </p>
        </div>
      )}
    </Panel>
  );
}

/**
 * Enrollment-scoped specialization list: Enrollment → Sections →
 * Specializations. Create/delete live here; managing memberships lives on
 * the detail route. Never touches POST /api/schedule/run.
 */
export function SpecializationsPage() {
  const { eid } = useParams();
  const toast = useToast();
  const specsQuery = useApi(getSpecializations, ["specializations"]);
  const sectionsFetcher = useCallback(() => getEnrollmentSections(eid), [eid]);
  const sectionsQuery = useApi(sectionsFetcher, ["sections"]);
  const [createOpen, setCreateOpen] = useState(false);
  const [createKey, setCreateKey] = useState(0);
  const [pendingDelete, setPendingDelete] = useState(null);
  const deletion = useMutation(deleteSpecialization);

  function refetchAll() {
    specsQuery.retry();
    sectionsQuery.retry();
  }

  function openCreateDialog() {
    setCreateKey((key) => key + 1);
    setCreateOpen(true);
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    const result = await deletion.execute(pendingDelete.id);
    if (result.ok) {
      toast.success(result.data.message || "Specialization deleted.");
      setPendingDelete(null);
      refetchAll();
      emitOnSuccess(result, SPECIALIZATION_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not delete specialization.");
    }
  }

  const loading = (specsQuery.isLoading && !specsQuery.data) || (sectionsQuery.isLoading && !sectionsQuery.data);
  const loadError = !specsQuery.data ? specsQuery.error : !sectionsQuery.data ? sectionsQuery.error : null;

  if (loading) {
    return (
      <Page
        title="Specializations"
        subtitle="Cross-section groups within one enrollment."
        breadcrumbs={[
          { label: "Enrollments", to: "/enrollments" },
          { label: "Sections", to: `/enrollments/${eid}/sections` },
          { label: "Specializations" },
        ]}
      >
        <PageLoading rows={5} label="Loading specializations…" />
      </Page>
    );
  }

  if (loadError) {
    return (
      <Page
        title="Specializations"
        subtitle="Cross-section groups within one enrollment."
        breadcrumbs={[
          { label: "Enrollments", to: "/enrollments" },
          { label: "Sections", to: `/enrollments/${eid}/sections` },
          { label: "Specializations" },
        ]}
      >
        <QueryError error={loadError} onRetry={refetchAll} />
      </Page>
    );
  }

  const enrollment = sectionsQuery.data.enrollment ?? {};
  const allSpecs = specsQuery.data.specializations ?? [];
  const specs = allSpecs.filter((spec) => String(spec.enrollment_id) === String(eid));
  const contextLabel = `${enrollment.program_name ?? "?"} · ${enrollment.year_label ?? "?"}`;
  const deleteFailures = getFailures(deletion.error);

  return (
    <Page
      title={`Specializations — ${contextLabel}`}
      subtitle={
        specs.length === 0
          ? "Cross-section groups within one enrollment."
          : `${specs.length} ${specs.length === 1 ? "specialization" : "specializations"} · synchronized across this enrollment`
      }
      breadcrumbs={[
        { label: "Enrollments", to: "/enrollments" },
        { label: contextLabel, to: `/enrollments/${eid}/sections` },
        { label: "Specializations" },
      ]}
      actions={
        <div className="flex gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to={`/enrollments/${eid}/sections`}>
              <ArrowLeft aria-hidden="true" />
              Back to Sections
            </Link>
          </Button>
          <Button onClick={openCreateDialog}>
            <Plus aria-hidden="true" />
            Add Specialization
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        <SyncNotice />
        {specs.length === 0 ? (
          <EmptyState
            icon={BookOpen}
            title="No specializations yet"
            description="A specialization is a cross-section group (e.g. Cyber Security) whose classes run in synchronized slots for every participating section. Add your first one to get started — sections join afterwards as members."
            action={
              <Button onClick={openCreateDialog} className="mt-2">
                <Plus aria-hidden="true" />
                Add Specialization
              </Button>
            }
          />
        ) : (
          <Panel accent="steel" title="All specializations in this enrollment">
            <Table aria-label="Specializations">
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Name</TableHead>
                  <TableHead scope="col">Type</TableHead>
                  <TableHead scope="col">Sections</TableHead>
                  <TableHead scope="col">Students</TableHead>
                  <TableHead scope="col">Schedule</TableHead>
                  <TableHead scope="col">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {specs.map((spec) => {
                  const memberCount = spec.memberships?.length ?? 0;
                  const scheduled = (spec.slots?.length ?? 0) > 0 || (spec.scheduled_classes?.length ?? 0) > 0;
                  return (
                    <TableRow key={spec.id}>
                      <TableCell className="font-medium text-ink">{spec.name}</TableCell>
                      <TableCell>
                        <SessionTypeBadge sessionType={spec.session_type} />
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {memberCount} {memberCount === 1 ? "section" : "sections"}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {spec.total_students ?? 0} students
                      </TableCell>
                      <TableCell>
                        <Badge variant={scheduled ? "secondary" : "outline"}>
                          {scheduled ? "Scheduled" : "Unscheduled"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button asChild variant="outline" size="sm">
                            <Link
                              to={`/enrollments/${eid}/specializations/${spec.id}`}
                              aria-label={`Manage specialization ${spec.name}`}
                            >
                              <UsersRound aria-hidden="true" />
                              Manage
                            </Link>
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setPendingDelete(spec)}
                            aria-label={`Delete specialization ${spec.name}`}
                          >
                            <Trash2 aria-hidden="true" className="text-signal" />
                            Delete
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Panel>
        )}
      </div>

      <CreateSpecializationDialog
        key={createKey}
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={refetchAll}
        enrollmentId={eid}
      />
      <DeleteConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
            deletion.reset();
          }
        }}
        title={pendingDelete ? `Delete specialization ${pendingDelete.name}?` : "Delete specialization?"}
        description="This also removes its section memberships, synchronized slots, scheduled classes, and specialization assignments. Normal teaching is untouched. This cannot be undone."
        confirmLabel="Delete"
        onConfirm={handleDelete}
        isConfirming={deletion.isSubmitting}
        error={deletion.error && deleteFailures.length === 0 ? deletion.error : null}
      />
      {deleteFailures.length > 0 && pendingDelete !== null ? (
        <div className="mt-4">
          <FailureList failures={deleteFailures} />
        </div>
      ) : null}
    </Page>
  );
}

/**
 * Manage one specialization: identity, memberships (add/update/remove),
 * capacity/headcount, and the read-only schedule footprint. Every mutation
 * refetches the authoritative GET payload before rendering. Never calls
 * POST /api/schedule/run.
 */
export function SpecializationDetailPage() {
  const { eid, sid } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const specFetcher = useCallback(() => getSpecialization(sid), [sid]);
  const specQuery = useApi(specFetcher, ["specializations"]);
  const sectionsFetcher = useCallback(() => getEnrollmentSections(eid), [eid]);
  const sectionsQuery = useApi(sectionsFetcher, ["sections"]);
  const [membershipOpen, setMembershipOpen] = useState(false);
  const [membershipKey, setMembershipKey] = useState(0);
  const [pendingRemove, setPendingRemove] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(false);
  const removal = useMutation(({ sectionId }) => deleteMembership(sid, sectionId));
  const deletion = useMutation(deleteSpecialization);

  function refetchAll() {
    specQuery.retry();
    sectionsQuery.retry();
  }

  function openMembershipDialog() {
    setMembershipKey((key) => key + 1);
    setMembershipOpen(true);
  }

  async function handleRemove() {
    if (!pendingRemove) return;
    const result = await removal.execute({ sectionId: pendingRemove.section_id });
    if (result.ok) {
      toast.success(result.data.message || "Membership removed.");
      setPendingRemove(null);
      refetchAll();
      emitOnSuccess(result, MEMBERSHIP_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not remove membership.");
    }
  }

  async function handleDelete() {
    const result = await deletion.execute(sid);
    if (result.ok) {
      toast.success(result.data.message || "Specialization deleted.");
      setPendingDelete(false);
      // Phase 6P: the list page remounts fresh on navigation; still emit so
      // any other mounted specialization consumer refreshes too.
      emitOnSuccess(result, SPECIALIZATION_DOMAINS);
      navigate(`/enrollments/${eid}/specializations`);
    } else if (result.error) {
      toast.error(result.error.message || "Could not delete specialization.");
    }
  }

  const loading = (specQuery.isLoading && !specQuery.data) || (sectionsQuery.isLoading && !sectionsQuery.data);
  const loadError = !specQuery.data ? specQuery.error : !sectionsQuery.data ? sectionsQuery.error : null;

  if (loading) {
    return (
      <Page
        title="Specialization"
        subtitle="Memberships, capacity, and schedule footprint."
        breadcrumbs={[
          { label: "Enrollments", to: "/enrollments" },
          { label: "Sections", to: `/enrollments/${eid}/sections` },
          { label: "Specializations", to: `/enrollments/${eid}/specializations` },
          { label: "Manage" },
        ]}
      >
        <PageLoading rows={6} label="Loading specialization…" />
      </Page>
    );
  }

  if (loadError) {
    return (
      <Page
        title="Specialization"
        subtitle="Memberships, capacity, and schedule footprint."
        breadcrumbs={[
          { label: "Enrollments", to: "/enrollments" },
          { label: "Sections", to: `/enrollments/${eid}/sections` },
          { label: "Specializations", to: `/enrollments/${eid}/specializations` },
          { label: "Manage" },
        ]}
      >
        <QueryError error={loadError} onRetry={refetchAll} />
      </Page>
    );
  }

  const spec = specQuery.data.specialization;
  const enrollment = sectionsQuery.data.enrollment ?? {};
  const sections = sectionsQuery.data.sections ?? [];
  const memberships = spec.memberships ?? [];
  const contextLabel = `${enrollment.program_name ?? "?"} · ${enrollment.year_label ?? "?"}`;
  const removeFailures = getFailures(removal.error);
  const deleteFailures = getFailures(deletion.error);
  const cohortMismatch = String(spec.enrollment_id) !== String(eid);

  return (
    <Page
      title={`Specialization — ${spec.name}`}
      subtitle={`${contextLabel} · ${spec.periods_per_week} periods/week · ${spec.block_length}-period blocks`}
      breadcrumbs={[
        { label: "Enrollments", to: "/enrollments" },
        { label: contextLabel, to: `/enrollments/${eid}/sections` },
        { label: "Specializations", to: `/enrollments/${eid}/specializations` },
        { label: spec.name },
      ]}
      actions={
        <div className="flex gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to={`/enrollments/${eid}/specializations`}>
              <ArrowLeft aria-hidden="true" />
              Back to Specializations
            </Link>
          </Button>
          <Button variant="destructive" size="sm" onClick={() => setPendingDelete(true)}>
            <Trash2 aria-hidden="true" />
            Delete
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        {cohortMismatch ? (
          <Alert variant="destructive">
            <AlertTitle>Wrong enrollment</AlertTitle>
            <AlertDescription>
              <p>
                This specialization belongs to enrollment {spec.enrollment_id}, not the enrollment in
                the URL. Membership changes are still validated server-side.
              </p>
            </AlertDescription>
          </Alert>
        ) : null}
        <SyncNotice />

        <Panel
          accent="brass"
          title="Identity"
          description="Configuration for this specialization. Applies to future timetable generations."
        >
          <dl className="grid gap-3 sm:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Name</dt>
              <dd className="mt-0.5 text-sm font-medium text-ink">{spec.name}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Session type</dt>
              <dd className="mt-0.5">
                <SessionTypeBadge sessionType={spec.session_type} />
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Periods / week</dt>
              <dd className="mt-0.5 text-sm font-medium text-ink tabular-nums">{spec.periods_per_week}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Block length</dt>
              <dd className="mt-0.5 text-sm font-medium text-ink tabular-nums">
                {spec.block_length} {spec.block_length === 1 ? "period" : "periods"}
              </dd>
            </div>
          </dl>
        </Panel>

        <Panel
          accent="steel"
          title="Participating sections"
          description={
            memberships.length === 0
              ? "No sections participate yet. Add sections below — the backend validates cohort and capacity."
              : `${memberships.length} ${memberships.length === 1 ? "section participates" : "sections participate"} · ${spec.total_students ?? 0} students total.`
          }
          actions={
            <Button size="sm" onClick={openMembershipDialog} disabled={sections.length === 0}>
              <Plus aria-hidden="true" />
              Add Section
            </Button>
          }
        >
          {memberships.length === 0 ? (
            <EmptyState
              icon={UsersRound}
              title="No participating sections"
              description="Add sections from this enrollment. Each membership records how many of the section's students join — the backend enforces cohort match and per-section capacity."
              action={
                <Button size="sm" onClick={openMembershipDialog} disabled={sections.length === 0} className="mt-2">
                  <Plus aria-hidden="true" />
                  Add Section
                </Button>
              }
            />
          ) : (
            <Table aria-label="Participating sections">
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Section</TableHead>
                  <TableHead scope="col">Students joining</TableHead>
                  <TableHead scope="col">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {memberships.map((membership) => (
                  <TableRow key={membership.id ?? membership.section_id}>
                    <TableCell className="font-medium text-ink">
                      {membership.section_name ?? `Section ${membership.section_id}`}
                    </TableCell>
                    <TableCell className="tabular-nums">{membership.student_count} students</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button variant="outline" size="sm" onClick={openMembershipDialog}>
                          Edit
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setPendingRemove(membership)}
                          aria-label={`Remove ${membership.section_name ?? membership.section_id} from ${spec.name}`}
                        >
                          <Trash2 aria-hidden="true" className="text-signal" />
                          Remove
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Panel>

        <CapacityPanel specialization={spec} sections={sections} />
        <ScheduleFootprintPanel specialization={spec} />

        <Panel
          accent="steel"
          title="Teaching assignments"
          description="Classes for this specialization are taught through specialization assignments."
        >
          <p className="text-sm text-muted-foreground">
            Assignments with this specialization teach the whole group at once and cannot be moved
            independently — they stay synchronized across the enrollment. Create and manage them on
            the{" "}
            <Link to="/assignments" className="text-steel underline-offset-4 hover:underline">
              Teaching Assignments
            </Link>{" "}
            page, where specialization classes are labelled with this specialization&apos;s name.
          </p>
        </Panel>
      </div>

      <MembershipDialog
        key={membershipKey}
        open={membershipOpen}
        onOpenChange={setMembershipOpen}
        onSaved={refetchAll}
        specialization={spec}
        sections={sections}
      />
      <DeleteConfirmDialog
        open={pendingRemove !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingRemove(null);
            removal.reset();
          }
        }}
        title={
          pendingRemove
            ? `Remove ${pendingRemove.section_name ?? "section"} from ${spec.name}?`
            : "Remove membership?"
        }
        description="The section keeps its normal teaching. This only withdraws its students from the specialization and applies to future timetable generations."
        confirmLabel="Remove"
        onConfirm={handleRemove}
        isConfirming={removal.isSubmitting}
        error={removal.error && removeFailures.length === 0 ? removal.error : null}
      />
      {removeFailures.length > 0 && pendingRemove !== null ? (
        <div className="mt-4">
          <FailureList failures={removeFailures} />
        </div>
      ) : null}
      <DeleteConfirmDialog
        open={pendingDelete}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(false);
            deletion.reset();
          }
        }}
        title={`Delete specialization ${spec.name}?`}
        description="This also removes its section memberships, synchronized slots, scheduled classes, and specialization assignments. Normal teaching is untouched. This cannot be undone."
        confirmLabel="Delete"
        onConfirm={handleDelete}
        isConfirming={deletion.isSubmitting}
        error={deletion.error && deleteFailures.length === 0 ? deletion.error : null}
      />
      {deleteFailures.length > 0 && pendingDelete ? (
        <div className="mt-4">
          <FailureList failures={deleteFailures} />
        </div>
      ) : null}
    </Page>
  );
}
