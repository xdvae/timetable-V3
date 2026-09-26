"""
Phase 6H.3 — Faculty swapping (domain service).

Atomic operation: exchange the faculties of two TeachingAssignments
(``A.faculty_id ↔ B.faculty_id``) while keeping every existing
ScheduledClass placement exactly where it is (day/start/length/room/run/
lock/slot preserved — faculty is derived through the assignment, so no
ScheduledClass column changes and no schedule regeneration occurs).

Flow (same proven pattern as manual_edits.py / faculty_reassignment.py):

    validate A under Bob + B under Alice (no writes)
        -> mutate both faculty_id values
        -> flush() once
        -> rebuild snapshot + re-verify both sides
        -> commit()  (any failure -> rollback, DB byte-identical)

A partially applied swap (A moved, B not) is never allowed.

Guards (checked before any occupancy validation):

* missing A / B -> UNKNOWN_ASSIGNMENT (raised; future API maps to 404);
* same assignment id -> INVALID_SWAP (raised; swap(A, A) is meaningless
  and must not be treated as a noop);
* same faculty on both sides -> ok noop (no write, mirrors 6H.2);
* locked ScheduledClass rows or LockedBlock rows on EITHER side ->
  LOCKED_BLOCK (raised; never auto-updates/unlocks/deletes locks);
* normal <-> specialization mix -> SPECIALIZATION_SWAP (raised; 6H
  supports normal<->normal and spec<->spec only).

Placement validation (all classes on both sides, fail-closed):

* one shared snapshot minus ALL classes of A and B (neither side
  conflicts with itself, and A/B never falsely conflict with each other
  merely for overlapping in time);
* normal assignments use schedule_validator.validate_candidate;
* specialization assignments use
  schedule_validator.validate_specialization_candidate per synchronized
  slot (sync itself is never modified);
* H12 consecutive-teaching is checked for each target faculty over
  (its remaining occupancy + incoming classes);
* geometry/room/HN1 rules run as safety checks through the shared layer.

weekly_max_hours stays a soft warning per faculty (like assignment
creation and 6H.2), never a blocker. Because a swap moves load both
ways, both resulting loads are computed as
``resulting = current - outgoing + incoming``.

Only two genuinely new codes are introduced (both documented here):

* INVALID_SWAP — the swap request itself is malformed (same assignment
  id twice) or a persistence fallback with no rule failure to report.
  No existing code represents "not a valid swap".
* SPECIALIZATION_SWAP — a normal assignment and a specialization
  assignment were asked to exchange faculties. No existing
  SPECIALIZATION_* code means "cross-type swap forbidden"
  (SYNC/OVERLAP/CAPACITY/ENROLLMENT all describe different conditions).

This module never imports Flask/HTTP code and never calls
reassign_faculty() sequentially (that would commit one side before
validating the other). API mapping to ApiError lives in a future phase
(6H.4).
"""
from dataclasses import dataclass, field
from typing import List, Optional

from backend import schedule_rules as rules
from backend import schedule_validator as sv
from backend import faculty_reassignment as fr


class FacultySwapError(Exception):
    """Raised when a faculty swap fails validation or persistence.

    Carries ``failures``: a list of schedule_rules.RuleResult with stable
    UPPER_SNAKE codes and structured ``details`` (including ``swap_side``
    ``"A"``/``"B"`` where a placement failure belongs to one side).
    """

    def __init__(self, message, failures=None):
        super().__init__(message)
        self.message = message
        self.failures = list(failures or [])

    def to_payload(self):
        primary = self.failures[0] if self.failures else None
        return {
            "error": self.message,
            "code": primary.code if primary else "INVALID_SWAP",
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
class SwapValidationResult:
    """Reusable outcome shared by dry-run validation and the mutation.

    ``faculty_a_id``/``faculty_b_id`` are the CURRENT faculties (A teaches
    faculty_a, B teaches faculty_b); after a successful swap A teaches
    faculty_b and B teaches faculty_a. ``warnings`` is the (possibly
    empty) list of soft weekly-load notices.
    """

    ok: bool
    failures: List = field(default_factory=list)
    assignment_a_id: Optional[int] = None
    assignment_b_id: Optional[int] = None
    faculty_a_id: Optional[int] = None
    faculty_b_id: Optional[int] = None
    scheduled_class_ids_a: List = field(default_factory=list)
    scheduled_class_ids_b: List = field(default_factory=list)
    noop: bool = False
    warnings: List = field(default_factory=list)


def _coerce_id(value, side):
    """Coerce an assignment id to int or raise a missing-resource error."""
    try:
        return int(value)
    except (TypeError, ValueError):
        raise FacultySwapError(
            f"Teaching assignment {value!r} does not exist.",
            [_fail("UNKNOWN_ASSIGNMENT",
                   f"Teaching assignment {value!r} does not exist.",
                   {"assignment_id": value, "swap_side": side})])


def _tag_side(failures, *, side, assignment_id, target_faculty_id):
    """Stamp placement failures with which swap side they belong to."""
    out = []
    for res in failures:
        details = dict(res.details)
        details.setdefault("swap_side", side)
        details.setdefault("assignment_id", assignment_id)
        details.setdefault("target_faculty_id", target_faculty_id)
        out.append(rules.RuleResult(ok=False, code=res.code,
                                    message=res.message, details=details))
    return out


def _locked_state(assignment):
    """(locked_class_ids, locked_block_ids) for one assignment."""
    from backend.models import LockedBlock, ScheduledClass
    classes = ScheduledClass.query.filter_by(
        assignment_id=assignment.id).all()
    locked_class_ids = [c.id for c in classes
                        if bool(getattr(c, "is_locked", False))
                        or getattr(c, "locked_block_id", None) is not None]
    try:
        locked_block_ids = [lb.id for lb in LockedBlock.query.filter_by(
            assignment_id=assignment.id).all()]
    except Exception:
        locked_block_ids = []
    return locked_class_ids, locked_block_ids


def _check_locked_or_raise(assignment_a, assignment_b):
    """Reject the whole swap when EITHER side is locked."""
    for side, assignment in (("A", assignment_a), ("B", assignment_b)):
        class_ids, block_ids = _locked_state(assignment)
        if class_ids or block_ids:
            raise FacultySwapError(
                f"Teaching assignment {assignment.id} has locked placements "
                f"and cannot be swapped.",
                [rules.RuleResult(
                    ok=False, code="LOCKED_BLOCK",
                    message=f"Teaching assignment {assignment.id} (swap side "
                            f"{side}) has locked placements and cannot be "
                            f"swapped (locked classes {class_ids}, locked "
                            f"blocks {block_ids}).",
                    details={"swap_side": side,
                             "assignment_id": assignment.id,
                             "locked_class_ids": class_ids,
                             "locked_block_ids": block_ids,
                             "reason": "Locked placements pin the assignment "
                                       "faculty; swapping would make the "
                                       "lock inconsistent."})])


def _swap_load_warnings(db, assignment_a, assignment_b,
                        faculty_a_id, faculty_b_id):
    """Soft weekly-load notices for both faculties (never blockers).

    resulting = current - outgoing + incoming per faculty, following the
    6H.2 warning shape (extended with previous/outgoing/incoming loads).
    Returns a (possibly empty) list.
    """
    from backend.models import Faculty, TeachingAssignment
    from sqlalchemy import func
    warnings = []
    loads = dict(db.session.query(
        TeachingAssignment.faculty_id,
        func.coalesce(func.sum(TeachingAssignment.periods_per_week), 0),
    ).group_by(TeachingAssignment.faculty_id).all())
    pa = getattr(assignment_a, "periods_per_week", 0) or 0
    pb = getattr(assignment_b, "periods_per_week", 0) or 0
    for fid, outgoing, incoming in ((faculty_a_id, pa, pb),
                                    (faculty_b_id, pb, pa)):
        faculty = Faculty.query.get(fid)
        if faculty is None:
            continue
        current = loads.get(fid, 0) or 0
        resulting = (current or 0) - (outgoing or 0) + (incoming or 0)
        max_hours = getattr(faculty, "weekly_max_hours", None)
        if max_hours and resulting > max_hours:
            warnings.append({
                "exceeded": True,
                "faculty_id": fid,
                "faculty_name": faculty.name,
                "previous_load": int(current or 0),
                "assignment_load_out": int(outgoing or 0),
                "assignment_load_in": int(incoming or 0),
                "resulting_load": int(resulting),
                "max_hours": int(max_hours),
                "message": (f"{faculty.name}'s weekly load would be "
                            f"{resulting} hrs (max {max_hours} hrs)."),
            })
    return warnings


def _faculty_name(db, faculty_id):
    from backend.models import Faculty
    faculty = Faculty.query.get(faculty_id)
    return (faculty.name if faculty else "?") or "?"


# ------------------------------------------------------- validation
def validate_faculty_swap(db, assignment_a_id, assignment_b_id):
    """Dry-run validation shared by the future API and the mutation.

    No database mutation. Returns a SwapValidationResult.
    Raises FacultySwapError for missing resources, same-id requests,
    locked assignments, and normal<->specialization mixes.
    """
    from backend.models import ScheduledClass, TeachingAssignment
    assignment_a_id = _coerce_id(assignment_a_id, "A")
    assignment_b_id = _coerce_id(assignment_b_id, "B")

    assignment_a = TeachingAssignment.query.get(assignment_a_id)
    if assignment_a is None:
        raise FacultySwapError(
            f"Teaching assignment {assignment_a_id} does not exist.",
            [_fail("UNKNOWN_ASSIGNMENT",
                   f"Teaching assignment {assignment_a_id} does not exist.",
                   {"assignment_id": assignment_a_id, "swap_side": "A"})])
    assignment_b = TeachingAssignment.query.get(assignment_b_id)
    if assignment_b is None:
        raise FacultySwapError(
            f"Teaching assignment {assignment_b_id} does not exist.",
            [_fail("UNKNOWN_ASSIGNMENT",
                   f"Teaching assignment {assignment_b_id} does not exist.",
                   {"assignment_id": assignment_b_id, "swap_side": "B"})])

    if assignment_a.id == assignment_b.id:
        raise FacultySwapError(
            f"Cannot swap teaching assignment {assignment_a.id} with itself.",
            [_fail("INVALID_SWAP",
                   f"Cannot swap teaching assignment {assignment_a.id} "
                   f"with itself: two distinct assignments are required.",
                   {"assignment_a_id": assignment_a.id,
                    "assignment_b_id": assignment_b.id})])

    faculty_a_id = getattr(assignment_a, "faculty_id", None)
    faculty_b_id = getattr(assignment_b, "faculty_id", None)
    classes_a = ScheduledClass.query.filter_by(
        assignment_id=assignment_a.id).order_by(ScheduledClass.id).all()
    classes_b = ScheduledClass.query.filter_by(
        assignment_id=assignment_b.id).order_by(ScheduledClass.id).all()

    if faculty_a_id == faculty_b_id:
        return SwapValidationResult(
            ok=True, failures=[],
            assignment_a_id=assignment_a.id,
            assignment_b_id=assignment_b.id,
            faculty_a_id=faculty_a_id, faculty_b_id=faculty_b_id,
            scheduled_class_ids_a=[c.id for c in classes_a],
            scheduled_class_ids_b=[c.id for c in classes_b],
            noop=True, warnings=[])

    _check_locked_or_raise(assignment_a, assignment_b)

    spec_a = getattr(assignment_a, "specialization_id", None)
    spec_b = getattr(assignment_b, "specialization_id", None)
    if (spec_a is not None) != (spec_b is not None):
        raise FacultySwapError(
            f"Cannot swap normal assignment {assignment_a.id} with "
            f"specialization assignment {assignment_b.id}.",
            [_fail("SPECIALIZATION_SWAP",
                   f"Cannot swap normal assignment {assignment_a.id} with "
                   f"specialization assignment {assignment_b.id}: 6H "
                   f"supports normal<->normal and "
                   f"specialization<->specialization swaps only.",
                   {"assignment_a_id": assignment_a.id,
                    "assignment_b_id": assignment_b.id,
                    "specialization_a_id": spec_a,
                    "specialization_b_id": spec_b})])

    try:
        snap, _cfg = fr._load_snapshot(db)
    except fr.FacultyReassignmentError as exc:
        raise FacultySwapError(exc.message, exc.failures)

    # One shared snapshot minus BOTH assignments' classes: neither side
    # conflicts with itself, and A/B never falsely conflict with each
    # other merely for overlapping in time (they take different target
    # faculties).
    slim = snap
    for cid in [c.id for c in classes_a] + [c.id for c in classes_b]:
        slim = sv.snapshot_without(slim, cid)

    failures = []
    failures.extend(_tag_side(
        fr._validate_classes(
            slim, snap, assignment=assignment_a,
            new_faculty_id=faculty_b_id,
            faculty_name=_faculty_name(db, faculty_b_id),
            assignment_classes=classes_a),
        side="A", assignment_id=assignment_a.id,
        target_faculty_id=faculty_b_id))
    failures.extend(_tag_side(
        fr._validate_classes(
            slim, snap, assignment=assignment_b,
            new_faculty_id=faculty_a_id,
            faculty_name=_faculty_name(db, faculty_a_id),
            assignment_classes=classes_b),
        side="B", assignment_id=assignment_b.id,
        target_faculty_id=faculty_a_id))
    failures.extend(_tag_side(
        fr._check_consecutive(
            slim, snap, new_faculty_id=faculty_b_id,
            assignment_classes=classes_a, assignment_id=assignment_a.id),
        side="A", assignment_id=assignment_a.id,
        target_faculty_id=faculty_b_id))
    failures.extend(_tag_side(
        fr._check_consecutive(
            slim, snap, new_faculty_id=faculty_a_id,
            assignment_classes=classes_b, assignment_id=assignment_b.id),
        side="B", assignment_id=assignment_b.id,
        target_faculty_id=faculty_a_id))

    warnings = _swap_load_warnings(db, assignment_a, assignment_b,
                                   faculty_a_id, faculty_b_id)

    return SwapValidationResult(
        ok=not failures, failures=failures,
        assignment_a_id=assignment_a.id, assignment_b_id=assignment_b.id,
        faculty_a_id=faculty_a_id, faculty_b_id=faculty_b_id,
        scheduled_class_ids_a=[c.id for c in classes_a],
        scheduled_class_ids_b=[c.id for c in classes_b],
        noop=False, warnings=warnings)


def _verify_post_swap(db, assignment_a_id, assignment_b_id,
                       faculty_a_id, faculty_b_id):
    """Rebuild the snapshot after flush and re-verify both sides.

    Bypasses the same-faculty noop shortcut so placements are genuinely
    re-checked. Separated for testability: swap tests patch this to force
    a post-flush failure and prove rollback.
    """
    from backend.models import ScheduledClass, TeachingAssignment
    assignment_a = TeachingAssignment.query.get(assignment_a_id)
    assignment_b = TeachingAssignment.query.get(assignment_b_id)
    if assignment_a is None or assignment_b is None:
        return [_fail("UNKNOWN_ASSIGNMENT",
                      "Faculty swap verification failed after update.",
                      {"assignment_a_id": assignment_a_id,
                       "assignment_b_id": assignment_b_id})]
    if getattr(assignment_a, "faculty_id", None) != faculty_b_id \
            or getattr(assignment_b, "faculty_id", None) != faculty_a_id:
        return [_fail("INVALID_SWAP",
                      "Faculty swap verification failed after update.",
                      {"assignment_a_id": assignment_a_id,
                       "assignment_b_id": assignment_b_id})]
    try:
        snap, _cfg = fr._load_snapshot(db)
    except fr.FacultyReassignmentError as exc:
        return list(exc.failures)
    classes_a = ScheduledClass.query.filter_by(
        assignment_id=assignment_a.id).order_by(ScheduledClass.id).all()
    classes_b = ScheduledClass.query.filter_by(
        assignment_id=assignment_b.id).order_by(ScheduledClass.id).all()
    slim = snap
    for cid in [c.id for c in classes_a] + [c.id for c in classes_b]:
        slim = sv.snapshot_without(slim, cid)
    failures = []
    failures.extend(_tag_side(
        fr._validate_classes(
            slim, snap, assignment=assignment_a,
            new_faculty_id=faculty_b_id,
            faculty_name=_faculty_name(db, faculty_b_id),
            assignment_classes=classes_a),
        side="A", assignment_id=assignment_a.id,
        target_faculty_id=faculty_b_id))
    failures.extend(_tag_side(
        fr._validate_classes(
            slim, snap, assignment=assignment_b,
            new_faculty_id=faculty_a_id,
            faculty_name=_faculty_name(db, faculty_a_id),
            assignment_classes=classes_b),
        side="B", assignment_id=assignment_b.id,
        target_faculty_id=faculty_a_id))
    failures.extend(_tag_side(
        fr._check_consecutive(
            slim, snap, new_faculty_id=faculty_b_id,
            assignment_classes=classes_a, assignment_id=assignment_a.id),
        side="A", assignment_id=assignment_a.id,
        target_faculty_id=faculty_b_id))
    failures.extend(_tag_side(
        fr._check_consecutive(
            slim, snap, new_faculty_id=faculty_a_id,
            assignment_classes=classes_b, assignment_id=assignment_b.id),
        side="B", assignment_id=assignment_b.id,
        target_faculty_id=faculty_a_id))
    return failures


# ------------------------------------------------------- mutation
def swap_faculty(db, assignment_a_id, assignment_b_id):
    """Atomically exchange the faculties of two teaching assignments.

    Validates both sides first (no writes), then sets both faculty_id
    values, flushes once, re-verifies the complete swapped state against
    a freshly rebuilt snapshot, and commits. Any failure rolls back
    leaving the database byte-identical — never A-moved/B-not.
    Returns (assignment_a, assignment_b, SwapValidationResult).
    """
    from backend.models import TeachingAssignment
    result = validate_faculty_swap(db, assignment_a_id, assignment_b_id)
    if not result.ok:
        raise FacultySwapError(
            f"Faculty swap invalid: {result.failures[0].message}",
            result.failures)
    if result.noop:
        assignment_a = TeachingAssignment.query.get(result.assignment_a_id)
        assignment_b = TeachingAssignment.query.get(result.assignment_b_id)
        return assignment_a, assignment_b, result
    try:
        assignment_a = TeachingAssignment.query.get(result.assignment_a_id)
        assignment_b = TeachingAssignment.query.get(result.assignment_b_id)
        assignment_a.faculty_id = result.faculty_b_id
        assignment_b.faculty_id = result.faculty_a_id
        db.session.flush()
        # Post-flush verification against rebuilt state (still uncommitted:
        # a failure here rolls back both sides together).
        verify_failures = _verify_post_swap(
            db, result.assignment_a_id, result.assignment_b_id,
            result.faculty_a_id, result.faculty_b_id)
        if verify_failures:
            db.session.rollback()
            raise FacultySwapError(
                "Faculty swap verification failed after update.",
                (verify_failures or [_fail(
                    "INVALID_SWAP",
                    "Faculty swap verification failed after update.",
                    {"assignment_a_id": result.assignment_a_id,
                     "assignment_b_id": result.assignment_b_id})]))
        db.session.commit()
        db.session.refresh(assignment_a)
        db.session.refresh(assignment_b)
        return assignment_a, assignment_b, result
    except FacultySwapError:
        db.session.rollback()
        raise
    except Exception:  # noqa: BLE001 — rollback must cover any DB error
        db.session.rollback()
        raise FacultySwapError(
            f"Could not swap assignments {assignment_a_id} and "
            f"{assignment_b_id}.",
            [_fail("INVALID_SWAP",
                   f"Could not swap assignments {assignment_a_id} and "
                   f"{assignment_b_id}.",
                   {"assignment_a_id": assignment_a_id,
                    "assignment_b_id": assignment_b_id})])
