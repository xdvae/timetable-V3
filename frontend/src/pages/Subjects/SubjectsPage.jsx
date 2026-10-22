import { useState } from "react";
import { BookOpen, Plus, Trash2 } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
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
import { DeleteConfirmDialog, FieldError, MutationFailure } from "@/components/feedback/mutation.jsx";
import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import { emitOnSuccess, SUBJECTS_DOMAINS } from "@/lib/propagation.js";
import { createSubject, deleteSubject, getSubjects } from "@/services/api/subjects.js";

function Hours({ value, unit }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">—</span>;
  }
  return <span className="tabular-nums">{`${value} ${unit}`}</span>;
}

function AddSubjectDialog({ open, onOpenChange, onCreated, enrollments }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation(createSubject);
  const [enrollmentId, setEnrollmentId] = useState(
    enrollments[0]?.id != null ? String(enrollments[0].id) : ""
  );
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [theoryHours, setTheoryHours] = useState("");
  const [practicalHours, setPracticalHours] = useState("");
  const [blockLength, setBlockLength] = useState("2");
  const [credits, setCredits] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute({
      enrollment_id: enrollmentId,
      code,
      name,
      theory_hours_per_week: theoryHours,
      practical_hours_per_week: practicalHours,
      practical_block_length: blockLength,
      credits,
    });
    if (result.ok) {
      toast.success(result.data.message || "Subject added.");
      onOpenChange(false);
      onCreated();
      emitOnSuccess(result, SUBJECTS_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not add subject.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add subject</DialogTitle>
          <DialogDescription>Subject catalog entry with default weekly hours.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationFailure error={error} />
          <div>
            <Label htmlFor="subject-enrollment">Enrollment (program + year)</Label>
            <Select value={enrollmentId} onValueChange={setEnrollmentId} disabled={isSubmitting}>
              <SelectTrigger id="subject-enrollment" className="mt-1.5">
                <SelectValue placeholder="Select an enrollment" />
              </SelectTrigger>
              <SelectContent>
                {enrollments.map((enrollment) => (
                  <SelectItem key={enrollment.id} value={String(enrollment.id)}>
                    {enrollment.program_name} — {enrollment.year_label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldError id="subject-enrollment-error" message={fieldErrors.enrollment_id} />
          </div>
          <div>
            <Label htmlFor="subject-code">Code</Label>
            <Input
              id="subject-code"
              className="mt-1.5"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="e.g. CS201"
              disabled={isSubmitting}
              aria-describedby={fieldErrors.code ? "subject-code-error" : undefined}
            />
            <FieldError id="subject-code-error" message={fieldErrors.code} />
          </div>
          <div>
            <Label htmlFor="subject-name">Name</Label>
            <Input
              id="subject-name"
              className="mt-1.5"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Data Structures"
              disabled={isSubmitting}
              aria-describedby={fieldErrors.name ? "subject-name-error" : undefined}
            />
            <FieldError id="subject-name-error" message={fieldErrors.name} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="subject-theory">Theory hrs/week</Label>
              <Input
                id="subject-theory"
                className="mt-1.5"
                type="number"
                min="0"
                value={theoryHours}
                onChange={(e) => setTheoryHours(e.target.value)}
                placeholder="e.g. 3"
                disabled={isSubmitting}
                aria-describedby={fieldErrors.theory_hours_per_week ? "subject-theory-error" : undefined}
              />
              <FieldError id="subject-theory-error" message={fieldErrors.theory_hours_per_week} />
            </div>
            <div>
              <Label htmlFor="subject-practical">Practical hrs/week</Label>
              <Input
                id="subject-practical"
                className="mt-1.5"
                type="number"
                min="0"
                value={practicalHours}
                onChange={(e) => setPracticalHours(e.target.value)}
                placeholder="e.g. 4"
                disabled={isSubmitting}
                aria-describedby={fieldErrors.practical_hours_per_week ? "subject-practical-error" : undefined}
              />
              <FieldError id="subject-practical-error" message={fieldErrors.practical_hours_per_week} />
            </div>
          </div>
          <div>
            <Label htmlFor="subject-block">Lab block length (hrs per session)</Label>
            <Input
              id="subject-block"
              className="mt-1.5"
              type="number"
              min="1"
              value={blockLength}
              onChange={(e) => setBlockLength(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={fieldErrors.practical_block_length ? "subject-block-error" : undefined}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Labs default to one 2-hour block. Set to 1 to split into separate 1-hour sessions instead.
            </p>
            <FieldError id="subject-block-error" message={fieldErrors.practical_block_length} />
          </div>
          <div>
            <Label htmlFor="subject-credits">Credits (optional)</Label>
            <Input
              id="subject-credits"
              className="mt-1.5"
              type="number"
              value={credits}
              onChange={(e) => setCredits(e.target.value)}
              placeholder="e.g. 3"
              disabled={isSubmitting}
              aria-describedby={fieldErrors.credits ? "subject-credits-error" : undefined}
            />
            <FieldError id="subject-credits-error" message={fieldErrors.credits} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || enrollments.length === 0}>
              {isSubmitting ? "Adding…" : "Add Subject"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function SubjectsPage() {
  const toast = useToast();
  const { data, error, isLoading, retry } = useApi(getSubjects, ["subjects"]);
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [pendingDelete, setPendingDelete] = useState(null);
  const deletion = useMutation(deleteSubject);

  function openAddDialog() {
    setAddKey((key) => key + 1);
    setAddOpen(true);
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    const result = await deletion.execute(pendingDelete.id);
    if (result.ok) {
      toast.success(result.data.message || "Subject deleted.");
      setPendingDelete(null);
      retry();
      emitOnSuccess(result, SUBJECTS_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not delete subject.");
    }
  }

  if (isLoading && !data) {
    return (
      <Page title="Subjects" subtitle="Subject catalog with default weekly hours.">
        <PageLoading rows={6} label="Loading subjects…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page title="Subjects" subtitle="Subject catalog with default weekly hours.">
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const subjects = data.subjects ?? [];
  const enrollments = data.enrollments ?? [];

  return (
    <Page
      title="Subjects"
      subtitle={
        subjects.length === 0
          ? "Subject catalog with default weekly hours."
          : `${subjects.length} ${subjects.length === 1 ? "subject" : "subjects"} · program / year → subject → teaching assignment`
      }
      actions={
        <Button onClick={openAddDialog}>
          <Plus aria-hidden="true" />
          Add Subject
        </Button>
      }
    >
      {subjects.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title="No subjects yet"
          description={
            enrollments.length === 0
              ? "Add an enrollment first, then add your first subject."
              : "Add your first subject to get started."
          }
          action={
            <Button onClick={openAddDialog} className="mt-2">
              <Plus aria-hidden="true" />
              Add Subject
            </Button>
          }
        />
      ) : (
        <Panel accent="steel" title="All subjects">
          <Table aria-label="Subjects">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Code</TableHead>
                <TableHead scope="col">Name</TableHead>
                <TableHead scope="col">Program / Year</TableHead>
                <TableHead scope="col">Credits</TableHead>
                <TableHead scope="col">Theory</TableHead>
                <TableHead scope="col">Practical</TableHead>
                <TableHead scope="col">Block</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {subjects.map((subject) => (
                <TableRow key={subject.id}>
                  <TableCell className="font-medium text-ink">
                    {subject.code || <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell>{subject.name}</TableCell>
                  <TableCell>{`${subject.program_name ?? "?"} · ${subject.year_label ?? "?"}`}</TableCell>
                  <TableCell className="tabular-nums">
                    {subject.credits ?? <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell>
                    <Hours value={subject.theory_hours_per_week} unit="hrs/wk" />
                  </TableCell>
                  <TableCell>
                    <Hours value={subject.practical_hours_per_week} unit="hrs/wk" />
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {subject.practical_block_length != null ? (
                      `${subject.practical_block_length} periods`
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPendingDelete(subject)}
                      aria-label={`Delete subject ${subject.name}`}
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

      <AddSubjectDialog
        key={addKey}
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={retry}
        enrollments={enrollments}
      />
      <DeleteConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
            deletion.reset();
          }
        }}
        title={`Delete subject ${pendingDelete?.name ?? ""}?`}
        description="The subject will be removed. This cannot be undone."
        confirmLabel="Delete"
        onConfirm={handleDelete}
        isConfirming={deletion.isSubmitting}
        error={deletion.error}
      />
    </Page>
  );
}
