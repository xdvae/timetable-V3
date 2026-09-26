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
import { DeleteConfirmDialog, FieldError, MutationError } from "@/components/feedback/mutation.jsx";
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

function AddRoomDialog({ open, onOpenChange, onCreated }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation(createRoom);
  const [name, setName] = useState("");
  const [roomType, setRoomType] = useState("theory");
  const [capacity, setCapacity] = useState("");
  const [equipmentCount, setEquipmentCount] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute({
      name,
      room_type: roomType,
      capacity,
      equipment_count: equipmentCount,
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

  return (
    <Dialog open={open} onOpenChange={isSubmitting ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add room</DialogTitle>
          <DialogDescription>Theory rooms and labs with capacity.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <MutationError error={error && !error.fieldErrors ? error : null} />
          <div>
            <Label htmlFor="room-name">Room Number</Label>
            <Input
              id="room-name"
              className="mt-1.5"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. 503 B or 301"
              disabled={isSubmitting}
              aria-describedby={fieldErrors.name ? "room-name-error" : undefined}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Only a room number with an optional single block letter is accepted — spellings normalize
              to one fixed form, so the same room can never be entered twice.
            </p>
            <FieldError id="room-name-error" message={fieldErrors.name} />
          </div>
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
              required
              value={capacity}
              onChange={(e) => setCapacity(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={fieldErrors.capacity ? "room-capacity-error" : undefined}
            />
            <FieldError id="room-capacity-error" message={fieldErrors.capacity} />
          </div>
          <div>
            <Label htmlFor="room-equipment">Equipment count (labs only, optional)</Label>
            <Input
              id="room-equipment"
              className="mt-1.5"
              type="number"
              value={equipmentCount}
              onChange={(e) => setEquipmentCount(e.target.value)}
              placeholder="e.g. number of computers"
              disabled={isSubmitting}
              aria-describedby={fieldErrors.equipment_count ? "room-equipment-error" : undefined}
            />
            <FieldError id="room-equipment-error" message={fieldErrors.equipment_count} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
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
                <TableHead scope="col">Name</TableHead>
                <TableHead scope="col">Type</TableHead>
                <TableHead scope="col">Capacity</TableHead>
                <TableHead scope="col">Equipment</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rooms.map((room) => (
                <TableRow key={room.id}>
                  <TableCell className="font-medium text-ink">{room.name}</TableCell>
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
                      aria-label={`Delete room ${room.name}`}
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
        title={`Delete room ${pendingDelete?.name ?? ""}?`}
        description="The room will be removed. This cannot be undone."
        confirmLabel="Delete"
        onConfirm={handleDelete}
        isConfirming={deletion.isSubmitting}
        error={deletion.error}
      />
    </Page>
  );
}
