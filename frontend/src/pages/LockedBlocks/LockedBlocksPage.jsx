import { useState } from "react";
import { Info, Lock, Plus, Trash2 } from "lucide-react";

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
import { emitOnSuccess, LOCKED_BLOCK_DOMAINS } from "@/lib/propagation.js";
import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import { createLockedBlock, deleteLockedBlock, getLockedBlocks } from "@/services/api/lockedBlocks.js";
import { getAssignments } from "@/services/api/assignments.js";
import { getRooms } from "@/services/api/rooms.js";
import { getConfig } from "@/services/api/config.js";

/**
 * Single stable fetcher composing every read the page needs. Locked blocks
 * carry IDs only, so assignments (names/context), rooms (names/capacity),
 * and config (day/period labels) are loaded alongside for display.
 */
function fetchLockedBlocksPage() {
  return Promise.all([getLockedBlocks(), getAssignments(), getRooms(), getConfig()]).then(
    ([blocks, assignments, rooms, config]) => ({
      blocks: blocks.lockedBlocks,
      assignments: assignments.assignments,
      rooms,
      days: config.days ?? [],
      periods: config.periods_list ?? [],
    })
  );
}

function assignmentOptionLabel(assignment) {
  return `${assignment.faculty_name} — ${assignment.subject_name} (${assignment.group})`;
}

function isSpecializationAssignment(assignment) {
  return (
    assignment != null &&
    assignment.section_id == null &&
    assignment.lab_group_id == null
  );
}

function SessionTypeBadge({ sessionType }) {
  const isPractical = sessionType === "practical";
  return <Badge variant={isPractical ? "lab" : "theory"}>{isPractical ? "Lab" : "Theory"}</Badge>;
}

function FixedNotice() {
  return (
    <Alert variant="info">
      <Info aria-hidden="true" />
      <AlertTitle>Fixed scheduling constraints</AlertTitle>
      <AlertDescription>
        <p>
          A locked block is a <strong>fixed scheduling input</strong>, not an ordinary class: the
          scheduler builds every future timetable around it and never moves it. A normal scheduled
          class is movable output. Changes here affect future schedule generations — the current
          timetable is never regenerated.
        </p>
      </AlertDescription>
    </Alert>
  );
}

function formatPlacement(block, periods) {
  const label = periods[block.start_period] ?? `Period ${block.start_period}`;
  const plural = block.length === 1 ? "period" : "periods";
  return `${block.day} · P${block.start_period} (${label}) × ${block.length} ${plural}`;
}

/**
 * Create dialog. Only backend-supported fields are collected: the teaching
 * assignment (faculty/subject/section are derived from it server-side),
 * day, start period, block length, room, plus optional department/note.
 * Local validation covers required fields and integer syntax only; room
 * conflicts, faculty conflicts, availability, geometry, HN1, hierarchy,
 * capacity, and specialization restrictions stay server-side and surface
 * as structured failures. No dry-run endpoint exists, so creation itself
 * is the authoritative validation (single POST, never duplicated).
 */
function CreateLockedBlockDialog({ open, onOpenChange, onCreated, options }) {
  const toast = useToast();
  const { assignments, rooms, days, periods } = options;
  const { execute, isSubmitting, error, fieldErrors } = useMutation(createLockedBlock);
  const [assignmentId, setAssignmentId] = useState(
    assignments[0] != null ? String(assignments[0].id) : ""
  );
  const [day, setDay] = useState(days[0] ?? "");
  const [startPeriod, setStartPeriod] = useState("0");
  const [length, setLength] = useState("1");
  const [roomId, setRoomId] = useState(rooms[0] != null ? String(rooms[0].id) : "");
  const [department, setDepartment] = useState("");
  const [note, setNote] = useState("");
  const selected = assignments.find((a) => String(a.id) === assignmentId) ?? null;
  const missing = [];
  if (assignments.length === 0) missing.push("teaching assignments");
  if (rooms.length === 0) missing.push("rooms");
  if (days.length === 0) missing.push("working days in Config");

  const startInt = Number(startPeriod);
  const lengthInt = Number(length);
  const localError =
    !Number.isInteger(startInt) || !Number.isInteger(lengthInt) || lengthInt < 1
      ? "Start period and block length must be whole numbers; block length must be at least 1."
      : null;

  const canSubmit =
    !isSubmitting && missing.length === 0 && assignmentId !== "" && day !== "" && localError === null;

  async function handleSubmit(event) {
    event.preventDefault();
    if (!canSubmit) return;
    const result = await execute({
      assignment_id: assignmentId,
      day,
      start_period: startPeriod,
      length,
      room_id: roomId,
      department: department.trim() === "" ? undefined : department.trim(),
      note: note.trim() === "" ? undefined : note.trim(),
    });
    if (result.ok) {
      toast.success(result.data.message || "Fixed block added.");
      onOpenChange(false);
      onCreated();
      // Phase 6P: config record + paired is_locked schedule row + assignment
      // display context changed. Failures emit nothing.
      emitOnSuccess(result, LOCKED_BLOCK_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not add fixed block.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add fixed block</DialogTitle>
          <DialogDescription>
            Pin one teaching assignment to an exact day, period, and room. The backend validates
            every hard rule before saving; failures are listed here without saving anything.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationFailure error={error} />
          {missing.length > 0 ? (
            <p className="text-sm font-medium text-signal" role="alert">
              Add {missing.join(", ")} first before creating a fixed block.
            </p>
          ) : null}
          <div>
            <Label htmlFor="locked-assignment">Teaching assignment</Label>
            <Select value={assignmentId} onValueChange={setAssignmentId} disabled={isSubmitting}>
              <SelectTrigger id="locked-assignment" className="mt-1.5">
                <SelectValue placeholder="Select an assignment" />
              </SelectTrigger>
              <SelectContent>
                {assignments.map((assignment) => (
                  <SelectItem key={assignment.id} value={String(assignment.id)}>
                    {assignmentOptionLabel(assignment)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldError id="locked-assignment-error" message={fieldErrors.assignment_id} />
            {selected ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Faculty, subject, and section/lab-group are taken from this assignment —{" "}
                {selected.session_type === "practical" ? "lab" : "theory"} · {selected.group} ·{" "}
                {selected.periods_per_week} periods/week.
              </p>
            ) : null}
            {selected && isSpecializationAssignment(selected) ? (
              <p className="mt-1 text-xs font-medium text-signal" role="alert">
                This looks like a specialization assignment (no section/lab group). The backend only
                pins normal section/lab teaching and will reject it — pick a regular assignment.
              </p>
            ) : null}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="locked-day">Day</Label>
              <Select value={day} onValueChange={setDay} disabled={isSubmitting}>
                <SelectTrigger id="locked-day" className="mt-1.5">
                  <SelectValue placeholder="Select a day" />
                </SelectTrigger>
                <SelectContent>
                  {days.map((d) => (
                    <SelectItem key={d} value={d}>
                      {d}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldError id="locked-day-error" message={fieldErrors.day} />
            </div>
            <div>
              <Label htmlFor="locked-start">Start period</Label>
              <Select value={startPeriod} onValueChange={setStartPeriod} disabled={isSubmitting}>
                <SelectTrigger id="locked-start" className="mt-1.5">
                  <SelectValue placeholder="Select a period" />
                </SelectTrigger>
                <SelectContent>
                  {periods.map((label, index) => (
                    <SelectItem key={index} value={String(index)}>
                      P{index} · {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldError id="locked-start-error" message={fieldErrors.start_period} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="locked-length">Block length (periods)</Label>
              <Input
                id="locked-length"
                className="mt-1.5"
                type="number"
                min="1"
                required
                value={length}
                onChange={(e) => setLength(e.target.value)}
                disabled={isSubmitting}
                aria-describedby={fieldErrors.length ? "locked-length-error" : undefined}
              />
              <FieldError id="locked-length-error" message={fieldErrors.length} />
            </div>
            <div>
              <Label htmlFor="locked-room">Room</Label>
              <Select value={roomId} onValueChange={setRoomId} disabled={isSubmitting}>
                <SelectTrigger id="locked-room" className="mt-1.5">
                  <SelectValue placeholder="Select a room" />
                </SelectTrigger>
                <SelectContent>
                  {rooms.map((room) => (
                    <SelectItem key={room.id} value={String(room.id)}>
                      {room.name} · {room.room_type} · {room.capacity} seats
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldError id="locked-room-error" message={fieldErrors.room_id} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="locked-department">Owning department (optional)</Label>
              <Input
                id="locked-department"
                className="mt-1.5"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                placeholder="e.g. Mathematics"
                disabled={isSubmitting}
              />
            </div>
            <div>
              <Label htmlFor="locked-note">Note (optional)</Label>
              <Input
                id="locked-note"
                className="mt-1.5"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Why this slot is fixed"
                disabled={isSubmitting}
              />
            </div>
          </div>
          {localError ? (
            <p className="text-xs font-medium text-signal" role="alert">
              {localError}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {isSubmitting ? "Adding…" : "Add Fixed Block"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Interdepartment / locked-block administration. List, create, and delete
 * live here; the backend exposes no update endpoint, so changing a block
 * means delete + recreate (delete only frees resources, so that round-trip
 * is safe). Every mutation refetches the authoritative list before
 * rendering. This page never calls POST /api/schedule/run.
 */
export function LockedBlocksPage() {
  const toast = useToast();
  const query = useApi(fetchLockedBlocksPage, ["lockedBlocks", "assignments", "rooms", "config"]);
  const [createOpen, setCreateOpen] = useState(false);
  const [createKey, setCreateKey] = useState(0);
  const [pendingDelete, setPendingDelete] = useState(null);
  const deletion = useMutation(deleteLockedBlock);
  const deleteFailures = getFailures(deletion.error);

  function openCreateDialog() {
    setCreateKey((key) => key + 1);
    setCreateOpen(true);
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    const result = await deletion.execute(pendingDelete.id);
    if (result.ok) {
      toast.success(result.data.message || "Fixed block removed.");
      setPendingDelete(null);
      query.retry();
      emitOnSuccess(result, LOCKED_BLOCK_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not remove fixed block.");
    }
  }

  if (query.isLoading && !query.data) {
    return (
      <Page
        title="Fixed Blocks"
        subtitle="Interdepartment classes pinned to an exact day, period, and room."
        breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Fixed Blocks" }]}
      >
        <PageLoading rows={5} label="Loading fixed blocks…" />
      </Page>
    );
  }

  if (!query.data) {
    return (
      <Page
        title="Fixed Blocks"
        subtitle="Interdepartment classes pinned to an exact day, period, and room."
        breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Fixed Blocks" }]}
      >
        <QueryError error={query.error} onRetry={query.retry} />
      </Page>
    );
  }

  const { blocks, assignments, rooms, periods } = query.data;
  const assignmentById = new Map(assignments.map((a) => [String(a.id), a]));
  const roomById = new Map(rooms.map((r) => [String(r.id), r]));
  const subtitle =
    blocks.length === 0
      ? "Interdepartment classes pinned to an exact day, period, and room."
      : `${blocks.length} ${blocks.length === 1 ? "fixed block constrains" : "fixed blocks constrain"} future schedule generations`;

  return (
    <Page
      title="Fixed Blocks"
      subtitle={subtitle}
      breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Fixed Blocks" }]}
      actions={
        <Button onClick={openCreateDialog}>
          <Plus aria-hidden="true" />
          Add Fixed Block
        </Button>
      }
    >
      <div className="space-y-5">
        <FixedNotice />
        {blocks.length === 0 ? (
          <EmptyState
            icon={Lock}
            title="No fixed blocks yet"
            description="A fixed block pins one teaching assignment — e.g. an interdepartment class taught by another department — to an exact day, period, and room. Future timetables are built around it; the current timetable stays untouched."
            action={
              <Button onClick={openCreateDialog} className="mt-2">
                <Plus aria-hidden="true" />
                Add Fixed Block
              </Button>
            }
          />
        ) : (
          <Panel
            accent="steel"
            title="All fixed blocks"
            description="Blocks cannot be edited in place — delete and recreate a block to change it. Deleting only removes the constraint; it never regenerates the timetable."
          >
            <Table aria-label="Fixed interdepartment blocks">
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Assignment</TableHead>
                  <TableHead scope="col">Type</TableHead>
                  <TableHead scope="col">Placement</TableHead>
                  <TableHead scope="col">Room</TableHead>
                  <TableHead scope="col">Source</TableHead>
                  <TableHead scope="col">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {blocks.map((block) => {
                  const assignment = assignmentById.get(String(block.assignment_id)) ?? null;
                  const room = roomById.get(String(block.room_id)) ?? null;
                  return (
                    <TableRow key={block.id}>
                      <TableCell className="font-medium text-ink">
                        {assignment ? (
                          <>
                            {assignment.subject_name} · {assignment.faculty_name}
                            <span className="block text-xs font-normal text-muted-foreground">
                              {assignment.group}
                            </span>
                          </>
                        ) : (
                          `Assignment ${block.assignment_id}`
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1.5">
                          <Badge variant="danger">
                            <Lock aria-hidden="true" />
                            Fixed
                          </Badge>
                          {assignment ? <SessionTypeBadge sessionType={assignment.session_type} /> : null}
                        </div>
                      </TableCell>
                      <TableCell className="tabular-nums">{formatPlacement(block, periods)}</TableCell>
                      <TableCell>{room ? `${room.name} (${room.capacity} seats)` : `Room ${block.room_id}`}</TableCell>
                      <TableCell>{block.department || "—"}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setPendingDelete(block)}
                          aria-label={`Delete fixed block for ${assignment ? assignmentOptionLabel(assignment) : `assignment ${block.assignment_id}`} on ${block.day}`}
                        >
                          <Trash2 aria-hidden="true" className="text-signal" />
                          Delete
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Panel>
        )}
      </div>

      <CreateLockedBlockDialog
        key={createKey}
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={query.retry}
        options={query.data}
      />
      <DeleteConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
            deletion.reset();
          }
        }}
        title="Remove this fixed block?"
        description="This removes the fixed scheduling constraint and its locked timetable row. The current timetable is not regenerated — the change only affects future schedule generations. This cannot be undone."
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
