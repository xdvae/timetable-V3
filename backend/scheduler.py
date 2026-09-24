"""
Timetable scheduling engine using Google OR-Tools CP-SAT.

Approach
--------
Every TeachingAssignment (faculty + subject + section/lab-group, with a
weekly period count and a block length) is expanded into one or more
"sessions" — a session is one contiguous block that must be placed at a
single (day, start_period, room).

For each session we create a boolean decision variable for every valid
(day, start_period, room) combination it could legally occupy (room type
matches, capacity is sufficient, the block doesn't cross the lunch break,
and it fits before the day ends).

Hard constraints:
  * every session is placed exactly once
  * no room double-booked
  * no faculty double-booked
  * no student group / lab-group double-booked
  * a lab group's session never overlaps a whole-section theory session
    for the section it belongs to (its students are a subset of that
    section, so they can't be in two places at once)
  * a faculty member doesn't teach more than `max_consecutive_teaching`
    periods in a row without at least one free period (a "break")
  * HN1: a student section never has three consecutive theory periods in
    one teaching segment of a day (labs/free periods reset the streak;
    windows never cross the lunch break)

Soft objective (what makes the timetable *good*, not just legal):
  * minimize the sum of start-periods across all sessions. Because a
    student group can never have two classes at once (hard constraint),
    pushing every session's start time as early as possible forces the
    solver to pack each group's day into a contiguous early block instead
    of leaving gaps or running late — this single objective term produces
    both "no dead gaps" and "go home early" behaviour for free.
"""
import itertools
import time
from ortools.sat.python import cp_model

# Phase 6C: logical rule definitions live in backend/schedule_rules.py.
# The CP-SAT encoding below is unchanged; the helpers are used for domain
# pruning, and each linear-constraint block notes which logical rule it
# mirrors (predicates can never replace CP-SAT expressions — see Part 4).
from backend.schedule_rules import (
    check_room_compatible,
    hn1_windows,
    is_faculty_available,
    overlap_count,
    valid_starts as rule_valid_starts,
)


def expand_sessions(assignments):
    """Turn TeachingAssignment rows into a flat list of session dicts."""
    sessions = []
    for a in assignments:
        remaining = a.periods_per_week
        block = a.block_length
        idx = 0
        # A lab group's students are a subset of their parent section's
        # students, so a practical session must never overlap with a
        # theory session for the WHOLE section it belongs to (they'd be
        # the same physical students in two places at once).
        parent_section_key = f"section:{a.lab_group.section_id}" if a.session_type == "practical" and a.lab_group else None
        while remaining > 0:
            length = block if remaining >= block else remaining
            sessions.append({
                "assignment_id": a.id,
                "faculty_id": a.faculty_id,
                "subject_id": a.subject_id,
                "session_type": a.session_type,
                "group_key": a.group_key(),
                "group_label": a.group_label(),
                "group_size": a.group_size(),
                "parent_section_key": parent_section_key,
                "length": length,
                "seq": idx,
            })
            remaining -= length
            idx += 1
    return sessions


def compatible_rooms(session, rooms):
    # Phase 6C: per-room legality delegates to schedule_rules
    # (H2 room capacity + H3 room type + H4 lab equipment). Order and
    # semantics are unchanged: rooms are returned in input order.
    out = []
    for r in rooms:
        if check_room_compatible(
            r.room_type, r.capacity, r.equipment_count,
            session["session_type"], session["group_size"],
            room_name=r.name, group_label=session["group_label"],
        ).ok:
            out.append(r)
    return out


def valid_starts(length, num_periods, break_after):
    """Start periods where a block of `length` fits without crossing the lunch break."""
    # Phase 6C: single definition now lives in schedule_rules (H10+H11).
    return rule_valid_starts(length, num_periods, break_after)


def run_scheduler(assignments, rooms, faculty_unavailable, days, num_periods,
                   break_after, max_consecutive, time_limit_seconds=30):
    """
    faculty_unavailable: dict faculty_id -> set of "day:period" strings
    Returns: (status_str, list_of_placements) where each placement is
             {assignment_id, seq, day, start_period, length, room_id}
             or (status_str, []) / (status_str, None) with a message on failure.
    """
    sessions = expand_sessions(assignments)
    if not sessions:
        return "NO_SESSIONS", [], "No teaching assignments to schedule."

    model = cp_model.CpModel()

    # x[(s_idx, day, start, room_id)] = BoolVar
    x = {}
    session_options = [[] for _ in sessions]  # list of (day,start,room_id) per session

    for s_idx, sess in enumerate(sessions):
        rooms_ok = compatible_rooms(sess, rooms)
        if not rooms_ok:
            return "INFEASIBLE", [], (
                f"No compatible room exists for '{sess['group_label']}' "
                f"({sess['session_type']}, {sess['group_size']} students). "
                f"Add a {'lab' if sess['session_type']=='practical' else 'theory'} "
                f"room with enough capacity."
            )
        starts = valid_starts(sess["length"], num_periods, break_after)
        if not starts:
            return "INFEASIBLE", [], (
                f"Session length {sess['length']} for '{sess['group_label']}' "
                f"doesn't fit in any day (num_periods={num_periods})."
            )
        unavail = faculty_unavailable.get(sess["faculty_id"], set())
        for day in days:
            for start in starts:
                # Phase 6C: H9 faculty-availability pruning via shared rule.
                if not is_faculty_available(unavail, day, start, sess["length"]):
                    continue
                for room in rooms_ok:
                    var = model.NewBoolVar(f"x_{s_idx}_{day}_{start}_{room.id}")
                    x[(s_idx, day, start, room.id)] = var
                    session_options[s_idx].append((day, start, room.id))

    for s_idx, sess in enumerate(sessions):
        opts = session_options[s_idx]
        if not opts:
            return "INFEASIBLE", [], (
                f"'{sess['group_label']}' ({sess['subject_id']}) has no legal "
                f"day/period/room slot at all — check faculty availability and room setup."
            )
        # H1 (schedule_rules.check_session_coverage is the logical counterpart):
        # every session is placed exactly once.
        model.Add(sum(x[(s_idx, d, st, r)] for (d, st, r) in opts) == 1)

    # ---- Resource occupancy expressions per (resource, day, period) ----
    def build_occupancy(key_func):
        occ = {}
        for s_idx, sess in enumerate(sessions):
            key = key_func(sess)
            for (d, start, r) in session_options[s_idx]:
                var = x[(s_idx, d, start, r)]
                for p in range(start, start + sess["length"]):
                    occ.setdefault((key, d, p), []).append(var)
        return occ

    room_occ = {}
    for s_idx, sess in enumerate(sessions):
        for (d, start, r) in session_options[s_idx]:
            var = x[(s_idx, d, start, r)]
            for p in range(start, start + sess["length"]):
                room_occ.setdefault((r, d, p), []).append(var)
    # H5 (logical counterpart: schedule_rules.check_no_overlap over room occupancy).
    for key, vlist in room_occ.items():
        model.Add(sum(vlist) <= 1)

    fac_occ = build_occupancy(lambda sess: sess["faculty_id"])
    # H6 (logical counterpart: schedule_rules.check_no_overlap over faculty occupancy).
    for key, vlist in fac_occ.items():
        model.Add(sum(vlist) <= 1)

    group_occ = build_occupancy(lambda sess: sess["group_key"])
    # H7 (logical counterpart: schedule_rules.check_no_overlap over group occupancy).
    for key, vlist in group_occ.items():
        model.Add(sum(vlist) <= 1)

    # ---- Section <-> its lab groups must never overlap ----
    # H8 (logical counterpart: schedule_rules.find_hierarchy_overlaps).
    # (a lab group's session and a whole-section theory session would
    # otherwise be allowed to run at the same time, which is impossible
    # since the lab group's students are also section students)
    parent_of = {}
    for sess in sessions:
        if sess["parent_section_key"]:
            parent_of[sess["group_key"]] = sess["parent_section_key"]
    for child_key, parent_key in parent_of.items():
        dp_keys = {k[1:] for k in group_occ if k[0] == child_key} | {k[1:] for k in group_occ if k[0] == parent_key}
        for (d, p) in dp_keys:
            child_vars = group_occ.get((child_key, d, p), [])
            parent_vars = group_occ.get((parent_key, d, p), [])
            if child_vars and parent_vars:
                model.Add(sum(child_vars) + sum(parent_vars) <= 1)

    # ---- Faculty consecutive-teaching / break constraint ----
    # H12 (logical counterpart: schedule_rules.check_faculty_consecutive; the
    # window-sum formulation over binary occupancy is equivalent to a
    # longest-run check).
    if max_consecutive and max_consecutive > 0:
        window = max_consecutive + 1
        fac_ids = {sess["faculty_id"] for sess in sessions}
        for fid in fac_ids:
            for d in days:
                for p0 in range(0, num_periods - window + 1):
                    terms = []
                    for p in range(p0, p0 + window):
                        terms.extend(fac_occ.get((fid, d, p), []))
                    if terms:
                        model.Add(sum(terms) <= max_consecutive)

    # ---- HN1: max two consecutive theory periods per section per day ----
    # Logical counterpart: schedule_rules.check_max_two_theory. For every
    # section, day, and 3-period in-segment window: sum over theory-session
    # candidate booleans of (overlap-period count * boolean) <= 2.
    # Practical sessions contribute 0 and are excluded; each placement
    # boolean appears once per window with its period-weighted coefficient.
    theory_by_section = {}
    for s_idx, sess in enumerate(sessions):
        if sess["session_type"] != "theory":
            continue
        theory_by_section.setdefault(sess["group_key"], []).append(s_idx)
    for sec_key in sorted(theory_by_section, key=str):
        for d in days:
            for window in hn1_windows(num_periods, break_after):
                terms = []
                for s_idx in theory_by_section[sec_key]:
                    length = sessions[s_idx]["length"]
                    for (od, start, r) in session_options[s_idx]:
                        if od != d:
                            continue
                        coeff = overlap_count(start, length, window)
                        if coeff:
                            terms.append(coeff * x[(s_idx, od, start, r)])
                if terms:
                    model.Add(sum(terms) <= 2)

    # ---- Soft objective: minimize start periods (compact + early-finish) ----
    objective_terms = []
    for s_idx, sess in enumerate(sessions):
        for (d, start, r) in session_options[s_idx]:
            # squared-ish weighting via linear scale keeps it simple & fast for CP-SAT
            objective_terms.append(start * x[(s_idx, d, start, r)])
    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return "INFEASIBLE", [], (
            "No valid timetable could be found with the current data and "
            "constraints. Try adding more rooms, relaxing faculty availability, "
            "or checking for faculty overloaded across too many sections."
        )

    placements = []
    for s_idx, sess in enumerate(sessions):
        for (d, start, r) in session_options[s_idx]:
            if solver.Value(x[(s_idx, d, start, r)]) == 1:
                placements.append({
                    "assignment_id": sess["assignment_id"],
                    "day": d,
                    "start_period": start,
                    "length": sess["length"],
                    "room_id": r,
                })
                break

    status_str = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
    return status_str, placements, None
