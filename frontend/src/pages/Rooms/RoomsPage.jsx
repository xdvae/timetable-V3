import { DoorOpen } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { Badge } from "@/components/ui/badge.jsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.jsx";
import { useApi } from "@/hooks/use-api.js";
import { getRooms } from "@/services/api/rooms.js";

function RoomTypeBadge({ roomType }) {
  const variant = roomType === "lab" ? "lab" : "theory";
  const label = roomType === "lab" ? "Lab" : "Theory";
  return <Badge variant={variant}>{label}</Badge>;
}

export function RoomsPage() {
  const { data: rooms, error, isLoading, retry } = useApi(getRooms);

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
    >
      {rooms.length === 0 ? (
        <EmptyState
          icon={DoorOpen}
          title="No rooms yet"
          description="Rooms added in the backend will appear here with their type, capacity, and equipment."
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
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Panel>
      )}
    </Page>
  );
}
