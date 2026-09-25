"""
Phase 6H.2 — Faculty reassignment (domain service).

Atomic operation: change one TeachingAssignment's faculty
(``assignment.faculty_id = new_faculty_id``) while keeping every existing
ScheduledClass placement exactly where it is (day/start/length/room/run/
lock/slot preserved — faculty is derived through the assignment, so no
ScheduledClass column changes and no schedule regeneration occurs).

Flow (mirrors manual_edits.py / locked_blocks.py):

    validate (no writes)
        -> mutate faculty_id
        -> flush()
        -> rebuild snapshot + re-verify
        -> commit()  (any failure -> rollback, DB byte-identical)

Guards (checked before any occupancy validation):

* missing assignment / faculty -> UNKNOWN_ASSIGNMENT / UNKNOWN_FACULTY
  (raised; future API maps to 404);
* same faculty -> ok noop (no write);
* locked ScheduledClass rows or LockedBlock rows for the assignment ->
  LOCKED_BLOCK (raised; never auto-updates/unlocks/deletes locks).

Placement validation (all classes, fail-closed):

* every ScheduledClass of the assignment is validated against the new
  faculty with the assignment's own occupancy removed (never conflicts
  with itself);
* normal assignments use schedule_validator.validate_candidate;
* specialization assignments use
  schedule_validator.validate_specialization_candidate per synchronized
  slot (sync itself is never modified);
* H12 consecutive-teaching is checked over
  (existing new-faculty occupancy + reassigned classes);
* geometry/room/HN1 rules run as safety checks through the shared layer.

weekly_max_hours stays a soft warning (like assignment creation), never
a blocker.

This module never imports Flask/HTTP code. API mapping to ApiError lives
in a future phase (6H.4).
"""
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import List, Optional

from backend import schedule_rules as rules
from backend import schedule_validator as sv


class FacultyReassignmentError(Exception):
    """Raised when a faculty reassignment fails validation or persistence.

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
            "code": primary.code if primary else "REASSIGNMENT_INVALID",
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
class ReassignmentValidationResult:
    """Reusable outcome shared by dry-run validation and the mutation.

    ``ok`` is True only when the reassignment can be applied.
    ``noop`` marks a same-faculty request (success without any write).
    ``warning`` carries the soft weekly-load notice (None when within max).
    """

    ok: bool
    failures: List = field(default_factory=list)
    assignment_id: Optional[int] = None
    current_faculty_id: Optional[int] = None
    new_faculty_id: Optional[int] = None
    scheduled_class_ids: List = field(default_factory=list)
    noop: bool = False
    warning: Optional[dict] = None


# ------------------------------------------------------- snapshot load
def _load_snapshot(db):
    """Build a schedule_validator snapshot from current ORM rows.

    Mirrors manual_edits._load_snapshot (practical assignments wrapped
    with resolved lab-group context; specialization assignments pass
    through). Read-only: issues SELECTs only.
    """
    from backend.models import (Config, Faculty, LabGroup, Room, Section,
                                Specialization, SpecializationMembership,
                                TeachingAssignment, ScheduledClass)
    cfg = Config.query.first()
    if cfg is None:
        raise FacultyReassignmentError(
            "No scheduling configuration found.",
            [_fail("REASSIGNMENT_INVALID",
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


def _coerce_id(value, kind):
    """Coerce an id to int or raise a missing-resource error."""
    try:
        return int(value)
    except (TypeError, ValueError):
        if kind == "assignment":
            raise FacultyReassignmentError(
                f"Teaching assignment {value!r} does not exist.",
                [_fail("UNKNOWN_ASSIGNMENT",
                       f"Teaching assignment {value!r} does not exist.",
                       {"assignment_id": value})])
        raise FacultyReassignmentError(
            f"Faculty {value!r} does not exist.",
            [_fail("UNKNOWN_FACULTY",
                   f"Faculty {value!r} does not exist.",
                   {"faculty_id": value})])


def _find_conflicting(slim, *, room_id, faculty_id, group_key,
                      parent_section_key, day, start, length):
    """First class in the slim snapshot conflicting with the candidate.

    Mirrors manual_edits._find_conflicting so FACULTY_CONFLICT /
    ROOM_CONFLICT failures carry actionable conflicting-class context.
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
            parent_section_key, day, start, length, assignment_id,
            scheduled_class_id):
    """Add conflicting_class_id/assignment context to occupancy failures."""
    out = []
    for res in failures:
        code = res.code
        details = dict(res.details)
        if code == "GROUP_CONFLICT":
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
            details.setdefault("assignment_id", assignment_id)
            details.setdefault("scheduled_class_id", scheduled_class_id)
            details.setdefault("faculty_id", faculty_id)
            details.setdefault("day", day)
            out.append(rules.RuleResult(ok=False, code=code,
                                        message=res.message,
                                        details=details))
        else:
            details.setdefault("assignment_id", assignment_id)
            details.setdefault("scheduled_class_id", scheduled_class_id)
            details.setdefault("faculty_id", faculty_id)
            out.append(rules.RuleResult(ok=False, code=code,
                                        message=res.message,
                                        details=details))
    return out


def _weekly_load_warning(db, new_faculty_id, assignment_periods):
    """Soft weekly-load notice (never a blocker).

    Mirrors the assignment-creation convention: load beyond
    Faculty.weekly_max_hours is a warning, not a rejection.
    Returns None when within max or when no max is configured.
    """
    from backend.models import Faculty, TeachingAssignment
    from sqlalchemy import func
    faculty = Faculty.query.get(new_faculty_id)
    if faculty is None:
        return None
    current = db.session.query(
        func.coalesce(func.sum(TeachingAssignment.periods_per_week), 0)
    ).filter_by(faculty_id=new_faculty_id).scalar() or 0
    resulting = (current or 0) + (assignment_periods or 0)
    max_hours = getattr(faculty, "weekly_max_hours", None)
    if max_hours and resulting > max_hours:
        return {
            "exceeded": True,
            "faculty_id": new_faculty_id,
            "faculty_name": faculty.name,
            "current_load": int(current or 0),
            "assignment_periods": int(assignment_periods or 0),
            "resulting_load": int(resulting),
            "max_hours": int(max_hours),
            "message": (f"{faculty.name}'s weekly load would be "
                        f"{resulting} hrs (max {max_hours} hrs)."),
        }
    return None


def _validate_classes(slim, snap, *, assignment, new_faculty_id,
                      faculty_name, assignment_classes):
    """Validate every existing class of the assignment under new faculty.

    ``slim`` excludes all of the assignment's own classes (no self
    conflict). Normal assignments use validate_candidate; specialization
    assignments use validate_specialization_candidate per slot. Returns
    the accumulated failing RuleResults (empty == valid).
    """
    failures = []
    is_spec = getattr(assignment, "specialization_id", None) is not None
    if is_spec:
        spec_id = assignment.specialization_id
        sinfo = slim.spec_info.get(spec_id, {}) or snap.spec_info.get(spec_id, {})
        section_ids = list(sinfo.get("section_ids", []) or [])
        total = sinfo.get("total_students", 0) or 0
        spec_name = sinfo.get("name", str(spec_id))
        session_type = getattr(assignment, "session_type", "theory")
        for sc in assignment_classes:
            cand = sv.validate_specialization_candidate(
                slim, specialization_id=spec_id, section_ids=section_ids,
                total_students=total, session_type=session_type,
                faculty_id=new_faculty_id, day=sc.day,
                start_period=sc.start_period, length=sc.length,
                room_id=sc.room_id, specialization_name=spec_name,
                faculty_name=faculty_name)
            cand = _enrich(
                cand, slim, room_id=sc.room_id, faculty_id=new_faculty_id,
                group_key=f"specialization:{spec_id}",
                parent_section_key=None, day=sc.day, start=sc.start_period,
                length=sc.length, assignment_id=assignment.id,
                scheduled_class_id=sc.id)
            failures.extend(cand)
        return failures
    info = snap.assignments.get(assignment.id) or slim.assignments.get(assignment.id)
    if info is None:  # pragma: no cover — defensive; assignment exists
        return [_fail("REASSIGNMENT_INVALID",
                      "Assignment context missing for reassignment.",
                      {"assignment_id": assignment.id})]
    for sc in assignment_classes:
        cand = sv.validate_candidate(
            slim, session_type=info.get("session_type", "theory"),
            group_key=info["group_key"],
            group_label=info.get("group_label", "?"),
            group_size=info.get("group_size", 0),
            faculty_id=new_faculty_id, day=sc.day,
            start_period=sc.start_period, length=sc.length,
            room_id=sc.room_id,
            parent_section_key=info.get("parent_section_key"),
            faculty_name=faculty_name)
        cand = _enrich(
            cand, slim, room_id=sc.room_id, faculty_id=new_faculty_id,
            group_key=info["group_key"],
            parent_section_key=info.get("parent_section_key"),
            day=sc.day, start=sc.start_period, length=sc.length,
            assignment_id=assignment.id, scheduled_class_id=sc.id)
        failures.extend(cand)
    return failures


def _check_consecutive(slim, snap, *, new_faculty_id, assignment_classes,
                       assignment_id):
    """H12: new faculty's day-runs including the reassigned classes."""
    if not snap.max_consecutive or snap.max_consecutive <= 0:
        return []
    failures = []
    by_day = {}
    for sc in assignment_classes:
        by_day.setdefault(sc.day, set()).update(
            rules.covers(sc.start_period, sc.length))
    for day, want in by_day.items():
        occupied = {p for (fid, d, p) in slim.faculty_occ
                    if fid == new_faculty_id and d == day}
        occupied.update(want)
        res = rules.check_faculty_consecutive(
            occupied, snap.max_consecutive,
            faculty_id=new_faculty_id, day=day)
        if not res.ok:
            details = dict(res.details)
            details.update({"assignment_id": assignment_id,
                            "faculty_id": new_faculty_id})
            failures.append(rules.RuleResult(ok=False, code=res.code,
                                             message=res.message,
                                             details=details))
    return failures


# ------------------------------------------------------- validation
def validate_reassignment(db, assignment_id, new_faculty_id):
    """Dry-run validation shared by future API and the mutation.

    No database mutation. Returns a ReassignmentValidationResult.
    Raises FacultyReassignmentError for missing resources and locked
    assignments (non-movable by definition).
    """
    from backend.models import Faculty, LockedBlock, ScheduledClass, TeachingAssignment
    assignment_id = _coerce_id(assignment_id, "assignment")
    new_faculty_id = _coerce_id(new_faculty_id, "faculty")

    assignment = TeachingAssignment.query.get(assignment_id)
    if assignment is None:
        raise FacultyReassignmentError(
            f"Teaching assignment {assignment_id} does not exist.",
            [_fail("UNKNOWN_ASSIGNMENT",
                   f"Teaching assignment {assignment_id} does not exist.",
                   {"assignment_id": assignment_id})])
    faculty = Faculty.query.get(new_faculty_id)
    if faculty is None:
        raise FacultyReassignmentError(
            f"Faculty {new_faculty_id} does not exist.",
            [_fail("UNKNOWN_FACULTY",
                   f"Faculty {new_faculty_id} does not exist.",
                   {"faculty_id": new_faculty_id,
                    "assignment_id": assignment_id})])

    current_faculty_id = getattr(assignment, "faculty_id", None)
    if current_faculty_id == new_faculty_id:
        classes = ScheduledClass.query.filter_by(
            assignment_id=assignment.id).all()
        return ReassignmentValidationResult(
            ok=True, failures=[], assignment_id=assignment.id,
            current_faculty_id=current_faculty_id,
            new_faculty_id=new_faculty_id,
            scheduled_class_ids=[c.id for c in classes], noop=True,
            warning=None)

    # Locked rows make reassignment inconsistent: the pinned placement
    # names the old faculty. Never auto-update/unlock/delete locks.
    locked_classes = ScheduledClass.query.filter_by(
        assignment_id=assignment.id).all()
    locked_class_ids = [c.id for c in locked_classes
                        if bool(getattr(c, "is_locked", False))
                        or getattr(c, "locked_block_id", None) is not None]
    try:
        locked_blocks = LockedBlock.query.filter_by(
            assignment_id=assignment.id).all()
        locked_block_ids = [lb.id for lb in locked_blocks]
    except Exception:
        locked_blocks, locked_block_ids = [], []
    if locked_class_ids or locked_block_ids:
        raise FacultyReassignmentError(
            f"Teaching assignment {assignment.id} has locked placements "
            f"and cannot be reassigned.",
            [rules.RuleResult(
                ok=False, code="LOCKED_BLOCK",
                message=f"Teaching assignment {assignment.id} has locked "
                        f"placements and cannot be reassigned (locked "
                        f"classes {locked_class_ids}, locked blocks "
                        f"{locked_block_ids}).",
                details={"assignment_id": assignment.id,
                         "current_faculty_id": current_faculty_id,
                         "new_faculty_id": new_faculty_id,
                         "locked_class_ids": locked_class_ids,
                         "locked_block_ids": locked_block_ids,
                         "reason": "Locked placements pin the assignment "
                                   "faculty; reassignment would make the "
                                   "lock inconsistent."})])

    snap, _cfg = _load_snapshot(db)
    assignment_classes = ScheduledClass.query.filter_by(
        assignment_id=assignment.id).order_by(ScheduledClass.id).all()
    class_ids = [c.id for c in assignment_classes]

    slim = snap
    for cid in class_ids:
        slim = sv.snapshot_without(slim, cid)

    failures = _validate_classes(
        slim, snap, assignment=assignment, new_faculty_id=new_faculty_id,
        faculty_name=faculty.name or "?", assignment_classes=assignment_classes)
    failures.extend(_check_consecutive(
        slim, snap, new_faculty_id=new_faculty_id,
        assignment_classes=assignment_classes, assignment_id=assignment.id))

    warning = _weekly_load_warning(
        db, new_faculty_id, getattr(assignment, "periods_per_week", 0) or 0)

    return ReassignmentValidationResult(
        ok=not failures, failures=failures, assignment_id=assignment.id,
        current_faculty_id=current_faculty_id, new_faculty_id=new_faculty_id,
        scheduled_class_ids=class_ids, noop=False, warning=warning)


def _verify_post_flush(db, assignment_id, new_faculty_id):
    """Rebuild the snapshot after flush and re-verify (uncommitted).

    Re-runs the placement validation against freshly rebuilt state
    (bypassing the same-faculty noop shortcut, which would otherwise
    skip placement checks). Separated for testability: reassignment
    tests patch this to force a post-flush failure and prove rollback.
    """
    from backend.models import Faculty, ScheduledClass, TeachingAssignment
    assignment = TeachingAssignment.query.get(assignment_id)
    if assignment is None:
        return [_fail("UNKNOWN_ASSIGNMENT",
                      f"Teaching assignment {assignment_id} does not exist.",
                      {"assignment_id": assignment_id})]
    if getattr(assignment, "faculty_id", None) != new_faculty_id:
        return [_fail("REASSIGNMENT_INVALID",
                      "Faculty reassignment verification failed after update.",
                      {"assignment_id": assignment_id,
                       "faculty_id": new_faculty_id})]
    faculty = Faculty.query.get(new_faculty_id)
    faculty_name = (faculty.name if faculty else "?") or "?"
    snap, _cfg = _load_snapshot(db)
    assignment_classes = ScheduledClass.query.filter_by(
        assignment_id=assignment.id).order_by(ScheduledClass.id).all()
    slim = snap
    for cid in [c.id for c in assignment_classes]:
        slim = sv.snapshot_without(slim, cid)
    failures = _validate_classes(
        slim, snap, assignment=assignment, new_faculty_id=new_faculty_id,
        faculty_name=faculty_name, assignment_classes=assignment_classes)
    failures.extend(_check_consecutive(
        slim, snap, new_faculty_id=new_faculty_id,
        assignment_classes=assignment_classes, assignment_id=assignment.id))
    return failures


# ------------------------------------------------------- mutation
def reassign_faculty(db, assignment_id, new_faculty_id):
    """Atomically reassign one teaching assignment to another faculty.

    Validates first (no writes), then sets faculty_id, flushes,
    re-verifies against a freshly rebuilt snapshot, and commits. Any
    failure rolls back leaving the database byte-identical.
    Returns (TeachingAssignment, ReassignmentValidationResult).
    """
    from backend.models import TeachingAssignment
    result = validate_reassignment(db, assignment_id, new_faculty_id)
    if not result.ok:
        raise FacultyReassignmentError(
            f"Faculty reassignment invalid: {result.failures[0].message}",
            result.failures)
    if result.noop:
        assignment = TeachingAssignment.query.get(result.assignment_id)
        return assignment, result
    try:
        assignment = TeachingAssignment.query.get(result.assignment_id)
        assignment.faculty_id = result.new_faculty_id
        db.session.flush()
        # Post-flush verification against rebuilt state (still uncommitted:
        # a failure here rolls back to the original faculty).
        verify_failures = _verify_post_flush(
            db, result.assignment_id, result.new_faculty_id)
        if verify_failures:
            db.session.rollback()
            raise FacultyReassignmentError(
                "Faculty reassignment verification failed after update.",
                (verify_failures or [_fail(
                    "REASSIGNMENT_INVALID",
                    "Faculty reassignment verification failed after update.",
                    {"assignment_id": result.assignment_id})]))
        db.session.commit()
        db.session.refresh(assignment)
        return assignment, result
    except FacultyReassignmentError:
        db.session.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 — rollback must cover any DB error
        db.session.rollback()
        raise FacultyReassignmentError(
            f"Could not reassign assignment {assignment_id}: {exc}",
            [_fail("REASSIGNMENT_INVALID",
                   f"Could not reassign assignment {assignment_id}: {exc}",
                   {"assignment_id": assignment_id,
                    "faculty_id": new_faculty_id})])
