/**
 * Structured backend validation failures ({ code, message, details }[]).
 *
 * The Flask API preserves the domain RuleResult envelope on 422s as
 * `{ error, code, details, failures }` (see ApiError.payload). These
 * helpers turn that envelope into human-readable UI without inventing
 * explanations the backend did not provide.
 */

/** Structured backend failures if present, otherwise an empty list. */
export function getFailures(error) {
  const failures = error?.payload?.failures;
  return Array.isArray(failures) ? failures : [];
}

/** Short human-readable label per known backend rule code. */
export const FAILURE_LABELS = {  FACULTY_UNAVAILABLE: "Faculty unavailable",
  FACULTY_CONFLICT: "Faculty double-booked",
  FACULTY_CONSECUTIVE: "Consecutive-teaching limit",
  LOCKED_BLOCK: "Locked timetable block",
  SPECIALIZATION_SWAP: "Incompatible specialization swap",
  SPECIALIZATION_OVERLAP: "Specialization overlap",
  SPECIALIZATION_SYNC: "Specialization out of sync",
  SPECIALIZATION_CAPACITY: "Specialization capacity",
  SPECIALIZATION_ENROLLMENT: "Specialization cohort mismatch",
  SPECIALIZATION_MEMBERSHIP: "Specialization membership",
  SPECIALIZATION_INVALID: "Invalid specialization",
  PERSISTENCE_FAILED: "Could not save",
  INVALID_SWAP: "Invalid swap",
  UNKNOWN_ASSIGNMENT: "Assignment not found",
  UNKNOWN_FACULTY: "Faculty not found",
  UNKNOWN_ROOM: "Room not found",
  ROOM_CONFLICT: "Room already occupied",
  ROOM_CAPACITY: "Room too small",
  ROOM_TYPE_MISMATCH: "Wrong room type",
  SECTION_CONFLICT: "Section already has a class",
  SECTION_HIERARCHY_CONFLICT: "Lab/section overlap",
  MAX_TWO_THEORY: "Too much consecutive theory",
  UNKNOWN_DAY: "Unknown day",
  PERIOD_OUT_OF_RANGE: "Period out of range",
  BREAK_SPAN: "Block spans the break",
  BLOCK_GEOMETRY: "Invalid block placement",
  ROOM_REQUIRED: "Room required",
  ROOM_EQUIPMENT: "Room equipment insufficient",
  BLOCK_LENGTH_INVALID: "Invalid block length",
  ASSIGNMENT_MISMATCH: "Assignment mismatch",
  KIND_NOT_ENABLED: "Unsupported block kind",
  UNKNOWN_KIND: "Unknown block kind",
  UNKNOWN_LOCKED_BLOCK: "Fixed block not found",
  GROUP_CONFLICT: "Student group already has a class",
  MANUAL_EDIT_INVALID: "Invalid move request",
  UNKNOWN_PREFERENCE: "Preference not found",
  PREF_INVALID_KIND: "Unsupported preference kind",
  PREF_INVALID_DAYS: "Invalid preference days",
  PREF_INVALID_PERIOD: "Invalid preference period range",
  PREF_INVALID_WEIGHT: "Invalid preference weight",
  PREF_HARD_UNSUPPORTED: "Preferences are soft-only",
  // Phase 6Q: codes that reach the UI but had no label. Backend messages
  // stay authoritative; these only cover the short label line.
  UNKNOWN_SECTION: "Section not found",
  COVERAGE_MISMATCH: "Coverage mismatch",
  REASSIGNMENT_INVALID: "Invalid reassignment",
  PREFERENCE_INVALID: "Invalid preference",
  LOCKED_BLOCK_INVALID: "Invalid fixed block",
  SCHEDULING_INFEASIBLE: "No feasible schedule",
  SCHEDULING_FAILED: "Scheduling failed",
  INVALID_CREDENTIALS: "Incorrect username or password",
  AUTH_REQUIRED: "Sign-in required",
  NOT_FOUND: "Not found",
  BAD_REQUEST: "Invalid request",
  METHOD_NOT_ALLOWED: "Method not allowed",
  INTERNAL_ERROR: "Server error",
};

/** Secondary context line built only from fields the backend provided. */
export function failureContext(details) {
  if (!details || typeof details !== "object") return null;
  const bits = [];
  if (details.day != null) bits.push(`Day ${details.day}`);
  const period = details.period ?? details.start_period;
  if (period != null) bits.push(`Period ${period}`);
  if (details.scheduled_class_id != null) bits.push(`Class #${details.scheduled_class_id}`);
  if (details.conflicting_class_id != null) {
    bits.push(`conflicts with class #${details.conflicting_class_id}`);
  }
  return bits.length > 0 ? bits.join(" · ") : null;
}

/* ------------------------------------------------------------------ */
/* Phase 6Q — shared failure normalization. Every API/client failure   */
/* enters the UI through normalizeFailure(), so pages and feedback     */
/* components never parse envelopes ad hoc. Unknown shapes degrade to  */
/* a safe generic message; useful backend detail is never discarded.   */
/* ------------------------------------------------------------------ */

const GENERIC_MESSAGE = "Something went wrong. Please try again.";
const NETWORK_MESSAGE = "Could not reach the server. Check your connection and try again.";
const UNREADABLE_MESSAGE = "The server returned an unreadable response. Try again.";
const MAX_TEXT = 2000;

/** Coerce any value into safe display text (never undefined/null/[object Object]). */
export function safeMessage(value, fallback = GENERIC_MESSAGE) {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? trimmed.slice(0, MAX_TEXT) : fallback;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value != null && typeof value === "object") {
    // Prefer a nested message string; otherwise JSON (never "[object Object]").
    if (typeof value.message === "string" && value.message.trim()) {
      return value.message.trim().slice(0, MAX_TEXT);
    }
    try {
      const text = JSON.stringify(value);
      if (text && text !== "{}" && text !== "[]") return text.slice(0, MAX_TEXT);
    } catch {
      /* fall through to fallback */
    }
  }
  return fallback;
}

/** Display label for a machine code; unknown codes degrade to the code itself when safe. */
export function labelFor(code) {
  if (code && FAILURE_LABELS[code]) return FAILURE_LABELS[code];
  if (typeof code === "string" && /^[A-Z0-9_]{1,64}$/.test(code)) return code;
  return "Validation failed";
}

/** Coarse category for presentation (retryable page vs field vs auth vs scheduler). */
export function categoryFor({ status = null, code = null } = {}) {
  if (status === 0) return "network";
  if (status === 401) return "auth";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 422 || status == null) {
    if (code === "SCHEDULING_INFEASIBLE" || code === "SCHEDULING_FAILED") return "scheduler";
    return status === 422 ? "validation" : "error";
  }
  if (typeof status === "number" && status >= 500) return "internal";
  if (code === "SCHEDULING_INFEASIBLE" || code === "SCHEDULING_FAILED") return "scheduler";
  if (code === "INTERNAL_ERROR") return "internal";
  return "error";
}

/** Normalize a field_errors map into { field: message } of safe strings. */
export function normalizeFieldErrors(fieldErrors) {
  if (!fieldErrors || typeof fieldErrors !== "object" || Array.isArray(fieldErrors)) return {};
  const out = {};
  for (const [field, message] of Object.entries(fieldErrors)) {
    if (!field || typeof message === "object") continue;
    if (message == null || message === "") continue;
    out[field] = safeMessage(message);
  }
  return out;
}

/** Field errors from any failure shape (ApiError, normalized, or raw payload). */
export function getFieldErrors(error) {
  if (!error || typeof error !== "object") return {};
  if (error.fieldErrors && typeof error.fieldErrors === "object") {
    return normalizeFieldErrors(error.fieldErrors);
  }
  const payload = error.payload;
  if (payload && typeof payload === "object") {
    if (payload.field_errors) return normalizeFieldErrors(payload.field_errors);
    if (payload.error && typeof payload.error === "object" && payload.error.field_errors) {
      return normalizeFieldErrors(payload.error.field_errors);
    }
  }
  if (error.field_errors) return normalizeFieldErrors(error.field_errors);
  return {};
}

function readPayload(error) {
  const payload = error?.payload;
  return payload && typeof payload === "object" ? payload : null;
}

function readEnvelope(payload) {
  // Phase-6Q nested shape { ok, error: {...} } or legacy flat shape.
  if (payload?.error && typeof payload.error === "object") return payload.error;
  return payload;
}

/**
 * Normalize any failure into one representation:
 * { code, message, details, fieldErrors, failures, status, category }.
 * Handles structured API errors, field errors, scheduler/infeasibility
 * errors, import row errors, non-JSON HTTP errors, malformed JSON,
 * network failures, and unknown JS exceptions.
 */
export function normalizeFailure(input) {
  if (input != null && typeof input === "object" && "code" in input && "message" in input
      && "category" in input && !input.payload) {
    return input; // already normalized
  }
  if (input == null) {
    return { code: null, message: GENERIC_MESSAGE, details: null, fieldErrors: {},
             failures: [], importErrors: [], status: null, category: "error" };
  }
  if (typeof input === "string") {
    return { code: null, message: safeMessage(input), details: null, fieldErrors: {},
             failures: [], importErrors: [], status: null, category: "error" };
  }
  if (input instanceof Error && !("status" in input) && !("payload" in input)) {
    // Unknown JavaScript exception (not an ApiError): safe generic message.
    return { code: null, message: GENERIC_MESSAGE, details: null, fieldErrors: {},
             failures: [], importErrors: [], status: null, category: "error" };
  }

  const status = typeof input.status === "number" ? input.status : null;
  const payload = readPayload(input);
  const envelope = payload ? readEnvelope(payload) : null;

  const code = (envelope && typeof envelope.code === "string" && envelope.code)
    || (typeof input.code === "string" && input.code) || null;

  let message;
  if (payload && payload.error && typeof payload.error === "object") {
    message = safeMessage(payload.error.message, null);
  } else {
    message = safeMessage(payload?.error ?? input.message, null);
  }
  if (status === 0) message = message && message !== GENERIC_MESSAGE ? message : NETWORK_MESSAGE;
  message = message ?? (status === 0 ? NETWORK_MESSAGE : GENERIC_MESSAGE);

  const details = (envelope && typeof envelope.details === "object" && envelope.details)
    || (input.details && typeof input.details === "object" ? input.details : null);

  const rawFailures = (envelope && Array.isArray(envelope.failures) && envelope.failures)
    || (Array.isArray(input.failures) && input.failures) || [];
  const failures = rawFailures
    .map((entry) => {
      if (typeof entry === "string") return { code: null, message: safeMessage(entry), details: null };
      if (entry && typeof entry === "object") {
        return {
          code: typeof entry.code === "string" ? entry.code : null,
          message: safeMessage(entry.message, ""),
          details: entry.details ?? null,
        };
      }
      return null;
    })
    .filter(Boolean);

  // CSV import reports row problems as string lists on success payloads
  // ({ ok:true, errors: [...] }) and occasionally on failures.
  const rawImport = (payload && Array.isArray(payload.errors) && payload.errors)
    || (Array.isArray(input.errors) && input.errors) || [];
  const importErrors = rawImport
    .map((entry) => (typeof entry === "string" ? entry : safeMessage(entry)))
    .filter((entry) => entry.length > 0);

  if (!message || message === GENERIC_MESSAGE) {
    if (failures.length === 1 && failures[0].message) message = failures[0].message;
    else if (importErrors.length > 0) message = safeMessage(importErrors[0]);
    else if (status != null && status >= 200 && status < 300) message = UNREADABLE_MESSAGE;
  }

  return {
    code,
    message: safeMessage(message),
    details,
    fieldErrors: getFieldErrors(input),
    failures,
    importErrors,
    status,
    category: categoryFor({ status, code }),
  };
}

/** True when a generic (non-field) error box should be hidden (field errors shown inline). */
export function hasFieldErrors(error) {
  return Object.keys(getFieldErrors(error)).length > 0;
}

/** Row-level CSV import problems from an import success payload or failure. */
export function getImportRowErrors(source) {
  if (!source || typeof source !== "object") return [];
  const data = source.data && typeof source.data === "object" ? source.data : source;
  const list = Array.isArray(data.errors) ? data.errors : [];
  return list.map((entry) => (typeof entry === "string" ? entry : safeMessage(entry)));
}
