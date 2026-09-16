import { api } from "./client.js";

/**
 * GET /api/rooms → { rooms: [{ id, name, room_type, capacity,
 * equipment_count|null }] } (live shape).
 */
export function getRooms() {
  return api.get("/api/rooms").then((payload) => payload.rooms ?? []);
}
