import { api } from "./client.js";

/**
 * GET /api/rooms → { rooms: [{ id, name, room_type, capacity,
 * equipment_count|null }] } (live shape).
 */
export function getRooms() {
  return api.get("/api/rooms").then((payload) => payload.rooms ?? []);
}

/**
 * POST /api/rooms → 201 { ok, message, room }.
 * 422 { error, field_errors } on duplicate/invalid name or bad input.
 */
export function createRoom(payload) {
  return api.post("/api/rooms", payload);
}

/** POST /api/rooms/<id>/delete → 200 { ok, message }. 404 when missing. */
export function deleteRoom(id) {
  return api.post(`/api/rooms/${id}/delete`);
}
