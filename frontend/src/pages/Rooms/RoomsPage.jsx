import { useState } from "react";
import { DoorOpen, Plus, Trash2 } from "lucide-react";

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
import { DeleteConfirmDialog, FieldError, MutationFailure } from "@/components/feedback/mutation.jsx";
import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import { emitOnSuccess, ROOMS_DOMAINS } from "@/lib/propagation.js";
import { createRoom, deleteRoom, getRooms } from "@/services/api/rooms.js";

function RoomTypeBadge({ roomType }) {
  const variant = roomType === "lab" ? "lab" : "theory";
  const label = roomType === "lab" ? "Lab" : "Theory";
  return <Badge variant={variant}>{label}</Badge>;
}

const BLOCK_LETTERS = Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i));
const NO_BLOCK = "none";

/** "Block A · 101" for canonical names like "101-A"; plain number otherwise. */
function roomDisplayName(room) {
  if (!room) return "";
  if (room.block && room.number) return `Block ${room.block} · ${room.number}`;
  return room.number || room.name;
}

/** Theory rooms first, then labs; within each, by block then room number. */
function sortRooms(rooms) {
  return [...rooms].sort((a, b) => {
    const typeA = a.room_type === "lab" ? 1 : 0;
    const typeB = b.room_type === "lab" ? 1 : 0;
    if (typeA !== typeB) return typeA - typeB;
    const blockA = a.block ?? "";
    const blockB = b.block ?? "";
    if (blockA !== blockB) return blockA.localeCompare(blockB);
    return (Number(a.number) || 0) - (Number(b.number) || 0) || String(a.name).localeCompare(String(b.name));
  });
}

function AddRoomDialog({ open, onOpenChange, onCreated }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation(createRoom);
  const [block, setBlock] = useState("A");
  const [number, setNumber] = useState("");
  const [roomType, setRoomType] = useState("theory");
  const [capacity, setCapacity] = useState("");
  const [equipmentCount, setEquipmentCount] = useState("");

  function handleNumberChange(event) {
    // Digits only, max 4 — anything else is simply not typed.
    setNumber(event.target.value.replace(/\D/g, "").slice(0, 4));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute({
      block: block === NO_BLOCK ? "" : block,
      number,
      room_type: roomType,
      capacity,
      equipment_count: roomType === "lab" ? equipmentCount : "",
    });
    if (result.ok) {
      toast.success(result.data.message || "Room added.");
      onOpenChange(false);
      onCreated();
      emitOnSuccess(result, ROOMS_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not add room.");
    }
  }

  const preview = number
    ? block === NO_BLOCK
      ? `Room ${number}`
      : `Block ${block} · Room ${number}`
    : null;
  const numberError = fieldErrors.number || fieldErrors.name;

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add room</DialogTitle>
          <DialogDescription>Theory rooms and labs with capacity.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationFailure error={error} />
          <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-4">
            <div>
              <Label htmlFor="room-block">Block</Label>
              <Select value={block} onValueChange={setBlock} disabled={isSubmitting}>
                <SelectTrigger id="room-block" className="mt-1.5" aria-describedby={fieldErrors.block ? "room-block-error" : undefined}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="max-h-72">
                  {BLOCK_LETTERS.map((letter) => (
                    <SelectItem key={letter} value={letter}>
                      Block {letter}
                    </SelectItem>
                  ))}
                  <SelectItem value={NO_BLOCK}>No block</SelectItem>
                </SelectContent>
              </Select>
              <FieldError id="room-block-error" message={fieldErrors.block} />
            </div>
            <div>
              <Label htmlFor="room-number">Room number</Label>
              <Input
                id="room-number"
                className="mt-1.5 tabular-nums"
                required
                inputMode="numeric"
                pattern="[0-9]{1,4}"
                maxLength={4}
                autoComplete="off"
                value={number}
                onChange={handleNumberChange}
                placeholder="e.g. 101"
                disabled={isSubmitting}
                aria-describedby={numberError ? "room-number-error" : "room-number-hint"}
              />
              <FieldError id="room-number-error" message={numberError} />
            </div>
          </div>
          <p id="room-number-hint" className="-mt-2 text-xs text-muted-foreground">
            {preview ? (
              <>
                Will be saved as <span className="font-medium text-ink">{preview}</span>. Numbers only
                — the same room can never be entered twice.
              </>
            ) : (
              "Numbers only — the same room can never be entered twice."
            )}
          </p>
          <div>
            <Label htmlFor="room-type">Type</Label>
            <Select value={roomType} onValueChange={setRoomType} disabled={isSubmitting}>
              <SelectTrigger id="room-type" className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="theory">Theory Room</SelectItem>
                <SelectItem value="lab">Lab</SelectItem>
              </SelectContent>
            </Select>
            <FieldError id="room-type-error" message={fieldErrors.room_type} />
          </div>
          <div>
            <Label htmlFor="room-capacity">Capacity</Label>
            <Input
              id="room-capacity"
              className="mt-1.5"
              type="number"
              min="1"
              required
              value={capacity}
              onChange={(e) => setCapacity(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={fieldErrors.capacity ? "room-capacity-error" : undefined}
            />
            <FieldError id="room-capacity-error" message={fieldErrors.capacity} />
          </div>
          {roomType === "lab" ? (
            <div>
              <Label htmlFor="room-equipment">Equipment count (optional)</Label>
              <Input
                id="room-equipment"
                className="mt-1.5"
                type="number"
                min="0"
                value={equipmentCount}
                onChange={(e) => setEquipmentCount(e.target.value)}
                placeholder="e.g. number of computers"
                disabled={isSubmitting}
                aria-describedby={fieldErrors.equipment_count ? "room-equipment-error" : undefined}
              />
              <FieldError id="room-equipment-error" message={fieldErrors.equipment_count} />
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || !number}>
              {isSubmitting ? "Adding…" : "Add Room"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function RoomsPage() {
  const toast = useToast();
  const { data: rooms, error, isLoading, retry } = useApi(getRooms, ["rooms"]);
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [pendingDelete, setPendingDelete] = useState(null);
  const deletion = useMutation(deleteRoom);

  function openAddDialog() {
    setAddKey((key) => key + 1);
    setAddOpen(true);
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    const result = await deletion.execute(pendingDelete.id);
    if (result.ok) {
      toast.success(result.data.message || "Room deleted.");
      setPendingDelete(null);
      retry();
      emitOnSuccess(result, ROOMS_DOMAINS);
    } else if (result.error) {
      toast.error(result.error.message || "Could not delete room.");
    }
  }

  if (isLoading && !rooms) {
    return (
      <Page title="Rooms & Labs" subtitle="Theory rooms and labs with capacity.">
        <PageLoading rows={6} label="Loading rooms…" />
      </Page>
    );
  }

  if (error && !rooms) {
    return (
      <Page title="Rooms & Labs" subtitle="Theory rooms and labs with capacity.">
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const theoryCount = rooms.filter((r) => r.room_type !== "lab").length;
  const labCount = rooms.length - theoryCount;

  return (
    <Page
      title="Rooms & Labs"
      subtitle={
        rooms.length === 0
          ? "Theory rooms and labs with capacity."
          : `${rooms.length} rooms · ${theoryCount} theory · ${labCount} labs`
      }
      actions={
        <Button onClick={openAddDialog}>
          <Plus aria-hidden="true" />
          Add Room
        </Button>
      }
    >
      {rooms.length === 0 ? (
        <EmptyState
          icon={DoorOpen}
          title="No rooms yet"
          description="Add your first theory room or lab to get started."
          action={
            <Button onClick={openAddDialog} className="mt-2">
              <Plus aria-hidden="true" />
              Add Room
            </Button>
          }
        />
      ) : (
        <Panel accent="steel" title="All rooms">
          <Table aria-label="Rooms and labs">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Block</TableHead>
                <TableHead scope="col">Room No.</TableHead>
                <TableHead scope="col">Type</TableHead>
                <TableHead scope="col">Capacity</TableHead>
                <TableHead scope="col">Equipment</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortRooms(rooms).map((room) => (
                <TableRow key={room.id}>
                  <TableCell>
                    {room.block ? (
                      <span className="inline-flex size-7 items-center justify-center rounded-md bg-muted font-semibold text-ink">
                        {room.block}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="font-medium tabular-nums text-ink">{room.number ?? room.name}</TableCell>
                  <TableCell>
                    <RoomTypeBadge roomType={room.room_type} />
                  </TableCell>
                  <TableCell className="tabular-nums">{room.capacity} students</TableCell>
                  <TableCell className="tabular-nums">
                    {room.equipment_count ?? <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPendingDelete(room)}
                      aria-label={`Delete room ${roomDisplayName(room)}`}
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

      <AddRoomDialog key={addKey} open={addOpen} onOpenChange={setAddOpen} onCreated={retry} />
      <DeleteConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
            deletion.reset();
          }
        }}
        title={`Delete room ${pendingDelete ? roomDisplayName(pendingDelete) : ""}?`}
        description="Classes placed in this room are removed from the current timetable (generate again to re-place them). Rooms used by fixed blocks can't be deleted until those blocks are removed. This cannot be undone."
        confirmLabel="Delete"
        onConfirm={handleDelete}
        isConfirming={deletion.isSubmitting}
        error={deletion.error}
      />
    </Page>
  );
}
