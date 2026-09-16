import { api } from "./client.js";

/**
 * Auth service — thin wrappers over the session-cookie endpoints.
 * No tokens are created or stored anywhere; the browser cookie is the session.
 */
export function login(username, password, next) {
  const suffix = next ? `?next=${encodeURIComponent(next)}` : "";
  return api.post(`/api/login${suffix}`, { username, password });
}

export function logout() {
  return api.post("/api/logout");
}

export function me() {
  return api.get("/api/me");
}

export function changePassword({ currentPassword, newPassword, confirmPassword }) {
  return api.post("/api/change-password", {
    current_password: currentPassword,
    new_password: newPassword,
    confirm_password: confirmPassword,
  });
}
