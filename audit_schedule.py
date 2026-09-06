"""
Independent audit of a generated schedule — re-checks every hard
constraint directly against the ScheduledClass rows in the database,
completely separately from the solver's own constraint-building logic.
Run this any time after generating a timetable to double-check there are
no room/faculty/student-group double-bookings, no break violations, no
capacity/equipment violations, and no faculty member over the
consecutive-teaching limit.

Usage: python audit_schedule.py
"""
from collections import defaultdict
from app import app, db
from models import ScheduledClass, TeachingAssignment, Config, Room

with app.app_context():
    cfg = Config.query.first()
    break_after = cfg.break_after_periods
    max_consec = cfg.max_consecutive_teaching

    rows = ScheduledClass.query.join(TeachingAssignment).all()
    print(f"Auditing {len(rows)} scheduled class blocks...\n")

    problems = []
    room_occ = defaultdict(list)
    fac_occ = defaultdict(list)
    group_occ = defaultdict(list)

    for sc in rows:
        a = sc.assignment
        periods = list(range(sc.start_period, sc.start_period + sc.length))

        if break_after is not None and sc.start_period < break_after < (sc.start_period + sc.length):
            problems.append(f"BREAK VIOLATION: assignment {a.id} ({a.subject.name}, {a.group_label()}) "
                             f"on {sc.day} spans across the break (starts {sc.start_period}, length {sc.length}).")

        room = sc.room
        group_size = a.group_size()
        if room.capacity < group_size:
            problems.append(f"CAPACITY VIOLATION: {room.name} (cap {room.capacity}) holds "
                             f"{a.group_label()} ({group_size} students) — assignment {a.id}.")
        wanted_type = "lab" if a.session_type == "practical" else "theory"
        if room.room_type != wanted_type:
            problems.append(f"ROOM TYPE VIOLATION: {a.session_type} session in a {room.room_type} room "
                             f"({room.name}) — assignment {a.id}.")
        if wanted_type == "lab" and room.equipment_count is not None and room.equipment_count < group_size:
            problems.append(f"EQUIPMENT VIOLATION: {room.name} has {room.equipment_count} equipment "
                             f"for {group_size} students — assignment {a.id}.")

        for p in periods:
            room_occ[(sc.room_id, sc.day)].append((p, sc))
            fac_occ[(a.faculty_id, sc.day)].append((p, sc))
            group_occ[(a.group_key(), sc.day)].append((p, sc))

    def check_overlap(occ_dict, label):
        for key, entries in occ_dict.items():
            by_period = defaultdict(list)
            for p, sc in entries:
                by_period[p].append(sc)
            for p, scs in by_period.items():
                if len(scs) > 1:
                    ids = [f"assignment {sc.assignment_id} ({sc.assignment.subject.name}, {sc.assignment.group_label()})" for sc in scs]
                    problems.append(f"{label} DOUBLE-BOOKED: {key} at period {p} -> {'; '.join(ids)}")

    check_overlap(room_occ, "ROOM")
    check_overlap(fac_occ, "FACULTY")
    check_overlap(group_occ, "STUDENT GROUP")

    # hierarchical check: a lab group's students are a subset of their
    # parent section, so a lab-group session must never overlap a
    # whole-section theory session
    from models import LabGroup
    lg_sections = {lg.id: lg.section_id for lg in LabGroup.query.all()}
    section_theory_periods = defaultdict(set)   # section_id -> {(day, period)}
    labgroup_periods = defaultdict(set)         # lab_group_id -> {(day, period)}
    for sc in rows:
        a = sc.assignment
        periods = range(sc.start_period, sc.start_period + sc.length)
        if a.session_type == "theory" and a.section_id:
            for p in periods:
                section_theory_periods[a.section_id].add((sc.day, p))
        elif a.session_type == "practical" and a.lab_group_id:
            for p in periods:
                labgroup_periods[a.lab_group_id].add((sc.day, p))
    for lg_id, sec_id in lg_sections.items():
        overlap = labgroup_periods[lg_id] & section_theory_periods[sec_id]
        if overlap:
            problems.append(f"HIERARCHY VIOLATION: lab group {lg_id} (part of section {sec_id}) "
                             f"has a practical at the same time as a whole-section theory class "
                             f"at: {sorted(overlap)}")

    if max_consec:
        for (fid, day), entries in fac_occ.items():
            occupied_periods = sorted(set(p for p, sc in entries))
            run_len = 1
            for i in range(1, len(occupied_periods)):
                if occupied_periods[i] == occupied_periods[i-1] + 1:
                    run_len += 1
                    if run_len > max_consec:
                        problems.append(f"CONSECUTIVE-TEACHING VIOLATION: faculty {fid} on {day} "
                                         f"teaches {run_len} periods in a row ending at period {occupied_periods[i]} "
                                         f"(max allowed {max_consec}).")
                else:
                    run_len = 1

    if problems:
        print(f"❌ {len(problems)} PROBLEM(S) FOUND:\n")
        for p in problems:
            print(" -", p)
    else:
        print("✅ No conflicts found: rooms, faculty, and student groups are never "
              "double-booked, no session crosses the break, room type/capacity/equipment "
              "always match, no faculty member exceeds the consecutive-teaching limit, "
              "and no lab group's practical overlaps a whole-section theory class for its "
              "own section.")
