"""
Phase 6E — Locked interdepartment blocks (domain service).

An interdepartment LockedBlock is an externally fixed schedule position
entered BEFORE normal timetable generation. The scheduler treats it as
immutable and builds everything else around it.

Lifecycle (Part 4)::

    TeachingAssignment (+ day/start/length/room)
        -> validate (shared rules, no bypass)
        -> persist LockedBlock + ScheduledClass atomically
           (ScheduledClass.is_locked=True, locked_block_id set)
        -> scheduler sees locked occupancy BEFORE solving
        -> audit detects inconsistencies (read-only)
        -> delete/cancel removes both rows atomically

ScheduledClass remains the timetable source of truth; LockedBlock is
constraint metadata. This module never imports Flask/HTTP code and never
touches specialization / faculty-preference / manual-edit UI behaviour
(later phases).

Structured errors reuse backend.schedule_rules.RuleResult so WHAT / WHY /
conflicting resource / WHERE are always explicit.
"""
from types import SimpleNamespace

from backend import schedule_rules as rules
from backend import schedule_validator as sv

INTERDEPARTMENT_KIND = "interdepartment"
VALID_KINDS = ("interdepartment", "manual_fix", "admin_override")


class LockedBlockError(Exception):
    """Raised when a locked-block create/cancel fails validation.

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
            "code": primary.code if primary else "LOCKED_BLOCK_INVALID",
            "details": primary.details if primary else {},
            "failures": [
                {"code": f.code, "message": f.message, "details": f.details}
                for f in self.failures
            ],
        }


def _fail(code, message, details=None):
    return rules.RuleResult(ok=False, code=code, message=message,
                            details=details or {})


# ------------------------------------------------- assignment description
def describe_assignment(a, section=None, lab_group=None):
    """Plain-dict view of a TeachingAssignment (ORM or duck-typed)."""
    session_type = getattr(a, "session_type", "theory")
    section_id = getattr(a, "section_id", None)
    lab_group_id = getattr(a, "lab_group_id", None)
    faculty_id = getattr(a, "faculty_id", None)
    if session_type == "practical" and lab_group_id is not None:
        lg = lab_group or getattr(a, "lab_group", None)
        parent_id = None
        if lg is not None:
            parent_id = getattr(lg, "section_id", None)
        elif getattr(a, "lab_group_section_id", None) is not None:
            parent_id = a.lab_group_section_id
        return {
            "session_type": session_type,
            "faculty_id": faculty_id,
            "subject_id": getattr(a, "subject_id", None),
            "section_id": section_id,
            "lab_group_id": lab_group_id,
            "group_key": f"labgroup:{lab_group_id}",
            "parent_section_key": f"section:{parent_id}" if parent_id else None,
            "group_label": (getattr(lg, "name", None)
                            or getattr(a, "lab_group_name", None) or "?"),
            "group_size": (getattr(lg, "student_count", None)
                           if getattr(lg, "student_count", None) is not None
                           else (getattr(a, "lab_group_size", 0) or 0)),
        }
    sec_name = (getattr(section, "name", None)
                or getattr(a, "section_name", None) or "?")
    sec_size = (getattr(section, "student_count", None)
                if getattr(section, "student_count", None) is not None
                else (getattr(a, "section_size", 0) or 0))
    return {
        "session_type": session_type,
        "faculty_id": faculty_id,
        "subject_id": getattr(a, "subject_id", None),
        "section_id": section_id,
        "lab_group_id": None,
        "group_key": f"section:{section_id}",
        "parent_section_key": None,
        "group_label": sec_name,
        "group_size": sec_size,
    }


def _snapshot_from_orm(days, num_periods, break_after, max_consecutive,
                       rooms, faculty_rows, sections, lab_groups,
                       assignments, scheduled_classes,
                       specializations=None, memberships=None):
    """Build a schedule_validator snapshot from ORM rows.

    TeachingAssignment ORM rows lack the resolved ``*_name/``*_size``
    helpers build_snapshot wants for practicals, so wrap them with the
    resolved values first (theory falls back to the sections list anyway).
    Phase 6F: specialization assignments (specialization_id set) pass
    through untouched so the validator can apply conservative
    section-occupancy; specializations/memberships build the deduped
    footprint.
    """
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
    return sv.build_snapshot(days, num_periods, break_after, max_consecutive,
                             rooms, faculty_rows, lab_groups, sections,
                             wrapped, scheduled_classes,
                             specializations=specializations,
                             memberships=memberships)


def _find_conflicting_class(snap, *, room_id, faculty_id, group_key,
                            parent_section_key, day, start, length):
    """First existing class id occupying any conflicting cell (or None)."""
    for cid, cls in snap.classes.items():
        info = snap.assignments.get(cls["assignment_id"])
        if info is None:
            continue
        c_periods = set(rules.covers(cls["start_period"], cls["length"]))
        want = set(rules.covers(start, length))
        if cls["day"] != day or not (c_periods & want):
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
        # Whole-section theory vs existing lab practical footprint.
        if group_key.startswith("section:"):
            if cls["day"] == day and info.get("parent_section_key") == group_key:
                return cid, cls["assignment_id"], "hierarchy"
    return None, None, None


# ------------------------------------------------------- pure validation
def validate_locked_candidate(*, day, start_period, length, room,
                              assignment, group, faculty_unavailable,
                              days, num_periods, break_after, snap,
                              existing_locked_periods=0,
                              faculty_name="?",
                              conflicting_lookup=True):
    """Validate one proposed locked placement against shared rules.

    Returns a list of failing RuleResults (empty == valid). Covers the
    Phase 6E minimum: UNKNOWN_DAY, PERIOD_OUT_OF_RANGE, BLOCK_GEOMETRY,
    BREAK_SPAN, ROOM_CONFLICT, ROOM_CAPACITY, ROOM_TYPE_MISMATCH,
    ROOM_EQUIPMENT, FACULTY_CONFLICT, FACULTY_UNAVAILABLE,
    SECTION_CONFLICT, SECTION_HIERARCHY_CONFLICT, MAX_TWO_THEORY,
    ASSIGNMENT_MISMATCH. Never bypasses a hard constraint.
    """
    failures = []
    session_type = group["session_type"]
    group_key = group["group_key"]
    parent_key = group.get("parent_section_key")
    group_label = group.get("group_label", "?")
    group_size = group.get("group_size", 0)
    faculty_id = group.get("faculty_id")

    # Assignment linkage must already be consistent; report mismatch here
    # so direct callers (and the API) get a structured code.
    if assignment is None:
        return [_fail("UNKNOWN_ASSIGNMENT", "Teaching assignment does not exist.",
                      {"assignment_id": None})]
    if group.get("faculty_id") != getattr(assignment, "faculty_id", group.get("faculty_id")):
        failures.append(_fail(
            "ASSIGNMENT_MISMATCH",
            f"Locked faculty {group.get('faculty_id')} does not match "
            f"assignment {assignment.id} faculty "
            f"{getattr(assignment, 'faculty_id', '?')}.",
            {"assignment_id": getattr(assignment, 'id', None),
             "locked_faculty_id": group.get("faculty_id"),
             "assignment_faculty_id": getattr(assignment, "faculty_id", None)}))
    if group.get("subject_id") != getattr(assignment, "subject_id", group.get("subject_id")):
        failures.append(_fail(
            "ASSIGNMENT_MISMATCH",
            f"Locked subject does not match assignment {getattr(assignment, 'id', None)}.",
            {"assignment_id": getattr(assignment, 'id', None),
             "locked_subject_id": group.get("subject_id"),
             "assignment_subject_id": getattr(assignment, "subject_id", None)}))
    # Section / lab-group footprint must match the assignment's group.
    if session_type == "practical":
        if group.get("lab_group_id") != getattr(assignment, "lab_group_id", group.get("lab_group_id")):
            failures.append(_fail(
                "ASSIGNMENT_MISMATCH",
                f"Locked lab group does not match assignment {getattr(assignment, 'id', None)}.",
                {"assignment_id": getattr(assignment, 'id', None)}))
    else:
        if group.get("section_id") != getattr(assignment, "section_id", group.get("section_id")):
            failures.append(_fail(
                "ASSIGNMENT_MISMATCH",
                f"Locked section does not match assignment {getattr(assignment, 'id', None)}.",
                {"assignment_id": getattr(assignment, 'id', None)}))

    # Geometry / day / break (H10/H11/H13).
    res = rules.check_day_known(day, days)
    if not res.ok:
        failures.append(_fail("UNKNOWN_DAY", res.message, res.details))
    res = rules.check_block_geometry(start_period, length, num_periods, group_label)
    if not res.ok:
        # check_block_geometry reports PERIOD_OUT_OF_RANGE; keep that code
        # verbatim (spec lists both PERIOD_OUT_OF_RANGE and geometry).
        failures.append(res)
    if not isinstance(length, int) or length < 1:
        failures.append(_fail(
            "BLOCK_GEOMETRY",
            f"Locked block length must be a positive number of periods (got {length}).",
            {"day": day, "start_period": start_period, "length": length}))
    elif length > num_periods:
        failures.append(_fail(
            "BLOCK_GEOMETRY",
            f"Locked block length {length} exceeds the {num_periods}-period day.",
            {"day": day, "start_period": start_period, "length": length,
             "num_periods": num_periods}))
    res = rules.check_break_geometry(start_period, length, break_after, group_label)
    if not res.ok:
        failures.append(_fail(
            "BREAK_SPAN", res.message,
            {"day": day, "start_period": start_period, "length": length,
             "break_after_periods": break_after}))
    # Demand: the locked periods must fit inside the assignment's weekly
    # periods alongside already-locked periods for the same assignment.
    ppw = getattr(assignment, "periods_per_week", None) or 0
    if isinstance(length, int) and length >= 1 and ppw:
        if existing_locked_periods + length > ppw:
            failures.append(_fail(
                "BLOCK_GEOMETRY",
                f"Locked block length {length} plus already-locked "
                f"{existing_locked_periods} periods exceeds assignment "
                f"{getattr(assignment, 'id', None)} periods/week ({ppw}).",
                {"assignment_id": getattr(assignment, 'id', None),
                 "length": length,
                 "existing_locked_periods": existing_locked_periods,
                 "periods_per_week": ppw}))
    if room is None:
        failures.append(_fail(
            "ROOM_REQUIRED",
            "A locked interdepartment block requires a fixed room "
            "(ScheduledClass.room_id is NOT NULL).",
            {"day": day, "start_period": start_period, "length": length}))
        return failures
    # Room compatibility (H2+H3+H4).
    res = rules.check_room_compatible(
        getattr(room, "room_type", "?"), getattr(room, "capacity", 0) or 0,
        getattr(room, "equipment_count", None), session_type, group_size,
        getattr(room, "name", "?"), group_label)
    if not res.ok:
        failures.append(res)
    # Faculty availability (H9).
    res = rules.check_faculty_available(
        faculty_unavailable or set(), day, start_period, length, faculty_name)
    if not res.ok:
        failures.append(res)
    if failures:
        # Geometry/compatibility failures dominate occupancy detail, but
        # assignment mismatches above are already recorded; still check
        # occupancy so callers see every conflict class at once? No — keep
        # the validator's convention: geometry first. Occupancy follows
        # only when geometry is clean, except mismatches already appended.
        geom_only = [f for f in failures if f.code not in ("ASSIGNMENT_MISMATCH",)]
        if geom_only:
            # If any hard geometry failure exists, occupancy results would
            # be noise (out-of-range periods). Return what we have.
            if any(f.code in ("UNKNOWN_DAY", "PERIOD_OUT_OF_RANGE",
                              "BLOCK_GEOMETRY", "BREAK_SPAN", "ROOM_REQUIRED")
                   for f in failures):
                return failures
    # Occupancy vs current schedule (H5/H6/H7/H8 + HN1) via the shared
    # validator snapshot. Map GROUP_CONFLICT -> SECTION_CONFLICT per the
    # Phase 6E error contract.
    cand = sv.validate_candidate(
        snap, session_type=session_type, group_key=group_key,
        group_label=group_label, group_size=group_size,
        faculty_id=faculty_id, day=day, start_period=start_period,
        length=length, room_id=getattr(room, "id", room),
        parent_section_key=parent_key, faculty_name=faculty_name)
    for res in cand:
        code = res.code
        details = dict(res.details)
        if code == "GROUP_CONFLICT":
            code = "SECTION_CONFLICT"
        if code in ("ROOM_CONFLICT", "FACULTY_CONFLICT", "SECTION_CONFLICT",
                    "SECTION_HIERARCHY_CONFLICT"):
            if conflicting_lookup:
                cid, caid, _kind = _find_conflicting_class(
                    snap, room_id=getattr(room, "id", room),
                    faculty_id=faculty_id, group_key=group_key,
                    parent_section_key=parent_key or group_key,
                    day=day, start=start_period, length=length)
                if cid is not None:
                    details.setdefault("conflicting_class_id", cid)
                    details.setdefault("conflicting_assignment_id", caid)
            if code == "ROOM_CONFLICT":
                details.setdefault("room_id", getattr(room, "id", room))
                details.setdefault("day", day)
                details.setdefault("periods",
                                   list(rules.covers(start_period, length)))
            if code == "FACULTY_CONFLICT":
                details.setdefault("faculty_id", faculty_id)
                details.setdefault("day", day)
                details.setdefault("periods",
                                   list(rules.covers(start_period, length)))
            failures.append(_fail(code, res.message, details))
        else:
            failures.append(res)
    return failures


# ------------------------------------------------------- ORM operations
def _orm_config(db):
    from backend.models import Config
    cfg = Config.query.first()
    if cfg is None:
        raise LockedBlockError("No scheduling configuration found.")
    return cfg


def create_locked_block(db, *, assignment_id, day, start_period, length,
                        room_id, kind="interdepartment", department=None,
                        note=None, faculty_id=None, subject_id=None,
                        section_id=None, lab_group_id=None,
                        room_locked=True, is_external=True):
    """Validate + atomically persist LockedBlock + ScheduledClass.

    Either both rows are created or neither is (transaction rollback on
    any validation or database failure).
    """
    from backend.models import (Faculty, LockedBlock, Room, ScheduledClass,
                                TeachingAssignment)
    if kind not in VALID_KINDS:
        raise LockedBlockError(
            f"Unknown locked-block kind '{kind}'.",
            [_fail("UNKNOWN_KIND", f"Unknown locked-block kind '{kind}'.",
                   {"kind": kind})])
    if kind != INTERDEPARTMENT_KIND:
        # 6E activates interdepartment only; other kinds stay inert.
        raise LockedBlockError(
            f"Locked-block kind '{kind}' is not enabled in Phase 6E.",
            [_fail("KIND_NOT_ENABLED",
                   f"Locked-block kind '{kind}' is not enabled in Phase 6E.",
                   {"kind": kind})])
    try:
        start_period = int(start_period)
        length = int(length)
    except (TypeError, ValueError):
        raise LockedBlockError(
            "start_period and length must be whole numbers.",
            [_fail("BLOCK_GEOMETRY",
                   "start_period and length must be whole numbers.",
                   {"start_period": start_period, "length": length})])
    assignment = TeachingAssignment.query.get(assignment_id)
    if assignment is None:
        raise LockedBlockError(
            f"Teaching assignment {assignment_id} does not exist.",
            [_fail("UNKNOWN_ASSIGNMENT",
                   f"Teaching assignment {assignment_id} does not exist.",
                   {"assignment_id": assignment_id})])
    # Phase 6F: interdepartment locks pin normal section/lab teaching.
    # Specialization assignments are scheduled as synchronized cohorts and
    # cannot be pinned as single locked blocks in this phase.
    if getattr(assignment, "specialization_id", None) is not None:
        raise LockedBlockError(
            f"Teaching assignment {assignment_id} is a specialization "
            f"assignment and cannot be locked as an interdepartment block.",
            [_fail("SPECIALIZATION_OVERLAP",
                   f"Teaching assignment {assignment_id} is a specialization "
                   f"assignment and cannot be locked as an interdepartment "
                   f"block.",
                   {"assignment_id": assignment_id,
                    "specialization_id": getattr(
                        assignment, "specialization_id", None)})])
    room = Room.query.get(room_id) if room_id is not None else None
    if room is None and room_id is not None:
        raise LockedBlockError(
            f"Room {room_id} does not exist.",
            [_fail("UNKNOWN_ROOM", f"Room {room_id} does not exist.",
                   {"room_id": room_id})])
    # Resolve locked identity from the assignment unless the caller
    # passes an explicit override (which is then mismatch-checked).
    want_faculty = faculty_id if faculty_id is not None else assignment.faculty_id
    want_subject = subject_id if subject_id is not None else assignment.subject_id
    if assignment.session_type == "practical":
        want_section = None
        want_lab = lab_group_id if lab_group_id is not None else assignment.lab_group_id
    else:
        want_section = section_id if section_id is not None else assignment.section_id
        want_lab = None

    cfg = _orm_config(db)
    days = cfg.day_list()
    periods = cfg.period_list()
    num_periods = len(periods)
    break_after = cfg.break_after_periods if cfg.break_after_periods else None

    from backend.models import LabGroup, Section
    section = Section.query.get(want_section) if want_section else None
    lab_group = LabGroup.query.get(want_lab) if want_lab else None
    group = describe_assignment(assignment, section, lab_group)
    # Apply explicit overrides for mismatch detection.
    group["faculty_id"] = want_faculty
    group["subject_id"] = want_subject
    group["section_id"] = want_section
    if assignment.session_type == "practical":
        group["lab_group_id"] = want_lab
        if want_lab is not None:
            group["group_key"] = f"labgroup:{want_lab}"
            lg = lab_group
            group["group_label"] = (getattr(lg, "name", None) or "?") if lg else "?"
            group["group_size"] = (getattr(lg, "student_count", 0) or 0) if lg else 0
            parent = getattr(lg, "section_id", None) if lg else None
            group["parent_section_key"] = f"section:{parent}" if parent else None
    else:
        group["section_id"] = want_section
        if want_section is not None:
            group["group_key"] = f"section:{want_section}"
            group["group_label"] = getattr(section, "name", None) or "?"
            group["group_size"] = getattr(section, "student_count", 0) or 0

    faculty_row = Faculty.query.get(want_faculty)
    faculty_name = faculty_row.name if faculty_row else "?"
    faculty_unavail = (faculty_row.unavailable_set()
                       if faculty_row else set())

    rooms = Room.query.all()
    faculty_rows = Faculty.query.all()
    sections = Section.query.all()
    lab_groups = LabGroup.query.all()
    assignments = TeachingAssignment.query.all()
    scheduled = ScheduledClass.query.all()
    # Phase 6F: include specialization occupancy so locked blocks cannot
    # collide with synchronized specialization slots (read-only here).
    try:
        from backend.models import (Specialization as _Spec,
                                    SpecializationMembership as _Mem)
        _specs = _Spec.query.all()
        _mems = _Mem.query.all()
    except Exception:
        _specs, _mems = [], []
    snap = _snapshot_from_orm(days, num_periods, break_after,
                              cfg.max_consecutive_teaching,
                              rooms, faculty_rows, sections, lab_groups,
                              assignments, scheduled,
                              specializations=_specs, memberships=_mems)
    # Demand already consumed by existing locked blocks for this assignment.
    from backend.models import LockedBlock as LB
    existing_locked = sum(
        lb.length for lb in LB.query.filter_by(assignment_id=assignment.id).all()
        if isinstance(lb.length, int))
    failures = validate_locked_candidate(
        day=day, start_period=start_period, length=length, room=room,
        assignment=assignment, group=group,
        faculty_unavailable=faculty_unavail, days=days,
        num_periods=num_periods, break_after=break_after, snap=snap,
        existing_locked_periods=existing_locked,
        faculty_name=faculty_name)
    if failures:
        raise LockedBlockError(
            f"Locked block invalid: {failures[0].message}", failures)
    # Atomic persist: both rows or neither.
    try:
        lb = LockedBlock(
            kind=kind, assignment_id=assignment.id,
            subject_id=want_subject, faculty_id=want_faculty,
            section_id=want_section, lab_group_id=want_lab,
            day=day, start_period=start_period, length=length,
            room_id=room.id if room else None, room_locked=bool(room_locked),
            department=department, is_external=bool(is_external), note=note)
        db.session.add(lb)
        db.session.flush()  # assigns lb.id without committing
        sc = ScheduledClass(
            assignment_id=assignment.id, day=day,
            start_period=start_period, length=length, room_id=room.id,
            run_id="locked", is_locked=True, locked_block_id=lb.id)
        db.session.add(sc)
        db.session.flush()
        sc_id = sc.id
        db.session.commit()
        # Re-fetch attached instances for the caller.
        db.session.refresh(lb)
        sc = ScheduledClass.query.get(sc_id)
        return lb, sc
    except LockedBlockError:
        db.session.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 — rollback must cover any DB error
        db.session.rollback()
        raise LockedBlockError(
            f"Could not persist locked block: {exc}",
            [_fail("PERSISTENCE_FAILED",
                   f"Could not persist locked block: {exc}", {})])


def delete_locked_block(db, locked_block_id):
    """Atomically remove a LockedBlock and its ScheduledClass rows.

    Removal never invalidates the remaining schedule (it only frees
    resources), so cancellation is always permitted once the block exists.
    """
    from backend.models import LockedBlock, ScheduledClass
    lb = LockedBlock.query.get(locked_block_id)
    if lb is None:
        raise LockedBlockError(
            f"Locked block {locked_block_id} does not exist.",
            [_fail("UNKNOWN_LOCKED_BLOCK",
                   f"Locked block {locked_block_id} does not exist.",
                   {"locked_block_id": locked_block_id})])
    try:
        ScheduledClass.query.filter_by(locked_block_id=lb.id).delete()
        db.session.delete(lb)
        db.session.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        raise LockedBlockError(
            f"Could not delete locked block: {exc}",
            [_fail("PERSISTENCE_FAILED",
                   f"Could not delete locked block: {exc}",
                   {"locked_block_id": locked_block_id})])


def query_locked_placements(db=None, kind="interdepartment"):
    """Fixed placements for the scheduler (ScheduledClass stays canonical).

    Returns a list of dicts with assignment/day/start/length/room/faculty
    plus the student-group footprint the solver must avoid. Reads LockedBlock
    rows; placement mismatch vs ScheduledClass is an audit finding, not a
    silent correction here.
    """
    from backend.models import LockedBlock
    try:
        blocks = LockedBlock.query.filter_by(kind=kind).all()
    except Exception:
        return []
    out = []
    for lb in blocks:
        assignment = getattr(lb, "assignment", None)
        faculty_id = getattr(lb, "faculty_id", None)
        session_type = getattr(assignment, "session_type", "theory")
        section_id = getattr(lb, "section_id", None)
        lab_group_id = getattr(lb, "lab_group_id", None)
        if session_type == "practical" and lab_group_id is not None:
            group_key = f"labgroup:{lab_group_id}"
            lg = getattr(lb, "lab_group", None)
            parent = getattr(lg, "section_id", None) if lg is not None else None
            parent_key = f"section:{parent}" if parent else None
        else:
            group_key = f"section:{section_id}"
            parent_key = None
        out.append({
            "locked_block_id": lb.id,
            "assignment_id": getattr(lb, "assignment_id", None)
            or getattr(assignment, "id", None),
            "day": lb.day,
            "start_period": lb.start_period,
            "length": lb.length,
            "room_id": lb.room_id,
            "faculty_id": faculty_id,
            "session_type": session_type,
            "group_key": group_key,
            "parent_section_key": parent_key,
            "section_id": section_id,
            "lab_group_id": lab_group_id,
            "subject_id": getattr(lb, "subject_id", None),
        })
    return out


def locked_block_json(lb, scheduled_class_id=None):
    """API-facing serialization (ScheduledClass stays the view source)."""
    return {
        "id": lb.id,
        "kind": lb.kind,
        "assignment_id": getattr(lb, "assignment_id", None),
        "subject_id": lb.subject_id,
        "faculty_id": lb.faculty_id,
        "section_id": lb.section_id,
        "lab_group_id": lb.lab_group_id,
        "day": lb.day,
        "start_period": lb.start_period,
        "length": lb.length,
        "room_id": lb.room_id,
        "room_locked": bool(getattr(lb, "room_locked", False)),
        "department": getattr(lb, "department", None),
        "is_external": bool(getattr(lb, "is_external", True)),
        "note": getattr(lb, "note", None),
        "scheduled_class_id": scheduled_class_id,
    }
