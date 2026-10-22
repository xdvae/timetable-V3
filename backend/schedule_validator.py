"""
Schedule validator foundation (Phase 6C).

Future home of manual-edit validation (move, room change, faculty change,
assignment change, swap, locked blocks, specialization slots). In Phase 6C
this module provides ONLY the reusable infrastructure:

* `ScheduleSnapshot` — an in-memory view of current occupancy derived from
  database rows (the database remains the single source of truth; snapshots
  are never persisted and never become authoritative);
* `build_snapshot()` — assembles the snapshot from loaded rows;
* `snapshot_without()` — returns a copy with one class's contribution
  removed (lets a move/swap validate against "everyone except me");
* `validate_candidate()` — checks one hypothetical placement against the
  snapshot using ONLY existing rules from `schedule_rules` (H2–H11) plus
  HN1 (Phase 6D: max two consecutive theory periods per section/day).

Explicitly OUT OF SCOPE for 6C: endpoints, locked blocks,
specializations, preferences, HN-rules. No Flask/HTTP/SQLAlchemy imports
here — rows are consumed duck-typed (attribute access), so this module is
importable without an app context and has no circular-import risk.
`schedule_rules` never imports this module.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from backend import schedule_rules as rules


@dataclass
class ScheduleSnapshot:
    """In-memory occupancy derived from one consistent set of DB rows."""
    days: List[str] = field(default_factory=list)
    num_periods: int = 0
    break_after: Optional[int] = None
    max_consecutive: Optional[int] = None
    # room_id -> {name, room_type, capacity, equipment_count}
    rooms: Dict[int, dict] = field(default_factory=dict)
    # faculty_id -> set("day:period")
    faculty_unavailable: Dict[int, Set[str]] = field(default_factory=dict)
    # lab_group_id -> parent section_id (H8 hierarchy)
    labgroup_section: Dict[int, int] = field(default_factory=dict)
    # assignment_id -> {group_key, parent_section_key, session_type,
    #                   group_size, group_label, faculty_id, spec_id?}
    assignments: Dict[int, dict] = field(default_factory=dict)
    # scheduled_class_id -> {assignment_id, day, start_period, length, room_id}
    classes: Dict[int, dict] = field(default_factory=dict)
    # Phase 6E: locked-block immovability footprint. Populated from
    # ScheduledClass.is_locked / locked_block_id when those columns are
    # present (duck-typed getattr, so pre-6C rows simply yield empty sets).
    # Read-only here: the validator never writes, it only refuses moves.
    locked_class_ids: Set[int] = field(default_factory=set)
    class_locked_block: Dict[int, int] = field(default_factory=dict)
    # (resource_key, day, period) -> booked count
    room_occ: Dict = field(default_factory=dict)
    faculty_occ: Dict = field(default_factory=dict)
    group_occ: Dict = field(default_factory=dict)
    # HN1: (section group_key, day, period) -> theory count. Only
    # whole-section THEORY placements are recorded here; practicals never
    # count toward the consecutive-theory streak.
    theory_occ: Dict = field(default_factory=dict)
    # Phase 6F: specialization footprint (conservative section occupancy).
    # spec_info: spec_id -> {enrollment_id, section_ids, total_students,
    #   session_type, name}. assignment_spec: assignment_id -> spec_id.
    # spec_section_occ[(section_id, day, period)] counts synchronized cohort
    # occupancy ONCE per (enrollment, day, start, length) group (never
    # triple-counted). spec_theory_occ is the theory-only subset for HN1.
    spec_info: Dict[int, dict] = field(default_factory=dict)
    assignment_spec: Dict[int, int] = field(default_factory=dict)
    spec_section_occ: Dict = field(default_factory=dict)
    spec_theory_occ: Dict = field(default_factory=dict)


def _group_info(session_type: str, section_id, section_name: str, section_size: int,
                lab_group_id, lab_group_name: str, lab_group_size: int,
                parent_section_id=None) -> dict:
    """Mirror TeachingAssignment.group_key()/group_label()/group_size() without ORM."""
    if session_type == "practical" and lab_group_id:
        parent_key = f"section:{parent_section_id}" if parent_section_id else None
        return {"group_key": f"labgroup:{lab_group_id}",
                "parent_section_key": parent_key,
                "group_label": lab_group_name or "?",
                "group_size": lab_group_size or 0}
    return {"group_key": f"section:{section_id}",
            "parent_section_key": None,
            "group_label": section_name or "?",
            "group_size": section_size or 0}


def _spec_group_key(spec_id) -> str:
    return f"specialization:{spec_id}"


def _rebuild_spec_occupancy(snap: ScheduleSnapshot) -> None:
    """Recompute deduped specialization occupancy from snap.classes.

    Groups spec classes by (enrollment, day, start, length); each group
    contributes ONCE per participating section (never triple-counted).
    Theory groups contribute to spec_theory_occ only for sections whose
    spec session at that time is theory (per-assignment session_type).
    """
    snap.spec_section_occ = {}
    snap.spec_theory_occ = {}
    # class_id -> spec context for grouping.
    groups = {}  # (enrollment, day, start, length) -> {class_ids, section_set, theory_sections}
    for cid, cls in snap.classes.items():
        info = snap.assignments.get(cls["assignment_id"])
        if info is None or info.get("spec_id") is None:
            continue
        spec_id = info["spec_id"]
        sinfo = snap.spec_info.get(spec_id, {})
        enr = sinfo.get("enrollment_id")
        key = (enr, cls["day"], cls["start_period"], cls["length"])
        g = groups.setdefault(key, {"sections": set(),
                                    "theory_sections": set()})
        for sec_id in sinfo.get("section_ids", []) or []:
            g["sections"].add(sec_id)
            if (info.get("session_type") == "theory"):
                g["theory_sections"].add(sec_id)
    for (enr, day, start, length), g in groups.items():
        for p in rules.covers(start, length):
            for sec_id in g["sections"]:
                k = (sec_id, day, p)
                snap.spec_section_occ[k] = snap.spec_section_occ.get(k, 0) + 1
            for sec_id in g["theory_sections"]:
                k = (sec_id, day, p)
                snap.spec_theory_occ[k] = snap.spec_theory_occ.get(k, 0) + 1


def build_snapshot(days: List[str], num_periods: int, break_after: Optional[int],
                   max_consecutive: Optional[int], rooms, faculty, lab_groups,
                   sections, assignments, scheduled_classes,
                   specializations=None, memberships=None) -> ScheduleSnapshot:
    """Assemble a snapshot from loaded rows (ORM objects or SimpleNamespace).

    Expected attributes — rooms: id/name/room_type/capacity/equipment_count;
    faculty: id/unavailable_set() or unavailable_slots string; lab_groups:
    id/section_id; sections: id/name/student_count; assignments: id/
    faculty_id/session_type/section_id/lab_group_id/periods_per_week/
    block_length plus resolved section/lab-group name+size+parent ids
    (Phase 6F: assignments may carry specialization_id for spec teaching);
    scheduled_classes: id/assignment_id/day/start_period/length/room_id.
    Phase 6F: optional specializations (id/enrollment_id/session_type/name)
    + memberships (specialization_id/section_id/student_count) build the
    conservative section-occupancy footprint (deduped per synchronized
    group). Existing callers omitting them get identical behavior.
    """
    snap = ScheduleSnapshot(days=list(days), num_periods=num_periods,
                            break_after=break_after, max_consecutive=max_consecutive)
    for r in rooms:
        snap.rooms[r.id] = {"name": getattr(r, "name", "?"),
                            "room_type": r.room_type, "capacity": r.capacity,
                            "equipment_count": getattr(r, "equipment_count", None)}
    for f in faculty:
        if hasattr(f, "unavailable_set"):
            snap.faculty_unavailable[f.id] = set(f.unavailable_set())
        else:
            snap.faculty_unavailable[f.id] = {
                t.strip() for t in (getattr(f, "unavailable_slots", "") or "").split(",")
                if t.strip()}
    sec_by_id = {s.id: s for s in sections}
    for lg in lab_groups:
        snap.labgroup_section[lg.id] = lg.section_id
    # Phase 6F: spec membership totals + section sets.
    mem_by_spec: Dict[int, list] = {}
    for m in memberships or []:
        mem_by_spec.setdefault(getattr(m, "specialization_id", None), []).append(m)
    spec_by_id = {s.id: s for s in (specializations or [])}
    for sid, spec in spec_by_id.items():
        mems = mem_by_spec.get(sid, [])
        snap.spec_info[sid] = {
            "enrollment_id": getattr(spec, "enrollment_id", None),
            "section_ids": sorted(m.section_id for m in mems),
            "total_students": sum(m.student_count for m in mems),
            "session_type": getattr(spec, "session_type", "theory"),
            "name": getattr(spec, "name", str(sid)),
        }
    for a in assignments:
        spec_id = getattr(a, "specialization_id", None)
        if spec_id is not None:
            sinfo = snap.spec_info.get(spec_id, {})
            total = sinfo.get("total_students", 0) or 0
            sname = sinfo.get("name", str(spec_id))
            info = {"group_key": _spec_group_key(spec_id),
                    "parent_section_key": None,
                    "group_label": f"SPEC:{sname}",
                    "group_size": total,
                    "session_type": getattr(a, "session_type", "theory"),
                    "faculty_id": getattr(a, "faculty_id", None),
                    "spec_id": spec_id,
                    "section_ids": list(sinfo.get("section_ids", []) or []),
                    "total_students": total}
            snap.assignments[a.id] = info
            snap.assignment_spec[a.id] = spec_id
            continue
        sec = sec_by_id.get(getattr(a, "section_id", None))
        if getattr(a, "session_type", "") == "practical" and getattr(a, "lab_group_id", None):
            info = _group_info("practical", None, "", 0, a.lab_group_id,
                               getattr(a, "lab_group_name", None) or "?",
                               getattr(a, "lab_group_size", 0) or 0,
                               parent_section_id=getattr(a, "lab_group_section_id", None))
        else:
            info = _group_info("theory", a.section_id,
                               getattr(a, "section_name", None)
                               or (sec.name if sec else "?"),
                               getattr(a, "section_size", None)
                               if getattr(a, "section_size", None) is not None
                               else (sec.student_count if sec else 0),
                               None, "", 0)
        info.update({"session_type": a.session_type, "faculty_id": a.faculty_id})
        snap.assignments[a.id] = info
    for sc in scheduled_classes:
        snap.classes[sc.id] = {"assignment_id": sc.assignment_id, "day": sc.day,
                               "start_period": sc.start_period,
                               "length": sc.length, "room_id": sc.room_id}
        # Phase 6E: record the lock footprint (absent columns -> unlocked).
        if bool(getattr(sc, "is_locked", False)):
            snap.locked_class_ids.add(sc.id)
            lbid = getattr(sc, "locked_block_id", None)
            if lbid is not None:
                snap.class_locked_block[sc.id] = lbid
        info = snap.assignments.get(sc.assignment_id)
        if info is None:
            continue
        rules.add_placement(snap.room_occ, sc.room_id, sc.day, sc.start_period, sc.length)
        rules.add_placement(snap.faculty_occ, info["faculty_id"], sc.day,
                            sc.start_period, sc.length)
        rules.add_placement(snap.group_occ, info["group_key"], sc.day,
                            sc.start_period, sc.length)
        if info.get("session_type") == "theory" and info.get("spec_id") is None:
            # HN1 footprint: theory occupancy per section/day/period.
            # (Spec theory lives in spec_theory_occ, deduped per sync group.)
            rules.add_placement(snap.theory_occ, info["group_key"], sc.day,
                                sc.start_period, sc.length)
        parent = info.get("parent_section_key")
        if parent:
            # H8 footprint: a lab-group practical also occupies its parent
            # section's availability for hierarchy checks.
            rules.add_placement(snap.group_occ, f"__parent__:{parent}", sc.day,
                                sc.start_period, sc.length)
    _rebuild_spec_occupancy(snap)
    return snap


def snapshot_without(snap: ScheduleSnapshot, class_id: int) -> ScheduleSnapshot:
    """Copy of `snap` with one scheduled class's occupancy removed."""
    clone = deepcopy(snap)
    current = clone.classes.pop(class_id, None)
    clone.locked_class_ids.discard(class_id)
    clone.class_locked_block.pop(class_id, None)
    if not current:
        return clone
    info = clone.assignments.get(current["assignment_id"])
    day, start, length = current["day"], current["start_period"], current["length"]
    for p in rules.covers(start, length):
        occ_keys = [(clone.room_occ, (current["room_id"], day, p)),
                    (clone.faculty_occ,
                     (info["faculty_id"], day, p) if info else None),
                    (clone.group_occ,
                     (info["group_key"], day, p) if info else None)]
        # Phase 6F: spec theory never lives in theory_occ (deduped in
        # spec_theory_occ, rebuilt below); normal theory still does.
        if info and info.get("session_type") == "theory" \
                and info.get("spec_id") is None:
            occ_keys.append((clone.theory_occ,
                             (info["group_key"], day, p)))
        for occ, key in occ_keys:
            if key is None:
                continue
            occ[key] = occ.get(key, 1) - 1
            if occ[key] <= 0:
                occ.pop(key, None)
        if info and info.get("parent_section_key"):
            pkey = (f"__parent__:{info['parent_section_key']}", day, p)
            clone.group_occ[pkey] = clone.group_occ.get(pkey, 1) - 1
            if clone.group_occ[pkey] <= 0:
                clone.group_occ.pop(pkey, None)
    # Phase 6F: spec section occupancy is deduped per synchronized group;
    # removing one class from a 3-spec sync must keep the footprint (the
    # other two still occupy it). Rebuild from remaining classes.
    if info and info.get("spec_id") is not None:
        _rebuild_spec_occupancy(clone)
    return clone


def check_locked_immovable(snap: ScheduleSnapshot, class_id: int, *,
                           day: str, start_period: int, length: int,
                           room_id: int,
                           assignment_id=None) -> Optional[rules.RuleResult]:
    """Phase 6E: refuse any change to a locked placement.

    Returns a LOCKED_BLOCK RuleResult when `class_id` is a locked class
    and the proposed fields differ from the stored placement (day, start,
    length, room, or assignment/faculty reassignment). Returns None when
    the class is unlocked or the proposal is identical (no move).
    Details identify locked_block_id, scheduled_class_id, the attempted
    change, and the current placement — the foundation for Phase 6H
    manual-edit validation. No editing UI is implemented here.
    """
    if class_id not in snap.locked_class_ids:
        return None
    current = snap.classes.get(class_id)
    if current is None:
        return None
    attempted = {"day": day, "start_period": start_period,
                 "length": length, "room_id": room_id}
    if assignment_id is not None:
        attempted["assignment_id"] = assignment_id
    current_view = {"day": current["day"],
                    "start_period": current["start_period"],
                    "length": current["length"],
                    "room_id": current["room_id"],
                    "assignment_id": current["assignment_id"]}
    changed = (
        day != current["day"]
        or start_period != current["start_period"]
        or length != current["length"]
        or room_id != current["room_id"]
        or (assignment_id is not None
            and assignment_id != current["assignment_id"])
    )
    if not changed:
        return None
    return rules.RuleResult(
        ok=False, code="LOCKED_BLOCK",
        message=f"Scheduled class {class_id} is locked and cannot be moved "
                f"(locked block {snap.class_locked_block.get(class_id)}).",
        details={"locked_block_id": snap.class_locked_block.get(class_id),
                 "scheduled_class_id": class_id,
                 "attempted_change": attempted,
                 "current": current_view})


def validate_move(snap: ScheduleSnapshot, class_id: int, *,
                  session_type: str, group_key: str, group_label: str,
                  group_size: int, faculty_id: int, day: str,
                  start_period: int, length: int, room_id: int,
                  parent_section_key: Optional[str] = None,
                  faculty_name: str = "?",
                  assignment_id=None) -> List[rules.RuleResult]:
    """Phase 6E: validate a hypothetical move of one existing class.

    Locked classes are refused with LOCKED_BLOCK before any occupancy
    check. Unlocked classes validate against a snapshot with their own
    occupancy removed (a move must not conflict with itself).
    """
    locked = check_locked_immovable(
        snap, class_id, day=day, start_period=start_period, length=length,
        room_id=room_id, assignment_id=assignment_id)
    if locked is not None:
        return [locked]
    slim = snapshot_without(snap, class_id)
    return validate_candidate(
        slim, session_type=session_type, group_key=group_key,
        group_label=group_label, group_size=group_size, faculty_id=faculty_id,
        day=day, start_period=start_period, length=length, room_id=room_id,
        parent_section_key=parent_section_key, faculty_name=faculty_name)


def validate_candidate(snap: ScheduleSnapshot, *, session_type: str, group_key: str,
                       group_label: str, group_size: int, faculty_id: int,
                       day: str, start_period: int, length: int, room_id: int,
                       parent_section_key: Optional[str] = None,
                       faculty_name: str = "?",
                       editing_class_id: Optional[int] = None,
                       assignment_id=None) -> List[rules.RuleResult]:
    """Check one hypothetical placement against a snapshot (existing rules only).

    Returns a list of failing RuleResults (empty == valid). Covers H2/H3/H4
    (room compatibility), H5/H6/H7/H8 (occupancy incl. parent-section
    footprint), H9 (faculty availability), H10/H11/H13 (geometry + day),
    and HN1 (max two consecutive theory periods for the candidate's
    section/day — theory candidates only; practicals contribute 0).
    H1/H12/H14 are input/coverage-level rules and are not per-placement
    checks here.

    When `editing_class_id` names a locked class, any differing placement
    is refused with LOCKED_BLOCK (Phase 6E immovability; foundation for
    Phase 6H). An identical placement is not a move and validates normally.
    """
    if editing_class_id is not None:
        locked = check_locked_immovable(
            snap, editing_class_id, day=day, start_period=start_period,
            length=length, room_id=room_id, assignment_id=assignment_id)
        if locked is not None:
            return [locked]
    failures: List[rules.RuleResult] = []
    room = snap.rooms.get(room_id)
    if room is None:
        return [rules.RuleResult(ok=False, code="UNKNOWN_ROOM",
                                 message=f"Room id {room_id} does not exist.",
                                 details={"room_id": room_id})]
    for res in (
        rules.check_day_known(day, snap.days),                                   # H13
        rules.check_block_geometry(start_period, length, snap.num_periods,       # H11
                                   group_label),
        rules.check_break_geometry(start_period, length, snap.break_after,       # H10
                                   group_label),
        rules.check_room_compatible(room["room_type"], room["capacity"],         # H2+H3+H4
                                    room["equipment_count"], session_type,
                                    group_size, room["name"], group_label),
        rules.check_faculty_available(                                           # H9
            snap.faculty_unavailable.get(faculty_id, set()),
            day, start_period, length, faculty_name),
    ):
        if not res.ok:
            failures.append(res)
    if failures:
        return failures  # geometry/compatibility failures dominate occupancy detail
    for occ, key, code, label in (
            (snap.room_occ, room_id, "ROOM_CONFLICT", "Room"),
            (snap.faculty_occ, faculty_id, "FACULTY_CONFLICT", "Faculty"),
            (snap.group_occ, group_key, "GROUP_CONFLICT", "Student group")):
        for p in rules.covers(start_period, length):
            if occ.get((key, day, p), 0) > 0:
                failures.append(rules.RuleResult(
                    ok=False, code=code,
                    message=f"{label} {key} is already occupied on {day} "
                            f"at period {p}.",
                    details={"resource": key, "day": day, "period": p,
                             "room_id": room_id, "faculty_id": faculty_id,
                             "group": group_key}))
                break
    if parent_section_key:
        for p in rules.covers(start_period, length):
            if snap.group_occ.get((parent_section_key, day, p), 0) > 0:
                failures.append(rules.RuleResult(
                    ok=False, code="SECTION_HIERARCHY_CONFLICT",
                    message=f"'{group_label}' overlaps its parent section "
                            f"{parent_section_key} on {day} at period {p}.",
                    details={"group": group_key, "parent": parent_section_key,
                             "day": day, "period": p}))
                break
    if session_type == "theory" and group_key.startswith("section:"):
        # Mirror image of the check above: a whole-section theory candidate
        # must also avoid existing lab-group practicals of that section,
        # which the snapshot records under the "__parent__:" footprint key
        # (parallel G1/G2 practicals must NOT block each other, so they are
        # deliberately not recorded under the plain section key).
        footprint = f"__parent__:{group_key}"
        for p in rules.covers(start_period, length):
            if snap.group_occ.get((footprint, day, p), 0) > 0:
                failures.append(rules.RuleResult(
                    ok=False, code="SECTION_HIERARCHY_CONFLICT",
                    message=f"Section '{group_label}' already has a lab-group "
                            f"practical on {day} at period {p}.",
                    details={"group": group_key, "day": day, "period": p}))
                break
    # Phase 6F: conservative specialization occupancy. A normal candidate
    # for a participating section must not overlap a synchronized
    # specialization slot (students cannot attend both).
    _spec_hit = None
    if group_key.startswith("section:"):
        try:
            _sid = int(group_key.split(":", 1)[1])
        except (ValueError, IndexError):
            _sid = None
        if _sid is not None:
            for p in rules.covers(start_period, length):
                if snap.spec_section_occ.get((_sid, day, p), 0) > 0:
                    _spec_hit = p
                    break
            if _spec_hit is not None:
                failures.append(rules.RuleResult(
                    ok=False, code="SPECIALIZATION_OVERLAP",
                    message=f"Section '{group_label}' already attends a "
                            f"specialization on {day} at period {_spec_hit}.",
                    details={"section_id": _sid, "section": group_label,
                             "day": day, "period": _spec_hit,
                             "room_id": room_id, "faculty_id": faculty_id,
                             "group": group_key}))
    elif group_key.startswith("labgroup:"):
        try:
            _lg = int(group_key.split(":", 1)[1])
        except (ValueError, IndexError):
            _lg = None
        _parent_sec = snap.labgroup_section.get(_lg) if _lg is not None else None
        if _parent_sec is not None:
            for p in rules.covers(start_period, length):
                if snap.spec_section_occ.get((_parent_sec, day, p), 0) > 0:
                    failures.append(rules.RuleResult(
                        ok=False, code="SPECIALIZATION_OVERLAP",
                        message=f"'{group_label}' overlaps its parent section's "
                                f"specialization on {day} at period {p}.",
                        details={"group": group_key,
                                 "parent_section_id": _parent_sec,
                                 "day": day, "period": p}))
                    break
    if session_type == "theory" and group_key.startswith("section:"):
        # HN1: the candidate's covered periods join the section's existing
        # theory occupancy for the day; any fully-covered 3-period
        # in-segment window is a violation. Practical candidates skip this
        # (labs contribute 0 to the theory streak).
        # Phase 6F: specialization theory counts ONCE per section (union,
        # never triple-counted).
        try:
            section_id = int(group_key.split(":", 1)[1])
        except (ValueError, IndexError):
            section_id = None
        occupied = {p for (k, d, p) in snap.theory_occ
                    if k == group_key and d == day}
        if section_id is not None:
            occupied.update(p for (sid, d, p) in snap.spec_theory_occ
                            if sid == section_id and d == day)
        occupied.update(rules.covers(start_period, length))
        for res in rules.check_max_two_theory(
                occupied, snap.num_periods, snap.break_after,
                group_label, day, section_id,
                extra_details={"room_id": room_id, "faculty_id": faculty_id,
                               "group": group_key}):
            failures.append(res)
    return failures


def validate_specialization_candidate(
        snap: ScheduleSnapshot, *, specialization_id: int,
        section_ids, total_students: int, session_type: str,
        faculty_id: int, day: str, start_period: int, length: int,
        room_id: int, specialization_name: str = "?",
        faculty_name: str = "?") -> List[rules.RuleResult]:
    """Phase 6F: validate one hypothetical specialization placement.

    Checks H2/H3/H4 (room holds the whole specialization headcount),
    H5/H6 (room/faculty occupancy), H9/H10/H11/H13 (availability/geometry),
    SPECIALIZATION_OVERLAP (every participating section must be free of
    normal teaching there), and HN1 (theory counts once per section;
    practicals contribute 0). Overlapping an existing synchronized spec
    slot for the same cohort is allowed (that IS synchronization) and is
    therefore NOT checked against spec_section_occ here.
    """
    failures: List[rules.RuleResult] = []
    room = snap.rooms.get(room_id)
    if room is None:
        return [rules.RuleResult(ok=False, code="UNKNOWN_ROOM",
                                 message=f"Room id {room_id} does not exist.",
                                 details={"room_id": room_id})]
    label = f"SPEC:{specialization_name}"
    for res in (
        rules.check_day_known(day, snap.days),
        rules.check_block_geometry(start_period, length, snap.num_periods,
                                   label),
        rules.check_break_geometry(start_period, length, snap.break_after,
                                   label),
        rules.check_room_compatible(room["room_type"], room["capacity"],
                                    room["equipment_count"], session_type,
                                    total_students or 0, room["name"], label),
        rules.check_faculty_available(
            snap.faculty_unavailable.get(faculty_id, set()),
            day, start_period, length, faculty_name),
    ):
        if not res.ok:
            # Map room-capacity failures to the specialization code so
            # administrators see the cohort context.
            if res.code == "ROOM_CAPACITY":
                failures.append(rules.RuleResult(
                    ok=False, code="SPECIALIZATION_CAPACITY",
                    message=res.message,
                    details={**res.details,
                             "specialization_id": specialization_id,
                             "specialization": specialization_name}))
            else:
                failures.append(res)
    if failures:
        return failures
    for occ, key, code, olabel in (
            (snap.room_occ, room_id, "ROOM_CONFLICT", "Room"),
            (snap.faculty_occ, faculty_id, "FACULTY_CONFLICT", "Faculty")):
        for p in rules.covers(start_period, length):
            if occ.get((key, day, p), 0) > 0:
                failures.append(rules.RuleResult(
                    ok=False, code=code,
                    message=f"{olabel} {key} is already occupied on {day} "
                            f"at period {p} (specialization "
                            f"'{specialization_name}').",
                    details={"resource": key, "day": day, "period": p,
                             "room_id": room_id, "faculty_id": faculty_id,
                             "specialization_id": specialization_id,
                             "specialization": specialization_name}))
                break
    for sec_id in section_ids or []:
        sec_key = f"section:{sec_id}"
        for p in rules.covers(start_period, length):
            if snap.group_occ.get((sec_key, day, p), 0) > 0:
                failures.append(rules.check_specialization_overlap(
                    section_name=str(sec_id),
                    specialization_name=specialization_name,
                    day=day, period=p,
                    specialization_id=specialization_id,
                    section_id=sec_id))
                break
            if snap.group_occ.get((f"__parent__:{sec_key}", day, p), 0) > 0:
                failures.append(rules.RuleResult(
                    ok=False, code="SPECIALIZATION_OVERLAP",
                    message=f"Specialization '{specialization_name}' on {day} "
                            f"at period {p} overlaps a lab-group practical "
                            f"for participating section {sec_id}.",
                    details={"specialization_id": specialization_id,
                             "specialization": specialization_name,
                             "section_id": sec_id, "day": day,
                             "period": p}))
                break
        if session_type == "theory":
            occupied = {p for (k, d, p) in snap.theory_occ
                        if k == sec_key and d == day}
            occupied.update(p for (sid, d, p) in snap.spec_theory_occ
                            if sid == sec_id and d == day)
            occupied.update(rules.covers(start_period, length))
            try:
                _sec_label = str(sec_id)
            except Exception:
                _sec_label = "?"
            for res in rules.check_max_two_theory(
                    occupied, snap.num_periods, snap.break_after,
                    _sec_label, day, sec_id,
                    extra_details={"room_id": room_id,
                                   "faculty_id": faculty_id,
                                   "specialization_id": specialization_id,
                                   "specialization": specialization_name}):
                failures.append(res)
    return failures


def validate_specialization_sync(snap: ScheduleSnapshot,
                                 slots_by_spec,
                                 spec_names=None,
                                 enrollment_id=None) -> List[rules.RuleResult]:
    """Phase 6F: check one cohort's slots share one synchronized pattern.

    `slots_by_spec`: {spec_id: [(day, start, length), ...]}. Thin wrapper
    over schedule_rules so the API, audit, and tests share one definition.
    """
    from backend.specializations import validate_sync_for_enrollment \
        as _sync
    return _sync(slots_by_spec, spec_names, enrollment_id)
