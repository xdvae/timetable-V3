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
  snapshot using ONLY existing rules from `schedule_rules` (H2–H11).

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
    #                   group_size, group_label, faculty_id}
    assignments: Dict[int, dict] = field(default_factory=dict)
    # scheduled_class_id -> {assignment_id, day, start_period, length, room_id}
    classes: Dict[int, dict] = field(default_factory=dict)
    # (resource_key, day, period) -> booked count
    room_occ: Dict = field(default_factory=dict)
    faculty_occ: Dict = field(default_factory=dict)
    group_occ: Dict = field(default_factory=dict)


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


def build_snapshot(days: List[str], num_periods: int, break_after: Optional[int],
                   max_consecutive: Optional[int], rooms, faculty, lab_groups,
                   sections, assignments, scheduled_classes) -> ScheduleSnapshot:
    """Assemble a snapshot from loaded rows (ORM objects or SimpleNamespace).

    Expected attributes — rooms: id/name/room_type/capacity/equipment_count;
    faculty: id/unavailable_set() or unavailable_slots string; lab_groups:
    id/section_id; sections: id/name/student_count; assignments: id/
    faculty_id/session_type/section_id/lab_group_id/periods_per_week/
    block_length plus resolved section/lab-group name+size+parent ids;
    scheduled_classes: id/assignment_id/day/start_period/length/room_id.
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
    for a in assignments:
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
        info = snap.assignments.get(sc.assignment_id)
        if info is None:
            continue
        rules.add_placement(snap.room_occ, sc.room_id, sc.day, sc.start_period, sc.length)
        rules.add_placement(snap.faculty_occ, info["faculty_id"], sc.day,
                            sc.start_period, sc.length)
        rules.add_placement(snap.group_occ, info["group_key"], sc.day,
                            sc.start_period, sc.length)
        parent = info.get("parent_section_key")
        if parent:
            # H8 footprint: a lab-group practical also occupies its parent
            # section's availability for hierarchy checks.
            rules.add_placement(snap.group_occ, f"__parent__:{parent}", sc.day,
                                sc.start_period, sc.length)
    return snap


def snapshot_without(snap: ScheduleSnapshot, class_id: int) -> ScheduleSnapshot:
    """Copy of `snap` with one scheduled class's occupancy removed."""
    clone = deepcopy(snap)
    current = clone.classes.pop(class_id, None)
    if not current:
        return clone
    info = clone.assignments.get(current["assignment_id"])
    day, start, length = current["day"], current["start_period"], current["length"]
    for p in rules.covers(start, length):
        for occ, key in ((clone.room_occ, (current["room_id"], day, p)),
                         (clone.faculty_occ,
                          (info["faculty_id"], day, p) if info else None),
                         (clone.group_occ,
                          (info["group_key"], day, p) if info else None)):
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
    return clone


def validate_candidate(snap: ScheduleSnapshot, *, session_type: str, group_key: str,
                       group_label: str, group_size: int, faculty_id: int,
                       day: str, start_period: int, length: int, room_id: int,
                       parent_section_key: Optional[str] = None,
                       faculty_name: str = "?") -> List[rules.RuleResult]:
    """Check one hypothetical placement against a snapshot (existing rules only).

    Returns a list of failing RuleResults (empty == valid). Covers H2/H3/H4
    (room compatibility), H5/H6/H7/H8 (occupancy incl. parent-section
    footprint), H9 (faculty availability), H10/H11/H13 (geometry + day).
    H1/H12/H14 are input/coverage-level rules and are not per-placement
    checks here.
    """
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
    return failures
