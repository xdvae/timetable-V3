"""
Phase 6G — Manual timetable editing (domain service).

Narrow, atomic operation: move one existing ScheduledClass to another
(day, start_period, room_id) while preserving every hard scheduling
constraint. The move:

* preserves assignment_id, length, run_id, is_locked, slot_id,
  locked_block_id (only day/start/room change);
* never relocates unrelated classes and never reruns CP-SAT;
* validates through the shared layer (schedule_validator +
  schedule_rules) against a snapshot with the moved class removed, so a
  class never conflicts with itself;
* commits only when the candidate is fully valid, otherwise rolls back
  leaving the database byte-identical.

Safeguards (checked before any occupancy validation):

* locked classes (is_locked or locked_block_id set) are immovable
  (LOCKED_BLOCK);
* specialization classes are not independently movable: moving one session
  would break cohort synchronization (SPECIALIZATION_SYNC). Only normal
  section/lab-group classes move in this phase.

This module never imports Flask/HTTP code. API mapping to ApiError lives
in api_routes.py.
"""
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import List, Optional

from backend import schedule_rules as rules
from backend import schedule_validator as sv


class ManualEditError(Exception):
    """Raised when a manual move fails validation or persistence.

    Carries ``failures``: a list of schedule_rules.RuleResult with stable
    UPPER_SNAKE codes and structured ``details``.
    """

    def __init__(self, message, failures=None):
        super().__init__(message)
        self.message = message
        self.failures = list(failures or [])

    def to_payload(self):
        primary = self.failures[0] if self.failures else None
        return {
            "error": self.message,
            "code": primary.code if primary else "MANUAL_EDIT_INVALID",
            "details": primary.details if primary else {},
            "failures": [
                {"code": f.code, "message": f.message, "details": f.details}
                for f in self.failures
            ],
        }


def _fail(code, message, details=None):
    return rules.RuleResult(ok=False, code=code, message=message,
                            details=details or {})


@dataclass
class MoveValidationResult:
    """Reusable outcome shared by dry-run validation and the mutation.

    ``ok`` is True only when the exact requested placement is acceptable.
    ``noop`` marks a same-position request (success without any write).
    ``candidate``/``current`` carry the proposed vs stored placement.
    """
    ok: bool
    failures: List = field(default_factory=list)
    candidate: Optional[dict] = None
    current: Optional[dict] = None
    scheduled_class_id: Optional[int] = None
    noop: bool = False


# ------------------------------------------------------- snapshot load
def _load_snapshot(db):
    """Build a schedule_validator snapshot from current ORM rows.

    Mirrors locked_blocks._snapshot_from_orm (practical assignments are
    wrapped with resolved lab-group context; specialization assignments
    pass through so the conservative section footprint applies).
    Read-only: issues SELECTs only.
    """
    from backend.models import (Config, Faculty, LabGroup, Room, Section,
                                Specialization, SpecializationMembership,
                                TeachingAssignment, ScheduledClass)
    cfg = Config.query.first()
    if cfg is None:
        raise ManualEditError(
            "No scheduling configuration found.",
            [_fail("MANUAL_EDIT_INVALID",
                   "No scheduling configuration found.", {})])
    days = cfg.day_list()
    periods = cfg.period_list()
    num_periods = len(periods)
    break_after = cfg.break_after_periods if cfg.break_after_periods else None

    rooms = Room.query.all()
    faculty_rows = Faculty.query.all()
    sections = Section.query.all()
    lab_groups = LabGroup.query.all()
    assignments = TeachingAssignment.query.all()
    scheduled = ScheduledClass.query.all()
    try:
        specializations = Specialization.query.all()
        memberships = SpecializationMembership.query.all()
    except Exception:
        specializations, memberships = [], []

    sec_by_id = {s.id: s for s in sections}
    lg_by_id = {lg.id: lg for lg in lab_groups}
    wrapped = []
    for a in assignments:
        if getattr(a, "specialization_id", None) is not None:
            wrapped.append(SimpleNamespace(
                id=a.id, faculty_id=getattr(a, "faculty_id", None),
                session_type=getattr(a, "session_type", "theory"),
                section_id=None, lab_group_id=None,
                specialization_id=getattr(a, "specialization_id", None)))
            continue
        stype = getattr(a, "session_type", "theory")
        if stype == "practical" and getattr(a, "lab_group_id", None):
            lg = lg_by_id.get(a.lab_group_id) or getattr(a, "lab_group", None)
            wrapped.append(SimpleNamespace(
                id=a.id, faculty_id=a.faculty_id, session_type=stype,
                section_id=getattr(a, "section_id", None),
                lab_group_id=a.lab_group_id,
                lab_group_name=(getattr(lg, "name", None) or "?"),
                lab_group_size=(getattr(lg, "student_count", 0) or 0),
                lab_group_section_id=getattr(lg, "section_id", None)))
        else:
            sec = sec_by_id.get(getattr(a, "section_id", None))
            wrapped.append(SimpleNamespace(
                id=a.id, faculty_id=a.faculty_id, session_type=stype,
                section_id=getattr(a, "section_id", None),
                lab_group_id=None,
                section_name=(getattr(sec, "name", None)
                              or getattr(a, "section_name", None) or "?"),
                section_size=(getattr(sec, "student_count", None)
                              if getattr(sec, "student_count", None) is not None
                              else (getattr(a, "section_size", 0) or 0))))
    snap = sv.build_snapshot(days, num_periods, break_after,
                             cfg.max_consecutive_teaching,
                             rooms, faculty_rows, lab_groups, sections,
                             wrapped, scheduled,
                             specializations=specializations,
                             memberships=memberships)
    return snap, cfg


def _coerce_int(value, field_name, scheduled_class_id):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ManualEditError(
            f"Invalid {field_name} for manual move of scheduled class "
            f"{scheduled_class_id}: must be a whole number.",
            [_fail("MANUAL_EDIT_INVALID",
                   f"{field_name} must be a whole number.",
                   {"scheduled_class_id": scheduled_class_id,
                    field_name: value})])


def _find_conflicting(slim, *, room_id, faculty_id, group_key,
                      parent_section_key, day, start, length):
    """First class in the slim snapshot conflicting with the candidate.

    Returns (class_id, assignment_id, kind) or (None, None, None). Covers
    room/faculty/group/hierarchy plus the specialization section footprint
    (a normal candidate colliding with synchronized spec occupancy).
    """
    want = set(rules.covers(start, length))
    for cid, cls in slim.classes.items():
        info = slim.assignments.get(cls["assignment_id"])
        if info is None:
            continue
        if cls["day"] != day:
            continue
        if not (set(rules.covers(cls["start_period"], cls["length"])) & want):
            continue
        if cls["room_id"] == room_id:
            return cid, cls["assignment_id"], "room"
        if info.get("faculty_id") == faculty_id:
            return cid, cls["assignment_id"], "faculty"
        if info.get("group_key") == group_key:
            return cid, cls["assignment_id"], "group"
        if parent_section_key and info.get("group_key") == parent_section_key:
            return cid, cls["assignment_id"], "hierarchy"
        if (info.get("parent_section_key")
                and info["parent_section_key"] == group_key):
            return cid, cls["assignment_id"], "hierarchy"
        if group_key.startswith("section:"):
            if info.get("parent_section_key") == group_key:
                return cid, cls["assignment_id"], "hierarchy"
    # Specialization footprint: a spec class occupying the candidate's
    # section at an overlapping period (deduped occupancy cannot name the
    # class, so resolve it here for actionable details).
    sec_id = None
    if group_key.startswith("section:"):
        try:
            sec_id = int(group_key.split(":", 1)[1])
        except (ValueError, IndexError):
            sec_id = None
    elif parent_section_key and parent_section_key.startswith("section:"):
        try:
            sec_id = int(parent_section_key.split(":", 1)[1])
        except (ValueError, IndexError):
            sec_id = None
    if sec_id is not None:
        for cid, cls in slim.classes.items():
            info = slim.assignments.get(cls["assignment_id"])
            if info is None or info.get("spec_id") is None:
                continue
            sinfo = slim.spec_info.get(info["spec_id"], {})
            if sec_id not in (sinfo.get("section_ids", []) or []):
                continue
            if cls["day"] != day:
                continue
            if set(rules.covers(cls["start_period"], cls["length"])) & want:
                return cid, cls["assignment_id"], "specialization"
    return None, None, None


def _enrich(failures, slim, *, room_id, faculty_id, group_key,
            parent_section_key, day, start, length, scheduled_class_id):
    """Add conflicting_class_id/assignment context to occupancy failures."""
    out = []
    for res in failures:
        code = res.code
        details = dict(res.details)
        if code == "GROUP_CONFLICT":
            # Same convention as the locked-block API: surface the student
            # group clash as SECTION_CONFLICT.
            code = "SECTION_CONFLICT"
        if code in ("ROOM_CONFLICT", "FACULTY_CONFLICT",
                    "SECTION_CONFLICT", "SECTION_HIERARCHY_CONFLICT",
                    "SPECIALIZATION_OVERLAP"):
            cid, caid, _kind = _find_conflicting(
                slim, room_id=room_id, faculty_id=faculty_id,
                group_key=group_key,
                parent_section_key=parent_section_key or group_key,
                day=day, start=start, length=length)
            if cid is not None:
                details.setdefault("conflicting_class_id", cid)
                details.setdefault("conflicting_assignment_id", caid)
            details.setdefault("scheduled_class_id", scheduled_class_id)
            details.setdefault("day", day)
            out.append(rules.RuleResult(ok=False, code=code,
                                        message=res.message,
                                        details=details))
        else:
            if "scheduled_class_id" not in details:
                details["scheduled_class_id"] = scheduled_class_id
            out.append(rules.RuleResult(ok=False, code=code,
                                        message=res.message,
                                        details=details))
    return out


# ------------------------------------------------------- validation
def validate_move_candidate(db, scheduled_class_id, *, day, start_period,
                            room_id):
    """Dry-run validation shared by the API validate/move endpoints.

    No database mutation. Returns a MoveValidationResult (ok / failures /
    candidate vs current). Raises ManualEditError for non-movable classes
    (missing, locked, specialization).
    """
    from backend.models import Faculty, ScheduledClass, TeachingAssignment
    sc = ScheduledClass.query.get(scheduled_class_id)
    if sc is None:
        raise ManualEditError(
            f"Scheduled class {scheduled_class_id} does not exist.",
            [_fail("MANUAL_EDIT_INVALID",
                   f"Scheduled class {scheduled_class_id} does not exist.",
                   {"scheduled_class_id": scheduled_class_id})])
    start_period = _coerce_int(start_period, "start_period",
                               scheduled_class_id)
    room_id = _coerce_int(room_id, "room_id", scheduled_class_id)

    current = {"day": sc.day, "start_period": sc.start_period,
               "length": sc.length, "room_id": sc.room_id,
               "assignment_id": sc.assignment_id}
    candidate = {"day": day, "start_period": start_period,
                 "length": sc.length, "room_id": room_id,
                 "assignment_id": sc.assignment_id}

    # Locked rows are immovable (either flag form).
    if bool(getattr(sc, "is_locked", False)) \
            or getattr(sc, "locked_block_id", None) is not None:
        raise ManualEditError(
            f"Scheduled class {scheduled_class_id} is locked and cannot "
            f"be moved.",
            [rules.RuleResult(
                ok=False, code="LOCKED_BLOCK",
                message=f"Scheduled class {scheduled_class_id} is locked "
                        f"and cannot be moved (locked block "
                        f"{getattr(sc, 'locked_block_id', None)}).",
                details={"locked_block_id": getattr(
                    sc, "locked_block_id", None),
                    "scheduled_class_id": scheduled_class_id,
                    "attempted_change": candidate,
                    "current": current,
                    "reason": "Locked classes preserve externally fixed "
                              "placements."})])

    assignment = TeachingAssignment.query.get(sc.assignment_id)
    if assignment is None:
        raise ManualEditError(
            f"Scheduled class {scheduled_class_id} references missing "
            f"assignment {sc.assignment_id}.",
            [_fail("MANUAL_EDIT_INVALID",
                   f"Scheduled class {scheduled_class_id} references "
                   f"missing assignment {sc.assignment_id}.",
                   {"scheduled_class_id": scheduled_class_id,
                    "assignment_id": sc.assignment_id})])
    # Specialization sessions move only as a synchronized cohort (out of
    # scope here); an independent move would desynchronize the cohort.
    # Fail-safe: a row carrying a specialization slot link is treated as
    # specialization-linked even if the assignment link is inconsistent —
    # never silently allow an independent move of a synced row.
    _spec_id = getattr(assignment, "specialization_id", None)
    _slot_id = getattr(sc, "slot_id", None)
    if _spec_id is not None or _slot_id is not None:
        raise ManualEditError(
            f"Scheduled class {scheduled_class_id} belongs to a "
            f"specialization and cannot be moved independently.",
            [_fail("SPECIALIZATION_SYNC",
                   f"Scheduled class {scheduled_class_id} belongs to "
                   f"specialization {_spec_id}: moving "
                   f"one session would break cohort synchronization.",
                   {"scheduled_class_id": scheduled_class_id,
                    "assignment_id": sc.assignment_id,
                    "specialization_id": _spec_id,
                    "slot_id": _slot_id,
                    "attempted_change": candidate,
                    "current": current})])

    # Same-position request: success without touching the database.
    if (day == sc.day and start_period == sc.start_period
            and room_id == sc.room_id):
        return MoveValidationResult(ok=True, failures=[], candidate=candidate,
                                    current=current,
                                    scheduled_class_id=scheduled_class_id,
                                    noop=True)

    snap, _cfg = _load_snapshot(db)
    info = snap.assignments.get(sc.assignment_id)
    if info is None:  # pragma: no cover — defensive; assignment exists above
        raise ManualEditError(
            f"Scheduled class {scheduled_class_id} has no schedulable "
            f"assignment context.",
            [_fail("MANUAL_EDIT_INVALID",
                   "Assignment context missing for manual move.",
                   {"scheduled_class_id": scheduled_class_id,
                    "assignment_id": sc.assignment_id})])
    faculty_row = Faculty.query.get(info.get("faculty_id"))
    faculty_name = faculty_row.name if faculty_row else "?"

    slim = sv.snapshot_without(snap, scheduled_class_id)
    failures = sv.validate_candidate(
        slim, session_type=info.get("session_type", "theory"),
        group_key=info["group_key"], group_label=info.get("group_label", "?"),
        group_size=info.get("group_size", 0),
        faculty_id=info.get("faculty_id"), day=day,
        start_period=start_period, length=sc.length, room_id=room_id,
        parent_section_key=info.get("parent_section_key"),
        faculty_name=faculty_name)
    # Faculty consecutive-teaching limit (H12, stable code
    # FACULTY_CONSECUTIVE) is a day-level rule the per-placement validator
    # leaves to the solver; a manual move must not introduce a violation
    # the audit would flag. Uses the shared schedule_rules helper — no
    # second implementation. (HN1 maps to MAX_TWO_THEORY inside
    # validate_candidate above.)
    if snap.max_consecutive and snap.max_consecutive > 0:
        occupied = {p for (fid, d, p) in slim.faculty_occ
                    if fid == info.get("faculty_id") and d == day}
        occupied.update(rules.covers(start_period, sc.length))
        res = rules.check_faculty_consecutive(
            occupied, snap.max_consecutive,
            faculty_id=info.get("faculty_id"), day=day)
        if not res.ok:
            details = dict(res.details)
            details.update({"scheduled_class_id": scheduled_class_id,
                            "room_id": room_id,
                            "faculty_id": info.get("faculty_id")})
            failures.append(rules.RuleResult(ok=False, code=res.code,
                                             message=res.message,
                                             details=details))
    failures = _enrich(failures, slim, room_id=room_id,
                       faculty_id=info.get("faculty_id"),
                       group_key=info["group_key"],
                       parent_section_key=info.get("parent_section_key"),
                       day=day, start=start_period, length=sc.length,
                       scheduled_class_id=scheduled_class_id)
    return MoveValidationResult(ok=not failures, failures=failures,
                                candidate=candidate, current=current,
                                scheduled_class_id=scheduled_class_id,
                                noop=False)


# ------------------------------------------------------- mutation
def move_scheduled_class(db, scheduled_class_id, *, day, start_period,
                         room_id):
    """Atomically move one scheduled class.

    Validates first (no writes), then updates day/start/room, flushes,
    re-verifies against a freshly rebuilt snapshot, and commits. Any
    failure rolls back leaving the original row exactly unchanged.
    Returns (ScheduledClass, MoveValidationResult). Never moves unrelated
    classes, never reruns the solver, preserves run_id.
    """
    from backend.models import ScheduledClass
    result = validate_move_candidate(
        db, scheduled_class_id, day=day, start_period=start_period,
        room_id=room_id)
    if not result.ok:
        raise ManualEditError(
            f"Manual move invalid: {result.failures[0].message}", result.failures)
    if result.noop:
        sc = ScheduledClass.query.get(scheduled_class_id)
        return sc, result
    try:
        sc = ScheduledClass.query.get(scheduled_class_id)
        sc.day = result.candidate["day"]
        sc.start_period = result.candidate["start_period"]
        sc.room_id = result.candidate["room_id"]
        db.session.flush()
        # Post-flush verification against rebuilt state (still uncommitted:
        # a failure here rolls back to the original placement).
        verify = validate_move_candidate(
            db, scheduled_class_id, day=result.candidate["day"],
            start_period=result.candidate["start_period"],
            room_id=result.candidate["room_id"])
        # validate_move_candidate on the moved row sees a same-position
        # request (noop success) only when the persisted state is
        # self-consistent; anything else means the flush produced an
        # unexpected state.
        if not verify.ok or not verify.noop:
            db.session.rollback()
            raise ManualEditError(
                "Manual move verification failed after update.",
                (verify.failures or [_fail(
                    "MANUAL_EDIT_INVALID",
                    "Manual move verification failed after update.",
                    {"scheduled_class_id": scheduled_class_id})]))
        db.session.commit()
        db.session.refresh(sc)
        return sc, result
    except ManualEditError:
        db.session.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 — rollback must cover any DB error
        db.session.rollback()
        raise ManualEditError(
            f"Could not move scheduled class {scheduled_class_id}: {exc}",
            [_fail("MANUAL_EDIT_INVALID",
                   f"Could not move scheduled class {scheduled_class_id}: "
                   f"{exc}",
                   {"scheduled_class_id": scheduled_class_id})])
