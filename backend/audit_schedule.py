"""
Independent audit of a generated schedule — re-checks every hard
constraint directly against the ScheduledClass rows in the database,
completely separately from the solver's own constraint-building logic.
Run this any time after generating a timetable to double-check there are
no room/faculty/student-group double-bookings, no break violations, no
capacity/equipment violations, and no faculty member over the
consecutive-teaching limit, and HN1 (no section with three consecutive
theory periods in one teaching segment of a day).

Phase 6C: the logical checks below are applied through
backend/schedule_rules.py (the shared rule layer) instead of inline
re-implementations. Phase 6D adds HN1 detection (check_max_two_theory)
reusing the section theory occupancy already collected for the H8
hierarchy check. This script still never imports backend/scheduler.py —
generation and auditing share rule *definitions*, not code paths.

Read-only: performs SELECTs only, never commits.

Usage: python -m backend.audit_schedule (from the repository root)
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app, db
from backend.models import ScheduledClass, TeachingAssignment, Config, Room
from backend import schedule_rules as rules

with app.app_context():
    cfg = Config.query.first()
    break_after = cfg.break_after_periods
    max_consec = cfg.max_consecutive_teaching

    rows = ScheduledClass.query.join(TeachingAssignment).all()
    print(f"Auditing {len(rows)} scheduled class blocks...\n")

    problems = []
    room_occ = {}
    fac_occ = {}
    group_occ = {}
    # cell -> human-readable assignment descriptions (for messages only;
    # the validity decision comes from schedule_rules).
    cell_desc = defaultdict(list)

    def _describe(sc):
        a = sc.assignment
        subj = a.subject.name if a.subject else "?"
        return f"assignment {a.id} ({subj}, {a.group_label()})"

    for sc in rows:
        a = sc.assignment
        periods = list(rules.covers(sc.start_period, sc.length))

        # H10: break geometry (shared rule).
        res = rules.check_break_geometry(sc.start_period, sc.length, break_after,
                                         group_label=a.group_label())
        if not res.ok:
            problems.append(
                f"BREAK VIOLATION: {_describe(sc)} on {sc.day} spans across "
                f"the break (starts {sc.start_period}, length {sc.length}).")

        # H2+H3+H4: room compatibility (shared rule).
        room = sc.room
        group_size = a.group_size()
        res = rules.check_room_compatible(
            room.room_type, room.capacity, room.equipment_count,
            a.session_type, group_size,
            room_name=room.name, group_label=a.group_label())
        if not res.ok:
            kind = {"ROOM_CAPACITY": "CAPACITY", "ROOM_TYPE_MISMATCH": "ROOM TYPE",
                    "ROOM_EQUIPMENT": "EQUIPMENT"}.get(res.code, "ROOM")
            problems.append(f"{kind} VIOLATION: {res.message} — {_describe(sc)}.")

        for p in periods:
            rules.add_placement(room_occ, sc.room_id, sc.day, p, 1)
            rules.add_placement(fac_occ, a.faculty_id, sc.day, p, 1)
            rules.add_placement(group_occ, a.group_key(), sc.day, p, 1)
            desc = _describe(sc)
            cell_desc[("room", sc.room_id, sc.day, p)].append(desc)
            cell_desc[("faculty", a.faculty_id, sc.day, p)].append(desc)
            cell_desc[("group", a.group_key(), sc.day, p)].append(desc)

    def check_overlap(occ, code, label, kind):
        for res in rules.check_no_overlap(occ, code, label):
            key, day, period = res.details["resource"], res.details["day"], res.details["period"]
            ids = "; ".join(cell_desc[(kind, key, day, period)])
            problems.append(f"{label} DOUBLE-BOOKED: {(key, day)} at period {period} -> {ids}")

    check_overlap(room_occ, "ROOM_CONFLICT", "ROOM", "room")
    check_overlap(fac_occ, "FACULTY_CONFLICT", "FACULTY", "faculty")
    check_overlap(group_occ, "GROUP_CONFLICT", "STUDENT GROUP", "group")

    # H8: hierarchical check via the shared rule — a lab group's students are
    # a subset of their parent section, so a lab-group session must never
    # overlap a whole-section theory session.
    from backend.models import LabGroup
    lg_sections = {lg.id: lg.section_id for lg in LabGroup.query.all()}
    section_theory_periods = defaultdict(set)   # section_id -> {(day, period)}
    labgroup_periods = defaultdict(set)         # lab_group_id -> {(day, period)}
    for sc in rows:
        a = sc.assignment
        periods = rules.covers(sc.start_period, sc.length)
        if a.session_type == "theory" and a.section_id:
            for p in periods:
                section_theory_periods[a.section_id].add((sc.day, p))
        elif a.session_type == "practical" and a.lab_group_id:
            for p in periods:
                labgroup_periods[a.lab_group_id].add((sc.day, p))
    grouped = defaultdict(list)
    for lg_id, sec_id, cell in rules.find_hierarchy_overlaps(
            labgroup_periods, section_theory_periods, lg_sections):
        grouped[(lg_id, sec_id)].append(cell)
    for (lg_id, sec_id), cells in sorted(grouped.items()):
        problems.append(f"HIERARCHY VIOLATION: lab group {lg_id} (part of section {sec_id}) "
                        f"has a practical at the same time as a whole-section theory class "
                        f"at: {sorted(cells)}")

    # H12: faculty consecutive-teaching limit via the shared rule.
    if max_consec:
        fac_day_periods = defaultdict(set)
        for (fid_day, day, p) in [((k[0]), k[1], k[2]) for k in fac_occ]:
            fac_day_periods[(fid_day, day)].add(p)
        for (fid, day), occupied in sorted(fac_day_periods.items(),
                                           key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
            res = rules.check_faculty_consecutive(occupied, max_consec,
                                                  faculty_id=fid, day=day)
            if not res.ok:
                problems.append(f"CONSECUTIVE-TEACHING VIOLATION: {res.message}")

    # HN1: max two consecutive theory periods per section/day, via the
    # shared rule over the section theory occupancy collected above.
    # Practicals never contribute (only theory periods were recorded).
    from backend.models import Section
    num_periods = len(cfg.period_list())
    day_order = {d: i for i, d in enumerate(cfg.day_list())}
    sec_names = {s.id: s.name for s in Section.query.all()}
    for sec_id in sorted(section_theory_periods):
        by_day = defaultdict(set)
        for (d, p) in section_theory_periods[sec_id]:
            by_day[d].add(p)
        for d in sorted(by_day, key=lambda x: (day_order.get(x, 999), str(x))):
            for res in rules.check_max_two_theory(
                    by_day[d], num_periods, break_after,
                    sec_names.get(sec_id, f"section {sec_id}"), d, sec_id):
                problems.append(f"MAX_TWO_THEORY VIOLATION: {res.message}")

    if problems:
        print(f"[FAIL] {len(problems)} PROBLEM(S) FOUND:\n")
        for p in problems:
            print(" -", p)
    else:
        print("[OK] No conflicts found: rooms, faculty, and student groups are never "
              "double-booked, no session crosses the break, room type/capacity/equipment "
              "always match, no faculty member exceeds the consecutive-teaching limit, "
              "no lab group's practical overlaps a whole-section theory class for its "
              "own section, and no section has three consecutive theory periods in "
              "one teaching segment of a day.")
