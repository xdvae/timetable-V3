import { useState } from "react";
import { Plus, School, Trash2 } from "lucide-react";

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
import { emitOnSuccess, PROGRAMS_DOMAINS } from "@/lib/propagation.js";
import { createProgram, deleteProgram, getPrograms } from "@/services/api/programs.js";

function AddProgramDialog({ open, onOpenChange, onCreated }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation(createProgram);
  const [name, setName] = useState("");
  const [department, setDepartment] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute({ name, department });
    if (result.ok) {
      toast.success(result.data.message || "Program added.");
      onOpenChange(false);
      onCreated();
      emitOnSuccess(result, PROGRAMS_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not add program.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add program</DialogTitle>
          <DialogDescription>Degree programs, e.g. BCA, B.Tech CSE.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationFailure error={error} />
          <div>
            <Label htmlFor="program-name">Name</Label>
            <Input
              id="program-name"
              className="mt-1.5"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. BCA, Btech CSE, MCA"
              disabled={isSubmitting}
              aria-describedby={fieldErrors.name ? "program-name-error" : undefined}
            />
            <FieldError id="program-name-error" message={fieldErrors.name} />
          </div>
          <div>
            <Label htmlFor="program-department">Department</Label>
            <Input
              id="program-department"
              className="mt-1.5"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={fieldErrors.department ? "program-department-error" : undefined}
            />
            <FieldError id="program-department-error" message={fieldErrors.department} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Adding…" : "Add Program"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ProgramsPage() {
  const toast = useToast();
  const { data: programs, error, isLoading, retry } = useApi(getPrograms, ["programs"]);
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [pendingDelete, setPendingDelete] = useState(null);
  const deletion = useMutation(deleteProgram);

  function openAddDialog() {
    setAddKey((key) => key + 1);
    setAddOpen(true);
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    const result = await deletion.execute(pendingDelete.id);
    if (result.ok) {
      toast.success(result.data.message || "Program deleted.");
      setPendingDelete(null);
      retry();
      emitOnSuccess(result, PROGRAMS_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not delete program.");
    }
  }

  if (isLoading && !programs) {
    return (
      <Page title="Programs" subtitle="Degree programs, e.g. BCA, B.Tech CSE.">
        <PageLoading rows={5} label="Loading programs…" />
      </Page>
    );
  }

  if (error && !programs) {
    return (
      <Page title="Programs" subtitle="Degree programs, e.g. BCA, B.Tech CSE.">
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  return (
    <Page
      title="Programs"
      subtitle={
        programs.length === 0
          ? "Degree programs, e.g. BCA, B.Tech CSE."
          : `${programs.length} ${programs.length === 1 ? "program" : "programs"} · enrollments live under each program`
      }
      actions={
        <Button onClick={openAddDialog}>
          <Plus aria-hidden="true" />
          Add Program
        </Button>
      }
    >
      {programs.length === 0 ? (
        <EmptyState
          icon={School}
          title="No programs yet"
          description="Add your first degree program to get started."
          action={
            <Button onClick={openAddDialog} className="mt-2">
              <Plus aria-hidden="true" />
              Add Program
            </Button>
          }
        />
      ) : (
        <Panel accent="steel" title="All programs">
          <Table aria-label="Programs">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Name</TableHead>
                <TableHead scope="col">Department</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {programs.map((program) => (
                <TableRow key={program.id}>
                  <TableCell className="font-medium text-ink">{program.name}</TableCell>
                  <TableCell>
                    {program.department || <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPendingDelete(program)}
                      aria-label={`Delete program ${program.name}`}
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

      <AddProgramDialog key={addKey} open={addOpen} onOpenChange={setAddOpen} onCreated={retry} />
      <DeleteConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
            deletion.reset();
          }
        }}
        title={`Delete program ${pendingDelete?.name ?? ""}?`}
        description="The program will be removed. This cannot be undone."
        confirmLabel="Delete"
        onConfirm={handleDelete}
        isConfirming={deletion.isSubmitting}
        error={deletion.error}
      />
    </Page>
  );
}
