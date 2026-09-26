"""
Phase 6J — Faculty custom preferences (domain service).

Optional per-faculty scheduling preferences, stored on the existing
``FacultyPreference`` table (introduced additively in Phase 6C, still
unconsumed until now). Every preference in this phase is SOFT: it can
only nudge the scheduler's objective, never forbid a placement.

Supported kinds (Phase 6J audit outcome):

* ``TIME_WINDOW`` — the faculty prefers teaching inside
  ``[start_period, end_period)`` on ``days`` (blank days = every working
  day). A placement whose covered periods all lie inside the window on a
  listed day satisfies it; anything else costs one soft penalty unit.
* ``DAY_OFF_PREFERENCE`` — the faculty prefers no teaching on ``days``
  (non-empty). Each placement on a listed day costs one soft penalty
  unit, so an empty day is simply never penalized.

Deferred (rejected by the API with an explicit code, never silently
stored): ``SUBJECT_AFFINITY`` (assignment-level affinity, not a
per-placement property — no clean scheduler encoding) and any
per-faculty consecutive-teaching limit (non-linear day-run reasoning;
the global hard ``max_consecutive_teaching`` limit already protects
faculty; see ``schedule_rules.check_faculty_consecutive``).

Hard vs soft: ``is_hard=True`` is rejected by the API
(``PREF_HARD_UNSUPPORTED``) — nothing in 6J may convert a preference
into a hard constraint. The scheduler additionally treats every row as
soft regardless of the stored flag, so legacy/hand-edited rows can
never make a feasible schedule infeasible.

``weight`` (1-10, the pre-existing CHECK constraint) is accepted,
validated, stored, and returned, but the 6J scheduler treats all
enabled preferences equally (binary per-session penalty, capped at 1
per session so the objective hierarchy stays provable). Weight is
reserved for future prioritization.

Layout mirrors ``faculty_reassignment.py`` / ``manual_edits.py``: pure
helpers (no Flask, no ORM, no OR-Tools) plus thin ``db``-taking CRUD
helpers. The API layer maps ``PreferenceError`` onto the structured
``ApiError`` envelope. The scheduler only imports the pure helpers.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


SUPPORTED_KINDS = ("TIME_WINDOW", "DAY_OFF_PREFERENCE")
# Kinds present in the 6C schema docstring but deliberately unsupported
# in 6J (see module docstring for why).
DEFERRED_KINDS = ("SUBJECT_AFFINITY",)

MIN_WEIGHT = 1
MAX_WEIGHT = 10
DEFAULT_WEIGHT = 5

#: Per-session faculty penalty cap. One violated preference costs 1 and
#: the per-session total never exceeds this cap, so the combined
#: secondary objective (preferred rooms + faculty prefs) stays bounded
#: by 2 * num_sessions and the scheduler can keep start-time
#: minimization strictly dominant (see scheduler.faculty_time_scale).
MAX_FACULTY_PENALTY_PER_SESSION = 1


class PreferenceError(Exception):
    """Raised when a faculty-preference mutation fails validation.

    Carries ``failures``: a list of ``{"code", "message", "details"}``
    dicts with stable UPPER_SNAKE codes, mirroring the
    FacultyReassignmentError / ManualEditError contract.
    """

    def __init__(self, message, failures=None):
        super().__init__(message)
        self.message = message
        self.failures = list(failures or [])

    def to_payload(self):
        primary = self.failures[0] if self.failures else None
        return {
            "error": self.message,
            "code": primary["code"] if primary else "PREFERENCE_INVALID",
            "details": primary["details"] if primary else {},
            "failures": list(self.failures),
        }


def _fail(code, message, details=None):
    return {"code": code, "message": message,
            "details": details or {}}


# ------------------------------------------------------------- pure parsers
def parse_days(days_raw) -> List[str]:
    """Split a comma-separated days string into a clean day list.

    Pure: never raises. Non-string input yields []. Order is preserved,
    duplicates removed, blanks dropped (``"Mon, Tue,,Mon"`` ->
    ``["Mon", "Tue"]``).
    """
    if not isinstance(days_raw, str):
        return []
    seen = []
    for tok in days_raw.split(","):
        tok = tok.strip()
        if tok and tok not in seen:
            seen.append(tok)
    return seen


def _coerce_int(value):
    """Coerce to int or return None (pure, never raises)."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, float):
            if not value.is_integer():
                return None
            return int(value)
        return int(str(value).strip() if isinstance(value, str) else value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value, default=True):
    """Coerce JSON/form booleans (pure, never raises)."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return default


def _row_get(row, name, default=None):
    """Attribute-or-key access for ORM rows, dicts, and namespaces."""
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


# ------------------------------------------------------- scheduler scoring
def normalize_faculty_preferences(rows, days, num_periods) -> Dict[int, list]:
    """Clean preference rows into a solver-ready map (pure, never raises).

    Returns ``{faculty_id: [clean_pref, ...]}`` where each clean pref is
    ``{"kind", "days", "start_period", "end_period"}``. Drops (never
    crashes on): disabled rows, unknown/deferred kinds, unknown faculty
    ids, days outside ``days`` (TIME_WINDOW blank days = all working
    days; DAY_OFF requires at least one known day), non-integer or
    impossible period ranges (``0 <= start < end <= num_periods``),
    and non-positive lengths. ``is_hard``/``weight`` are intentionally
    not consulted: every surviving row scores as one equal soft unit.
    Missing/empty input yields {} (neutral: zero penalty everywhere).
    """
    working = list(days or [])
    try:
        n_periods = int(num_periods or 0)
    except (TypeError, ValueError):
        n_periods = 0
    clean: Dict[int, list] = {}
    for row in rows or []:
        try:
            fid = _row_get(row, "faculty_id")
            fid = int(fid)
        except (TypeError, ValueError):
            continue
        # Missing/None stays enabled (the model default is True);
        # explicit False/0/"false" disables the row.
        enabled_raw = _row_get(row, "enabled", True)
        if enabled_raw is not None \
                and _coerce_bool(enabled_raw, default=True) is False:
            continue
        kind = _row_get(row, "kind")
        if kind not in SUPPORTED_KINDS:
            continue
        raw_days = parse_days(_row_get(row, "days"))
        if kind == "DAY_OFF_PREFERENCE":
            listed = [d for d in raw_days if d in working]
            if not listed:
                continue
            clean.setdefault(fid, []).append({
                "kind": kind, "days": listed,
                "start_period": None, "end_period": None,
            })
        else:  # TIME_WINDOW
            known = [d for d in raw_days if d in working]
            if raw_days and not known:
                continue  # days given but none are working days
            listed = known or list(working)  # blank days = all working days
            start = _coerce_int(_row_get(row, "start_period"))
            end = _coerce_int(_row_get(row, "end_period"))
            if start is None or end is None:
                continue
            if not (0 <= start < end <= n_periods):
                continue
            clean.setdefault(fid, []).append({
                "kind": kind, "days": listed,
                "start_period": start, "end_period": end,
            })
    return clean


def faculty_time_penalty(faculty_id, day, start, length,
                         prefs_by_faculty) -> int:
    """Soft 0/1 penalty for one candidate placement (Phase 6J).

    Returns 0 when the faculty has no (surviving) preferences, and 1
    when the placement violates at least one of them:

    * TIME_WINDOW: satisfied only when ``day`` is listed and every
      covered period lies in ``[start_period, end_period)``;
    * DAY_OFF_PREFERENCE: violated when ``day`` is listed.

    Pure: operates on plain ints/strings plus the normalized map only.
    Never raises on missing/odd input (yields 0). Capped at
    MAX_FACULTY_PENALTY_PER_SESSION by construction (binary).
    """
    prefs = (prefs_by_faculty or {}).get(faculty_id) if faculty_id is not None else None
    if not prefs:
        return 0
    try:
        covered = set(range(int(start), int(start) + int(length)))
    except (TypeError, ValueError):
        return 0
    for pref in prefs:
        kind = pref.get("kind")
        if kind == "DAY_OFF_PREFERENCE":
            if day in (pref.get("days") or []):
                return 1
        elif kind == "TIME_WINDOW":
            if day not in (pref.get("days") or []):
                return 1
            try:
                lo, hi = int(pref["start_period"]), int(pref["end_period"])
            except (TypeError, ValueError):
                return 1  # malformed survivor: penalize rather than crash
            if any(p < lo or p >= hi for p in covered):
                return 1
    return 0


# ------------------------------------------------------- validation (pure)
@dataclass
class CleanPreference:
    """Validated create/update payload (still ORM-free)."""
    kind: str = ""
    days: List[str] = field(default_factory=list)
    start_period: Optional[int] = None
    end_period: Optional[int] = None
    weight: int = DEFAULT_WEIGHT
    enabled: bool = True


def validate_preference_payload(data, working_days, num_periods) -> CleanPreference:
    """Validate a create/update payload; raise PreferenceError on failure.

    ``data`` is a plain dict (JSON body or coerced form). ``working_days``
    is the config day list, ``num_periods`` the period count. Pure.
    """
    data = dict(data or {})
    kind = data.get("kind")
    if isinstance(kind, str):
        kind = kind.strip()
    if kind not in SUPPORTED_KINDS:
        if kind in DEFERRED_KINDS:
            raise PreferenceError(
                f"Preference kind '{kind}' is not supported yet.",
                [_fail("PREF_INVALID_KIND",
                       f"Preference kind '{kind}' is recognized but not "
                       f"supported in this phase (only "
                       f"{', '.join(SUPPORTED_KINDS)} may be configured).",
                       {"kind": kind,
                        "supported_kinds": list(SUPPORTED_KINDS)})])
        raise PreferenceError(
            "Unsupported preference kind.",
            [_fail("PREF_INVALID_KIND",
                   f"Unknown preference kind {kind!r}: supported kinds are "
                   f"{', '.join(SUPPORTED_KINDS)}.",
                   {"kind": kind,
                    "supported_kinds": list(SUPPORTED_KINDS)})])

    # Hard preferences are never configurable (soft-only phase).
    is_hard_raw = data.get("is_hard", False)
    if _coerce_bool(is_hard_raw, default=False) is True:
        raise PreferenceError(
            "Faculty preferences are soft-only.",
            [_fail("PREF_HARD_UNSUPPORTED",
                   "Faculty preferences are soft scheduling hints: they "
                   "influence future timetable generation but can never "
                   "forbid a placement. Hard unavailability stays on the "
                   "faculty availability grid.",
                   {"is_hard": True})])

    raw_days = data.get("days")
    if isinstance(raw_days, (list, tuple)):
        day_list = [str(d).strip() for d in raw_days
                    if str(d).strip()]
        # de-duplicate, preserve order
        day_list = list(dict.fromkeys(day_list))
    else:
        day_list = parse_days(raw_days)
    unknown = [d for d in day_list if d not in (working_days or [])]
    if unknown:
        raise PreferenceError(
            "Unknown day in preference.",
            [_fail("PREF_INVALID_DAYS",
                   f"Unknown day(s) {unknown}: must be configured working "
                   f"days ({', '.join(working_days or [])}).",
                   {"days": day_list, "unknown_days": unknown,
                    "working_days": list(working_days or [])})])

    start = _coerce_int(data.get("start_period"))
    end = _coerce_int(data.get("end_period"))
    if kind == "TIME_WINDOW":
        if start is None or end is None:
            raise PreferenceError(
                "Time window needs a period range.",
                [_fail("PREF_INVALID_PERIOD",
                       "TIME_WINDOW preferences require start_period and "
                       "end_period (0-based period indexes, "
                       "start < end).",
                       {"start_period": data.get("start_period"),
                        "end_period": data.get("end_period"),
                        "num_periods": num_periods})])
        if not (0 <= start < end <= (num_periods or 0)):
            raise PreferenceError(
                "Impossible time window.",
                [_fail("PREF_INVALID_PERIOD",
                       f"Time window [{start}, {end}) is impossible: "
                       f"require 0 <= start < end <= {num_periods}.",
                       {"start_period": start, "end_period": end,
                        "num_periods": num_periods})])
        days = day_list or list(working_days or [])
    else:  # DAY_OFF_PREFERENCE
        if start is not None or end is not None:
            raise PreferenceError(
                "Day-off preferences take no period range.",
                [_fail("PREF_INVALID_PERIOD",
                       "DAY_OFF_PREFERENCE takes only days (no "
                       "start_period/end_period).",
                       {"start_period": data.get("start_period"),
                        "end_period": data.get("end_period")})])
        if not day_list:
            raise PreferenceError(
                "Day-off preference needs days.",
                [_fail("PREF_INVALID_DAYS",
                       "DAY_OFF_PREFERENCE requires at least one day.",
                       {"days": day_list,
                        "working_days": list(working_days or [])})])
        days = day_list
        start = end = None

    weight = _coerce_int(data.get("weight", DEFAULT_WEIGHT))
    if weight is None:
        weight = DEFAULT_WEIGHT
    if not (MIN_WEIGHT <= weight <= MAX_WEIGHT):
        raise PreferenceError(
            "Invalid preference weight.",
            [_fail("PREF_INVALID_WEIGHT",
                   f"Weight must be a whole number {MIN_WEIGHT}-{MAX_WEIGHT}.",
                   {"weight": data.get("weight"),
                    "min_weight": MIN_WEIGHT,
                    "max_weight": MAX_WEIGHT})])

    enabled = _coerce_bool(data.get("enabled", True), default=True)

    return CleanPreference(kind=kind, days=days, start_period=start,
                           end_period=end, weight=weight, enabled=enabled)


# ------------------------------------------------------- ORM helpers (thin)
def preference_json(p) -> dict:
    """Serialize one FacultyPreference row (authoritative persisted state)."""
    days = parse_days(getattr(p, "days", None))
    return {"id": p.id, "faculty_id": p.faculty_id, "kind": p.kind,
            "days": days,
            "days_display": ",".join(days),
            "start_period": p.start_period, "end_period": p.end_period,
            "weight": p.weight, "is_hard": bool(getattr(p, "is_hard", False)),
            "enabled": bool(getattr(p, "enabled", True))}


def _config_context(db):
    """Working days + period count from Config (raises PreferenceError)."""
    from backend.models import Config
    cfg = Config.query.first()
    if cfg is None:
        raise PreferenceError(
            "No scheduling configuration found.",
            [_fail("PREFERENCE_INVALID",
                   "No scheduling configuration found.", {})])
    return cfg.day_list(), len(cfg.period_list())


def list_for_faculty(db, faculty_id) -> list:
    """All preference rows for one faculty (ordered by id)."""
    from backend.models import Faculty, FacultyPreference
    try:
        fid = int(faculty_id)
    except (TypeError, ValueError):
        raise PreferenceError(
            f"Faculty {faculty_id!r} does not exist.",
            [_fail("UNKNOWN_FACULTY",
                   f"Faculty {faculty_id!r} does not exist.",
                   {"faculty_id": faculty_id})])
    fac = Faculty.query.get(fid)
    if fac is None:
        raise PreferenceError(
            f"Faculty {fid} does not exist.",
            [_fail("UNKNOWN_FACULTY",
                   f"Faculty {fid} does not exist.",
                   {"faculty_id": fid})])
    return FacultyPreference.query.filter_by(
        faculty_id=fid).order_by(FacultyPreference.id).all()


def create_preference(db, faculty_id, data):
    """Validate + persist one preference (no schedule mutation)."""
    from backend.models import Faculty, FacultyPreference
    try:
        fid = int(faculty_id)
    except (TypeError, ValueError):
        raise PreferenceError(
            f"Faculty {faculty_id!r} does not exist.",
            [_fail("UNKNOWN_FACULTY",
                   f"Faculty {faculty_id!r} does not exist.",
                   {"faculty_id": faculty_id})])
    if Faculty.query.get(fid) is None:
        raise PreferenceError(
            f"Faculty {fid} does not exist.",
            [_fail("UNKNOWN_FACULTY",
                   f"Faculty {fid} does not exist.",
                   {"faculty_id": fid})])
    working_days, num_periods = _config_context(db)
    clean = validate_preference_payload(data, working_days, num_periods)
    row = FacultyPreference(
        faculty_id=fid, kind=clean.kind,
        days=",".join(clean.days) if clean.days else None,
        start_period=clean.start_period, end_period=clean.end_period,
        weight=clean.weight, is_hard=False, enabled=clean.enabled)
    try:
        db.session.add(row)
        db.session.flush()
        db.session.commit()
        db.session.refresh(row)
    except PreferenceError:
        db.session.rollback()
        raise
    except Exception:  # noqa: BLE001 — rollback must cover any DB error
        db.session.rollback()
        raise PreferenceError(
            "Could not save preference.",
            [_fail("PREFERENCE_INVALID",
                   "Could not save preference.",
                   {"faculty_id": fid})])
    return row


def update_preference(db, preference_id, data):
    """Partial update: overlay provided fields, re-validate merged state."""
    from backend.models import FacultyPreference
    try:
        pid = int(preference_id)
    except (TypeError, ValueError):
        raise PreferenceError(
            f"Preference {preference_id!r} does not exist.",
            [_fail("UNKNOWN_PREFERENCE",
                   f"Preference {preference_id!r} does not exist.",
                   {"preference_id": preference_id})])
    row = FacultyPreference.query.get(pid)
    if row is None:
        raise PreferenceError(
            f"Preference {pid} does not exist.",
            [_fail("UNKNOWN_PREFERENCE",
                   f"Preference {pid} does not exist.",
                   {"preference_id": pid})])
    working_days, num_periods = _config_context(db)
    data = dict(data or {})
    current = {"kind": row.kind,
               "days": parse_days(row.days),
               "start_period": row.start_period,
               "end_period": row.end_period,
               "weight": row.weight,
               "enabled": bool(row.enabled),
               "is_hard": bool(row.is_hard)}
    # Clearing a period bound: explicit null removes it (needed to morph
    # TIME_WINDOW -> DAY_OFF_PREFERENCE and vice versa).
    for key in ("kind", "days", "start_period", "end_period",
                "weight", "enabled", "is_hard"):
        if key in data:
            current[key] = data[key]
    clean = validate_preference_payload(current, working_days, num_periods)
    try:
        row.kind = clean.kind
        row.days = ",".join(clean.days) if clean.days else None
        row.start_period = clean.start_period
        row.end_period = clean.end_period
        row.weight = clean.weight
        row.is_hard = False
        row.enabled = clean.enabled
        db.session.flush()
        db.session.commit()
        db.session.refresh(row)
    except PreferenceError:
        db.session.rollback()
        raise
    except Exception:  # noqa: BLE001 — rollback must cover any DB error
        db.session.rollback()
        raise PreferenceError(
            "Could not save preference.",
            [_fail("PREFERENCE_INVALID",
                   "Could not save preference.",
                   {"preference_id": pid})])
    return row


def delete_preference(db, preference_id):
    """Delete one preference row (never touches schedule rows)."""
    from backend.models import FacultyPreference
    try:
        pid = int(preference_id)
    except (TypeError, ValueError):
        raise PreferenceError(
            f"Preference {preference_id!r} does not exist.",
            [_fail("UNKNOWN_PREFERENCE",
                   f"Preference {preference_id!r} does not exist.",
                   {"preference_id": pid})])
    row = FacultyPreference.query.get(pid)
    if row is None:
        raise PreferenceError(
            f"Preference {pid} does not exist.",
            [_fail("UNKNOWN_PREFERENCE",
                   f"Preference {pid} does not exist.",
                   {"preference_id": pid})])
    try:
        db.session.delete(row)
        db.session.commit()
    except Exception:  # noqa: BLE001 — rollback must cover any DB error
        db.session.rollback()
        raise PreferenceError(
            "Could not delete preference.",
            [_fail("PREFERENCE_INVALID",
                   "Could not delete preference.",
                   {"preference_id": pid})])
    return pid


def query_scheduler_rows(db) -> list:
    """All enabled preference rows for the scheduler (legacy-safe).

    Returns [] when the table is absent (pre-6C database) instead of
    raising, mirroring the preferred-room query in api_routes.
    """
    try:
        from backend.models import FacultyPreference
        return FacultyPreference.query.filter_by(enabled=True).all()
    except Exception:
        return []
