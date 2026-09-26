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
    super(typeof message === "string" && message ? message : "Request failed.");
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

  /** Stable machine code when the backend provided one (flat or nested shape). */
  get code() {
    const payload = this.payload;
    if (payload && typeof payload === "object") {
      if (typeof payload.code === "string") return payload.code;
      if (payload.error && typeof payload.error === "object"
          && typeof payload.error.code === "string") {
        return payload.error.code;
      }
    }
    return null;
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
    throw new ApiError(errorMessage(data, response.status), {
      status: response.status,
      fieldErrors: normalizeFieldErrors(data),
      payload: data && typeof data === "object" ? data : null,
    });
  }

  // Phase 6Q: a 2xx with an unreadable/empty body must surface as a
  // retryable failure, never as silent null data (pages branch on
  // data == null and would otherwise crash on property access).
  if (data === null || data === undefined || data === "") {
    throw new ApiError("The server returned an unreadable response. Try again.", {
      status: response.status,
      payload: null,
    });
  }

  return data;
}

/**
 * Phase 6Q: extract a safe user-facing string from any error body.
 * The backend always sends a string `error`, but non-JSON bodies and
 * future envelopes must never surface as `[object Object]`.
 */
function errorMessage(data, status) {
  if (data && typeof data === "object") {
    if (typeof data.error === "string" && data.error.trim()) {
      return data.error.trim().slice(0, 2000);
    }
    if (data.error && typeof data.error === "object"
        && typeof data.error.message === "string" && data.error.message.trim()) {
      return data.error.message.trim().slice(0, 2000);
    }
  }
  if (typeof data === "string" && data.trim()) {
    // Strip HTML shells (proxy/Werkzeug pages) down to readable text.
    const text = data.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    if (text) return text.slice(0, 200);
  }
  return `Request failed (${status}).`;
}

/** Keep only scalar field messages; objects/arrays would render as garbage. */
function normalizeFieldErrors(data) {
  const raw = data && typeof data === "object"
    ? (data.field_errors
      ?? (data.error && typeof data.error === "object" ? data.error.field_errors : null))
    : null;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const out = {};
  for (const [field, message] of Object.entries(raw)) {
    if (!field) continue;
    if (typeof message === "string" && message.trim()) out[field] = message.trim().slice(0, 2000);
    else if (typeof message === "number" || typeof message === "boolean") {
      out[field] = String(message);
    } else if (Array.isArray(message)) {
      const parts = message.filter((part) => ["string", "number", "boolean"].includes(typeof part));
      if (parts.length > 0) out[field] = parts.join(", ").slice(0, 2000);
    }
  }
  return Object.keys(out).length > 0 ? out : null;
}

export const api = {
  get: (path, opts) => request(path, { ...opts, method: "GET" }),
  post: (path, body, opts) => request(path, { ...opts, method: "POST", body }),
  del: (path, opts) => request(path, { ...opts, method: "DELETE" }),
};
