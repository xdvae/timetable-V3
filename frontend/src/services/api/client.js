/**
 * Centralized API client for the Flask /api/* layer.
 *
 * - Same-origin fetch with session cookies (Flask-Login, no tokens).
 * - JSON in/out; FormData supported for CSV uploads (no manual Content-Type).
 * - HTTP errors surface as ApiError { message, status, fieldErrors } so pages
 *   never scrape HTML. Mirrors the backend error envelope:
 *   { "error": str, "field_errors"?: { field: str } }.
 */

export class ApiError extends Error {
  constructor(message, { status = 0, fieldErrors = null, payload = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fieldErrors = fieldErrors;
    this.payload = payload;
  }

  get isAuth() {
    return this.status === 401;
  }

  get isValidation() {
    return this.status === 422;
  }
}

function isFormData(body) {
  return typeof FormData !== "undefined" && body instanceof FormData;
}

export async function request(path, { method = "GET", body, signal } = {}) {
  const headers = { Accept: "application/json" };
  let payload;
  if (body !== undefined) {
    if (isFormData(body)) {
      payload = body; // browser sets multipart boundary itself
    } else {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
  }

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      body: payload,
      signal,
    });
  } catch (err) {
    if (err?.name === "AbortError") throw err;
    throw new ApiError("Could not reach the server. Check your connection and try again.", {
      status: 0,
    });
  }

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");

  if (!response.ok) {
    const message =
      (data && typeof data === "object" && data.error) ||
      (typeof data === "string" && data.slice(0, 200)) ||
      `Request failed (${response.status}).`;
    throw new ApiError(message, {
      status: response.status,
      fieldErrors: data && typeof data === "object" ? data.field_errors || null : null,
      payload: data,
    });
  }

  return data;
}

export const api = {
  get: (path, opts) => request(path, { ...opts, method: "GET" }),
  post: (path, body, opts) => request(path, { ...opts, method: "POST", body }),
  del: (path, opts) => request(path, { ...opts, method: "DELETE" }),
};
