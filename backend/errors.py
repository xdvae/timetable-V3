"""Phase 6Q — unified error contract for the JSON API layer.

Additive by design: every helper here produces the *existing* flat error
shape (``{"error", "code"?, "details"?, "field_errors"?, "failures"?}``)
plus an ``ok: false`` marker, so pre-6Q clients and tests keep working
while new clients can rely on one coherent representation:

    {
      "ok": false,
      "error": "<safe user-facing message>",
      "code": "<STABLE_UPPER_SNAKE>",
      "details": {...},        # present only when non-empty
      "field_errors": {...},   # present only when non-empty
      "failures": [...]        # present only when non-empty
    }

Rules enforced here (not at 60 call sites):

* every error carries a stable machine-readable ``code``;
* user-facing messages are always plain strings — never tracebacks, SQL
  fragments, filesystem paths, or exception internals;
* raw ``str(exc)`` text from persistence rollbacks is never embedded in a
  message (callers pass the safe base message; diagnostics stay in the
  server process);
* HTTP status keeps its existing meaning (401 auth, 404 missing,
  422 validation, 500 internal) — see ``category_for``;
* successful response shapes are untouched by this module.
"""

# Codes for errors that previously had no machine-readable code. All
# pre-existing public codes are preserved verbatim (see api_routes.py and
# the domain services); these only fill gaps so that *every* API error
# conforms to the contract.
INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
AUTH_REQUIRED = "AUTH_REQUIRED"
NOT_FOUND = "NOT_FOUND"
METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
BAD_REQUEST = "BAD_REQUEST"
SCHEDULING_FAILED = "SCHEDULING_FAILED"
INTERNAL_ERROR = "INTERNAL_ERROR"

INTERNAL_ERROR_MESSAGE = (
    "Something went wrong on the server. Please try again."
)

# Conservative bound so details/failures can never balloon a response.
_MAX_STR_LEN = 2000


def category_for(status, code=None):
    """Coarse client-side category: never overrides status semantics.

    Validation-only responses stay distinguishable from authoritative
    mutation failures, and auth failures stay distinguishable from both.
    """
    if status == 401:
        return "auth"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "not_found"
    if status == 409:
        return "conflict"
    if status == 422:
        if code in ("SCHEDULING_INFEASIBLE", SCHEDULING_FAILED):
            return "scheduler"
        return "validation"
    if status and status >= 500:
        return "internal"
    if code in ("SCHEDULING_INFEASIBLE", SCHEDULING_FAILED):
        return "scheduler"
    return "error"


def _safe_message(message, fallback="The operation could not be completed."):
    """Coerce to a plain user-safe string (never None/object/traceback)."""
    if isinstance(message, str) and message.strip():
        return message.strip()[:_MAX_STR_LEN]
    return fallback


def _safe_json(value, _depth=0):
    """JSON-round-trippable copy of details/failures (drops internals)."""
    if _depth > 6:
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, str) and len(value) > _MAX_STR_LEN:
            return value[:_MAX_STR_LEN]
        return value
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                key = str(key)
            # Never leak keys that smell like internals/secrets.
            lowered = key.lower()
            if any(token in lowered for token in (
                    "traceback", "stack", "secret", "password",
                    "environ", "sqlalchemy", "engine", "session")):
                continue
            out[key[:128]] = _safe_json(item, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_safe_json(item, _depth + 1) for item in value[:100]]
    return str(value)[:_MAX_STR_LEN]


def _normalize_field_errors(field_errors):
    """Keep only string-coercible scalar messages keyed by field name."""
    if not isinstance(field_errors, dict):
        return None
    out = {}
    for field, message in field_errors.items():
        if not isinstance(field, str) or not field:
            continue
        if isinstance(message, str) and message.strip():
            out[field] = message.strip()[:_MAX_STR_LEN]
        elif isinstance(message, (int, float, bool)):
            out[field] = str(message)
        elif isinstance(message, (list, tuple)):
            parts = [str(part) for part in message
                     if isinstance(part, (str, int, float, bool))]
            if parts:
                out[field] = ", ".join(parts)[:_MAX_STR_LEN]
        # Dicts/objects/None are dropped: they would render as
        # "[object Object]" downstream and carry no field guidance.
    return out or None


def error_payload(code, message, status=422, details=None,
                  field_errors=None, failures=None):
    """Build the unified error body (no Flask dependency)."""
    code = code if isinstance(code, str) and code else INTERNAL_ERROR
    safe_details = _safe_json(details) if details is not None else None
    safe_fields = _normalize_field_errors(field_errors)
    safe_failures = _safe_json(failures) if failures is not None else None
    payload = {
        "ok": False,
        "error": _safe_message(message),
        "code": code,
    }
    if safe_details:
        payload["details"] = safe_details
    if safe_fields:
        payload["field_errors"] = safe_fields
    if safe_failures:
        payload["failures"] = safe_failures
    return payload


def error_response(code, message, status=422, details=None,
                   field_errors=None, failures=None):
    """Flask ``(jsonify(payload), status)`` tuple for the unified contract."""
    from flask import jsonify  # local import: keeps this module test-light
    return jsonify(error_payload(
        code=code, message=message, status=status, details=details,
        field_errors=field_errors, failures=failures)), status
