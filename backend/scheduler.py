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
    check_block_geometry,
    check_break_geometry,
    check_day_known,
    check_faculty_consecutive,
    check_max_two_theory,
    check_room_compatible,
    hn1_windows,
    is_faculty_available,
    max_run_length,
    overlap_count,
    valid_starts as rule_valid_starts,
)
from backend.faculty_preferences import (
    normalize_faculty_preferences,
    faculty_time_penalty,
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


def normalize_preferred_rooms(preferred_theory_rooms, rooms):
    """Clean a section -> preferred-room side map for the solver.

    Keeps only {int section_id: int room_id} pairs whose room exists in
    `rooms`. Drops None values, unknown room ids (e.g. a room deleted
    after configuration), and non-integer junk. A dropped entry behaves
    exactly like no preference. Pure (no ORM/IO); never affects hard
    room validation, which stays in `compatible_rooms`.
    """
    known = set()
    for r in rooms or []:
        try:
            known.add(int(getattr(r, "id", None)))
        except (TypeError, ValueError):
            continue
    clean = {}
    for section_id, room_id in dict(preferred_theory_rooms or {}).items():
        try:
            sid, rid = int(section_id), int(room_id)
        except (TypeError, ValueError):
            continue
        if rid in known:
            clean[sid] = rid
    return clean


def preferred_room_penalty(session, room_id, preferred_theory_rooms):
    """Soft 0/1 penalty for one candidate placement (Phase 6I).

    Returns 0 when the candidate uses the session section's preferred
    theory room, 1 when the section maps to a *different* room, and 0
    for every session the preference must not touch: non-theory
    sessions, lab-group practicals, specialization sessions, sessions
    without a parseable section, and sections with no mapped preference
    (including a mapped-away incompatible room, which simply yields a
    uniform per-session constant that cannot change the optimum).
    Pure: operates on the session dict + room id only.
    """
    if not preferred_theory_rooms:
        return 0
    if session.get("session_type") != "theory":
        return 0
    group_key = session.get("group_key", "") or ""
    if not group_key.startswith("section:"):
        return 0
    try:
        section_id = int(group_key.split(":", 1)[1])
    except (ValueError, IndexError):
        return 0
    preferred = preferred_theory_rooms.get(section_id)
    if preferred is None:
        return 0
    try:
        if int(room_id) == int(preferred):
            return 0
    except (TypeError, ValueError):
        return 0
    return 1


def preferred_time_scale(num_sessions):
    """Start-period multiplier that keeps time-compactness strictly primary.

    Invariant: one start-period unit (worth `num_sessions + 1`) always
    outweighs every possible preferred-room improvement combined (at most
    `num_sessions`, since each session contributes at most penalty 1).
    """
    return (num_sessions or 0) + 1


def faculty_time_scale(num_sessions):
    """Start-period multiplier when faculty preferences are also active.

    Invariant: one start-period unit (worth `2 * num_sessions + 1`)
    always outweighs every possible secondary improvement combined (at
    most `2 * num_sessions`: each session contributes at most
    preferred-room penalty 1 plus faculty-preference penalty 1). So
    time-compactness still dominates exactly as before, while the two
    secondary categories arbitrate among time-equal alternatives on an
    equal footing — neither can systematically dominate the other
    (each is bounded by `num_sessions` total).
    """
    return 2 * (num_sessions or 0) + 1


def _residual_assignments(assignments, locked_periods):
    """Copies of assignments with locked periods subtracted from demand.

    Returns (residual_list, skipped_ids). A fully-locked assignment
    (remaining == 0) is skipped: its locked ScheduledClass rows already
    cover it. Remaining > 0 keeps the original block_length (the tail
    session may be shorter, exactly like expand_sessions handles).
    """
    residual = []
    skipped = []
    for a in assignments:
        locked = locked_periods.get(getattr(a, "id", None), 0)
        if not locked:
            residual.append(a)
            continue
        ppw = getattr(a, "periods_per_week", 0) or 0
        remaining = ppw - locked
        if remaining < 0:
            return None, None  # caller reports infeasible
        if remaining == 0:
            skipped.append(getattr(a, "id", None))
            continue
        orig = a

        class _Residual:
            pass
        r = _Residual()
        r.id = orig.id
        r.faculty_id = orig.faculty_id
        r.subject_id = orig.subject_id
        r.session_type = orig.session_type
        r.section_id = getattr(orig, "section_id", None)
        r.lab_group_id = getattr(orig, "lab_group_id", None)
        r.periods_per_week = remaining
        r.block_length = orig.block_length
        r.lab_group = getattr(orig, "lab_group", None)
        # Phase 6F: preserve the specialization link on residual copies so
        # spec assignments stay on the spec path (group size comes from
        # membership totals, never from section size).
        r.specialization_id = getattr(orig, "specialization_id", None)
        r._orig = orig

        def _gk(self=orig):
            return orig.group_key()
        def _gl(self=orig):
            return orig.group_label()
        def _gs(self=orig):
            return orig.group_size()
        r.group_key = _gk
        r.group_label = _gl
        r.group_size = _gs
        # Keep attribute access compatible with spec expansion.
        try:
            r.specialization = getattr(orig, "specialization", None)
        except Exception:
            pass
        residual.append(r)
    return residual, skipped


def _is_spec_assignment(a):
    """Phase 6F: True when an assignment teaches a specialization."""
    try:
        return getattr(a, "specialization_id", None) is not None
    except Exception:
        return False


def _expand_spec_sessions(spec_assignments, spec_info):
    """Phase 6F: expand specialization assignments into session dicts.

    `spec_info`: {spec_id: {enrollment_id, section_ids, total_students,
    session_type, name}}. Assignments without membership (total 0 / no
    sections) produce no sessions (empty specialization during config).
    Returns (sessions, sessions_by_spec) where sessions is a flat list and
    sessions_by_spec maps spec_id -> list of session indexes into `sessions`
    in deterministic per-spec order (assignments sorted by id).
    """
    sessions = []
    by_spec = {}
    # Group assignments per spec in id order for deterministic indexing.
    per_spec = {}
    for a in spec_assignments or []:
        sid = getattr(a, "specialization_id", None)
        per_spec.setdefault(sid, []).append(a)
    for sid in sorted(per_spec, key=lambda x: (str(x))):
        info = (spec_info or {}).get(sid, {})
        total = info.get("total_students", 0) or 0
        section_ids = list(info.get("section_ids", []) or [])
        enrollment_id = info.get("enrollment_id")
        spec_name = info.get("name", str(sid))
        if not section_ids or total <= 0:
            by_spec[sid] = []
            continue
        assigns = sorted(per_spec[sid],
                         key=lambda x: getattr(x, "id", 0) or 0)
        idx_list = []
        for a in assigns:
            remaining = getattr(a, "periods_per_week", 0) or 0
            block = getattr(a, "block_length", 1) or 1
            seq = 0
            while remaining > 0:
                length = block if remaining >= block else remaining
                s_idx = len(sessions)
                # Faculty label for messages.
                try:
                    glabel = a.group_label()
                except Exception:
                    glabel = f"SPEC:{spec_name}"
                sessions.append({
                    "assignment_id": getattr(a, "id", None),
                    "spec_id": sid,
                    "enrollment_id": enrollment_id,
                    "faculty_id": getattr(a, "faculty_id", None),
                    "subject_id": getattr(a, "subject_id", None),
                    "session_type": getattr(a, "session_type", "theory"),
                    "length": length,
                    "seq": seq,
                    "spec_index": len(idx_list),
                    "group_key": f"specialization:{sid}",
                    "group_label": glabel,
                    "group_size": total,
                    "section_ids": list(section_ids),
                    "total_students": total,
                    "spec_name": spec_name,
                })
                idx_list.append(s_idx)
                remaining -= length
                seq += 1
        by_spec[sid] = idx_list
    return sessions, by_spec


def _locked_occupancy(locked_placements):
    """Fixed cell sets for locked blocks (pre-solve occupancy)."""
    room, fac, group, parent_fp, theory = set(), set(), set(), set(), set()
    for lb in locked_placements or []:
        day = lb["day"]
        for p in range(lb["start_period"], lb["start_period"] + lb["length"]):
            if lb.get("room_id") is not None:
                room.add((lb["room_id"], day, p))
            if lb.get("faculty_id") is not None:
                fac.add((lb["faculty_id"], day, p))
            if lb.get("group_key"):
                group.add((lb["group_key"], day, p))
            if lb.get("parent_section_key"):
                # Mirror schedule_validator's "__parent__:" footprint: a
                # locked lab practical blocks whole-section theory there.
                parent_fp.add((f"__parent__:{lb['parent_section_key']}", day, p))
            if lb.get("session_type") == "theory" and lb.get("group_key"):
                theory.add((lb["group_key"], day, p))
    return room, fac, group, parent_fp, theory


def run_scheduler(assignments, rooms, faculty_unavailable, days, num_periods,
                   break_after, max_consecutive, time_limit_seconds=30,
                   locked_placements=None, specialization_data=None,
                   preferred_theory_rooms=None, faculty_preferences=None):
    """
    faculty_unavailable: dict faculty_id -> set of "day:period" strings
    locked_placements: optional list of fixed dicts, each with
        {locked_block_id, assignment_id, day, start_period, length,
         room_id, faculty_id, session_type, group_key, parent_section_key}.
        They enter occupancy BEFORE solving: conflicting normal candidates
        are pruned and CP-SAT constraints count locked periods as constants.
        Locked rows are never moved, never re-emitted in `placements`.
    specialization_data: optional {spec_id: {enrollment_id, section_ids,
        total_students, session_type, name}} for Phase 6F synchronized
        cohorts. Spec assignments (TeachingAssignment.specialization_id set)
        expand via membership totals; empty specs (no sections/total 0)
        produce no sessions. Cohorts synchronize explicitly (equal day/start
        per session index); section occupancy counts once per cohort;
        HN1 counts spec theory once per section. When None/empty the
        encoding is identical to Phase 6E.
    preferred_theory_rooms: optional {section_id: room_id} home-room map
        (Phase 6I). Adds a strictly subordinate soft objective term that
        prefers a section's whole-section theory sessions in its mapped
        room. Never a constraint: candidate domains and every hard rule
        are unchanged, so feasibility is identical with or without the
        map. When None/empty the encoding (and optimum) is identical to
        the no-preference solver.
    faculty_preferences: optional iterable of duck-typed preference rows
        (Phase 6J: FacultyPreference ORM rows, dicts, or namespaces with
        faculty_id/kind/days/start_period/end_period/enabled). Only
        TIME_WINDOW and DAY_OFF_PREFERENCE rows survive normalization;
        each session placement violating its faculty's surviving prefs
        costs one soft penalty unit (binary per session, capped). Never
        a constraint: domains and hard rules are unchanged, so
        feasibility is identical with or without prefs. Specialization
        sessions score through their own faculty like any other session:
        cohort synchronization is enforced by hard equality constraints,
        so the penalty can only rank synchronized alternatives, never
        desynchronize them. Locked placements are constants (never
        variables) and are unaffected. When None/empty the model is
        identical to the Phase 6I solver (same scale, same optimum).
    Returns: (status_str, list_of_placements) where each placement is
             {assignment_id, seq, day, start_period, length, room_id}
             or (status_str, []) / (status_str, None) with a message on failure.
    """
    locked_placements = list(locked_placements or [])
    locked_ids = [lb.get("locked_block_id") for lb in locked_placements
                  if lb.get("locked_block_id") is not None]

    def _locked_infeasible(reason):
        suffix = (f" Locked block(s) {sorted(locked_ids)} make the schedule "
                  f"impossible: {reason}" if locked_ids else f" {reason}")
        return ("INFEASIBLE", [],
                "No valid timetable could be found with the current data and "
                "constraints. Try adding more rooms, relaxing faculty availability, "
                "or checking for faculty overloaded across too many sections."
                + suffix)

    # ---- Locked geometry / compatibility pre-check (re-validated here so
    # the solver never trusts unvalidated input) ----
    for lb in locked_placements:
        if not check_day_known(lb["day"], days).ok:
            return _locked_infeasible(
                f"locked block {lb.get('locked_block_id')} has unknown day "
                f"'{lb['day']}'.")
        if not check_block_geometry(lb["start_period"], lb["length"],
                                    num_periods).ok:
            return _locked_infeasible(
                f"locked block {lb.get('locked_block_id')} does not fit in "
                f"a {num_periods}-period day.")
        if not check_break_geometry(lb["start_period"], lb["length"],
                                    break_after).ok:
            return _locked_infeasible(
                f"locked block {lb.get('locked_block_id')} spans the break.")
    # ---- Locked-vs-locked self-conflict (two fixed blocks collide) ----
    _lr, _lf, _lg, _lp, _lt = _locked_occupancy(locked_placements)
    def _dup(cells):
        seen, dups = set(), set()
        for c in cells:
            if c in seen:
                dups.add(c)
            seen.add(c)
        return dups
    _all_room = [(lb["room_id"], lb["day"], p)
                 for lb in locked_placements if lb.get("room_id") is not None
                 for p in range(lb["start_period"], lb["start_period"] + lb["length"])]
    _all_fac = [(lb["faculty_id"], lb["day"], p)
                for lb in locked_placements if lb.get("faculty_id") is not None
                for p in range(lb["start_period"], lb["start_period"] + lb["length"])]
    _all_grp = [(lb["group_key"], lb["day"], p)
                for lb in locked_placements if lb.get("group_key")
                for p in range(lb["start_period"], lb["start_period"] + lb["length"])]
    if _dup(_all_room) or _dup(_all_fac) or _dup(_all_grp):
        return _locked_infeasible(
            "two locked blocks book the same room, faculty, or student "
            "group at the same time.")
    # Hierarchy among locked blocks: locked lab vs locked section theory.
    _locked_sec_theory = {(lb["group_key"], lb["day"], p)
                          for lb in locked_placements
                          if lb.get("session_type") == "theory"
                          and lb.get("group_key", "").startswith("section:")
                          for p in range(lb["start_period"],
                                         lb["start_period"] + lb["length"])}
    for lb in locked_placements:
        if lb.get("parent_section_key"):
            for p in range(lb["start_period"], lb["start_period"] + lb["length"]):
                if (lb["parent_section_key"], lb["day"], p) in _locked_sec_theory:
                    return _locked_infeasible(
                        "a locked lab practical overlaps a locked "
                        "whole-section theory class for its own section.")
    # Locked faculty availability + HN1/H12 self-violation.
    for lb in locked_placements:
        unavail = faculty_unavailable.get(lb.get("faculty_id"), set())
        if not is_faculty_available(unavail, lb["day"], lb["start_period"],
                                    lb["length"]):
            return _locked_infeasible(
                f"locked block {lb.get('locked_block_id')} falls in an "
                f"unavailable slot for its faculty.")
    _theory_by_sec_day = {}
    for (gkey, day, p) in _lt:
        _theory_by_sec_day.setdefault((gkey, day), set()).add(p)
    for (gkey, day), occ in _theory_by_sec_day.items():
        bad = check_max_two_theory(occ, num_periods, break_after, gkey, day)
        if bad:
            return _locked_infeasible(
                "locked theory blocks alone violate MAX_TWO_THEORY "
                f"({gkey} on {day}).")
    if max_consecutive and max_consecutive > 0:
        _fac_by_day = {}
        for (fid, day, p) in _lf:
            _fac_by_day.setdefault((fid, day), set()).add(p)
        for (fid, day), occ in _fac_by_day.items():
            if not check_faculty_consecutive(occ, max_consecutive,
                                             faculty_id=fid, day=day).ok:
                return _locked_infeasible(
                    f"locked blocks alone exceed the consecutive-teaching "
                    f"limit for faculty {fid} on {day}.")

    # ---- Demand subtraction: locked periods are already placed ----
    locked_periods = {}
    for lb in locked_placements:
        aid = lb.get("assignment_id")
        if aid is not None:
            locked_periods[aid] = locked_periods.get(aid, 0) + (lb["length"] or 0)
    for aid, total in locked_periods.items():
        match = next((a for a in assignments if getattr(a, "id", None) == aid), None)
        if match is None:
            return _locked_infeasible(
                f"locked block references missing assignment {aid}.")
        if total > (getattr(match, "periods_per_week", 0) or 0):
            return _locked_infeasible(
                f"locked periods ({total}) exceed assignment {aid} "
                f"periods/week ({match.periods_per_week}).")
    residual = assignments
    if locked_periods:
        residual, _ = _residual_assignments(assignments, locked_periods)
        if residual is None:
            return _locked_infeasible("locked periods exceed demand.")
        if not residual:
            return "OPTIMAL", [], None

    # ---- Phase 6F: split normal vs specialization assignments ----
    specialization_data = dict(specialization_data or {})
    normal_assignments = [a for a in residual if not _is_spec_assignment(a)]
    spec_assignments = [a for a in residual if _is_spec_assignment(a)]
    sessions = expand_sessions(normal_assignments)
    spec_sessions, spec_by_spec = _expand_spec_sessions(
        spec_assignments, specialization_data)
    # Active cohorts: enrollment -> [spec_ids with sessions].
    spec_cohorts = {}
    spec_section_union = {}  # section_id -> enrollment_id (one cohort per section)
    if spec_sessions:
        for sid, idxs in spec_by_spec.items():
            if not idxs:
                continue
            info = specialization_data.get(sid, {})
            enr = info.get("enrollment_id")
            spec_cohorts.setdefault(enr, []).append(sid)
            for sec in info.get("section_ids", []) or []:
                # Enrollment invariant is enforced at membership time; the
                # scheduler trusts it and maps each section to its cohort.
                spec_section_union.setdefault(sec, enr)
        # Sync feasibility: same session count + same (length, type) per index.
        for enr, sids in sorted(spec_cohorts.items(), key=lambda kv: str(kv[0])):
            sigs = {}
            for sid in sids:
                seq = [(spec_sessions[i]["length"],
                        spec_sessions[i]["session_type"])
                       for i in spec_by_spec.get(sid, [])]
                sigs[sid] = seq
            ref_sid = sorted(sids, key=str)[0]
            ref = sigs[ref_sid]
            for sid in sorted(sids, key=str)[1:]:
                if sigs[sid] != ref:
                    return ("INFEASIBLE", [],
                            f"SPECIALIZATION_SYNC: specialization {sid} demand "
                            f"{sigs[sid]} does not match cohort pattern {ref} "
                            f"in enrollment {enr}: all specializations must share "
                            f"identical session counts, block lengths, and session "
                            f"types.")
        # Per-cohort ordered session-index matrix for equality constraints:
        # cohort_order[enr] = {index_i: {spec_id: global_s_idx}}.
        # NOTE: spec_by_spec holds LOCAL indexes into spec_sessions; they
        # are converted to GLOBAL indexes after the combined list is built.
    cohort_order = {}
    num_normal = len(sessions)
    if spec_sessions and spec_cohorts:
        for enr, sids in spec_cohorts.items():
            sids_sorted = sorted(sids, key=str)
            n = len(spec_by_spec.get(sids_sorted[0], []))
            order = {}
            for i in range(n):
                per_spec = {}
                for sid in sids_sorted:
                    per_spec[sid] = num_normal + spec_by_spec[sid][i]
                order[i] = per_spec
            cohort_order[enr] = order
        # Convert per-spec lists to global indexes for later use.
        for sid in list(spec_by_spec.keys()):
            spec_by_spec[sid] = [num_normal + li for li in spec_by_spec[sid]]
    # Combined session list preserves 6E behavior when no specs exist.
    sessions = list(sessions) + list(spec_sessions)
    is_spec_idx = [False] * num_normal + [True] * len(spec_sessions)
    if not sessions:
        return "NO_SESSIONS", [], "No teaching assignments to schedule."

    locked_room, locked_fac, locked_group, locked_parent_fp, locked_theory = \
        _locked_occupancy(locked_placements)
    # Per (group_key, day) locked-theory period sets for HN1 pruning.
    locked_theory_day = {}
    for (gkey, day, p) in locked_theory:
        locked_theory_day.setdefault((gkey, day), set()).add(p)
    locked_fac_day = {}
    for (fid, day, p) in locked_fac:
        locked_fac_day.setdefault((fid, day), set()).add(p)

    model = cp_model.CpModel()

    # x[(s_idx, day, start, room_id)] = BoolVar
    x = {}
    session_options = [[] for _ in sessions]  # list of (day,start,room_id) per session

    def _conflicts_locked(sess, day, start, room_id):
        length = sess["length"]
        # Phase 6F: specialization sessions occupy every participating
        # section (conservative section-level model).
        spec_sections = sess.get("section_ids") or []
        for p in range(start, start + length):
            if (room_id, day, p) in locked_room:
                return True
            if (sess["faculty_id"], day, p) in locked_fac:
                return True
            if spec_sections:
                for sec_id in spec_sections:
                    if (f"section:{sec_id}", day, p) in locked_group:
                        return True
                    if (f"__parent__:section:{sec_id}", day, p) in locked_parent_fp:
                        return True
                # Spec group keys never collide with locked normal groups;
                # room/faculty/section checks above are the footprint.
                continue
            if (sess["group_key"], day, p) in locked_group:
                return True
            parent = sess.get("parent_section_key")
            if parent and (parent, day, p) in _locked_sec_theory_cells():
                return True
            if sess["session_type"] == "theory" and sess["group_key"].startswith("section:"):
                if (f"__parent__:{sess['group_key']}", day, p) in locked_parent_fp:
                    return True
        return False

    def _locked_sec_theory_cells():
        return _locked_sec_theory

    def _spec_hn1_prune(sess, day, start):
        """Phase 6F: prune a spec theory candidate when candidate + locked
        theory alone already covers a 3-window for ANY participating
        section (unavoidable in any solution containing it)."""
        if sess.get("session_type") != "theory":
            return False
        for sec_id in sess.get("section_ids", []) or []:
            combo = (set(locked_theory_day.get((f"section:{sec_id}", day), set()))
                     | set(range(start, start + sess["length"])))
            if check_max_two_theory(combo, num_periods, break_after,
                                    sess.get("group_label", "?"), day):
                return True
        return False

    for s_idx, sess in enumerate(sessions):
        rooms_ok = compatible_rooms(sess, rooms)
        if not rooms_ok:
            if is_spec_idx[s_idx]:
                return ("INFEASIBLE", [],
                        f"SPECIALIZATION_CAPACITY: no compatible room exists "
                        f"for specialization '{sess.get('spec_name', '?')}' "
                        f"({sess['session_type']}, {sess['group_size']} students). "
                        f"Add a {'lab' if sess['session_type']=='practical' else 'theory'} "
                        f"room with enough capacity.")
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
                # Phase 6E: HN1 pruning — candidate + locked theory alone
                # covering a full 3-window is unavoidable in any solution
                # containing this candidate (more sessions only extend the
                # streak), so drop it. Wider violations stay as CP-SAT
                # constraints below.
                if (locked_placements and sess["session_type"] == "theory"
                        and sess["group_key"].startswith("section:")):
                    combo = (set(locked_theory_day.get((sess["group_key"], day), set()))
                             | set(range(start, start + sess["length"])))
                    if check_max_two_theory(combo, num_periods, break_after,
                                            sess["group_label"], day):
                        continue
                # Phase 6F: same pruning for specialization theory, once
                # per participating section (never multiply-counted).
                if (locked_placements and is_spec_idx[s_idx]
                        and sess["session_type"] == "theory"):
                    if _spec_hn1_prune(sess, day, start):
                        continue
                # Phase 6E: H12 pruning — candidate + locked faculty run
                # already exceeding the limit can never be repaired.
                if max_consecutive and max_consecutive > 0 and locked_placements:
                    fbase = set(locked_fac_day.get((sess["faculty_id"], day), set()))
                    fbase.update(range(start, start + sess["length"]))
                    if max_run_length(fbase) > max_consecutive:
                        continue
                for room in rooms_ok:
                    if locked_placements:
                        clash = False
                        for p in range(start, start + sess["length"]):
                            if (room.id, day, p) in locked_room:
                                clash = True
                                break
                        if clash:
                            continue
                        if _conflicts_locked(sess, day, start, room.id):
                            continue
                    var = model.NewBoolVar(f"x_{s_idx}_{day}_{start}_{room.id}")
                    x[(s_idx, day, start, room.id)] = var
                    session_options[s_idx].append((day, start, room.id))

    for s_idx, sess in enumerate(sessions):
        opts = session_options[s_idx]
        if not opts:
            if is_spec_idx[s_idx]:
                msg = (f"SPECIALIZATION_OVERLAP: specialization "
                       f"'{sess.get('spec_name', '?')}' "
                       f"(assignment {sess['assignment_id']}) has no legal "
                       f"day/period/room slot — check faculty availability, "
                       f"rooms, locked blocks, and participating-section "
                       f"occupancy.")
            else:
                msg = (f"'{sess['group_label']}' ({sess['subject_id']}) has no legal "
                       f"day/period/room slot at all — check faculty availability and room setup.")
            if locked_ids:
                msg += (f" Locked block(s) {sorted(locked_ids)} leave no feasible "
                        f"placement for assignment {sess['assignment_id']}.")
            return "INFEASIBLE", [], msg
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
        if sess.get("parent_section_key"):
            parent_of[sess["group_key"]] = sess["parent_section_key"]
    for child_key, parent_key in parent_of.items():
        dp_keys = {k[1:] for k in group_occ if k[0] == child_key} | {k[1:] for k in group_occ if k[0] == parent_key}
        for (d, p) in dp_keys:
            child_vars = group_occ.get((child_key, d, p), [])
            parent_vars = group_occ.get((parent_key, d, p), [])
            if child_vars and parent_vars:
                model.Add(sum(child_vars) + sum(parent_vars) <= 1)

    # ---- Phase 6F: specialization synchronization + section occupancy ----
    # Explicit equality (never hope independent choices coincide):
    # start(Cyber,i) = start(AI,i) = start(FullStack,i) and day equal,
    # lengths already validated equal. Rooms/faculty may differ.
    if cohort_order:
        for enr, order in cohort_order.items():
            for i, per_spec in order.items():
                lengths = {sessions[gidx]["length"] for gidx in per_spec.values()}
                if len(lengths) != 1:
                    return ("INFEASIBLE", [],
                            f"SPECIALIZATION_SYNC: block lengths differ within "
                            f"cohort {enr} session {i}: {sorted(lengths)}.")
                all_ds = set()
                for gidx in per_spec.values():
                    for (d, st, _r) in session_options[gidx]:
                        all_ds.add((d, st))
                first_sid = sorted(per_spec, key=str)[0]
                first_gidx = per_spec[first_sid]
                for (d, st) in sorted(all_ds):
                    first_vars = [x[(first_gidx, d, st, r)]
                                  for (dd, ss, r) in session_options[first_gidx]
                                  if dd == d and ss == st
                                  and (first_gidx, d, st, r) in x]
                    for sid in sorted(per_spec, key=str)[1:]:
                        gidx = per_spec[sid]
                        other_vars = [x[(gidx, d, st, r)]
                                      for (dd, ss, r) in session_options[gidx]
                                      if dd == d and ss == st
                                      and (gidx, d, st, r) in x]
                        if not first_vars and not other_vars:
                            continue
                        model.Add(sum(first_vars) == sum(other_vars))
        # Cohort internal non-overlap + conservative section blocking.
        # A synchronized slot blocks every participating section once
        # (never triple-counted): representative indicator per (cohort,i).
        for enr, order in cohort_order.items():
            sids_sorted = sorted(order[0].keys(), key=str) if order else []
            if not sids_sorted:
                continue
            rep_by_i = {i: per_spec[sids_sorted[0]]
                        for i, per_spec in order.items()}
            sections_in_cohort = sorted(
                sec for sec, e in spec_section_union.items() if e == enr)
            # Internal: at most one synchronized session covers a cell.
            for d in days:
                for p in range(num_periods):
                    covering = []
                    for i, rep_idx in rep_by_i.items():
                        rep_len = sessions[rep_idx]["length"]
                        for (od, st, r) in session_options[rep_idx]:
                            if od != d:
                                continue
                            if st <= p < st + rep_len:
                                covering.append(x[(rep_idx, od, st, r)])
                    if len(covering) > 1:
                        model.Add(sum(covering) <= 1)
            # Section blocking: normal section + cohort <= 1; each lab-group
            # of a participating section + cohort <= 1 (parallel labs of the
            # same section stay allowed when no specialization runs).
            lab_parent = {}  # lab group_key -> parent section id (int)
            for child_key, parent_key in parent_of.items():
                if parent_key.startswith("section:"):
                    try:
                        pid = int(parent_key.split(":", 1)[1])
                    except (ValueError, IndexError):
                        continue
                    lab_parent[child_key] = pid
            for sec_id in sections_in_cohort:
                sec_key = f"section:{sec_id}"
                for d in days:
                    for p in range(num_periods):
                        cohort_vars = []
                        for i, rep_idx in rep_by_i.items():
                            rep_len = sessions[rep_idx]["length"]
                            for (od, st, r) in session_options[rep_idx]:
                                if od != d:
                                    continue
                                if st <= p < st + rep_len:
                                    cohort_vars.append(x[(rep_idx, od, st, r)])
                        if not cohort_vars:
                            continue
                        sec_vars = group_occ.get((sec_key, d, p), [])
                        if sec_vars:
                            model.Add(sum(sec_vars) + sum(cohort_vars) <= 1)
                        elif len(cohort_vars) > 1:
                            # No normal class here, but keep internal guard
                            # (already added above; skip duplicate).
                            pass
                        for lab_key, pid in lab_parent.items():
                            if pid != sec_id:
                                continue
                            lab_vars = group_occ.get((lab_key, d, p), [])
                            if lab_vars:
                                model.Add(sum(lab_vars) + sum(cohort_vars) <= 1)

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
                    # Phase 6E: locked periods count as constants in the
                    # same window (pre-solve occupancy, never moved).
                    locked_n = sum(
                        1 for p in range(p0, p0 + window)
                        if (fid, d, p) in locked_fac) if locked_placements else 0
                    if terms:
                        if locked_n:
                            model.Add(sum(terms) + locked_n <= max_consecutive)
                        else:
                            model.Add(sum(terms) <= max_consecutive)
                    elif locked_n > max_consecutive:
                        return _locked_infeasible(
                            f"locked blocks exceed the consecutive-teaching "
                            f"limit for faculty {fid} on {d}.")

    # ---- HN1: max two consecutive theory periods per section per day ----
    # Logical counterpart: schedule_rules.check_max_two_theory. For every
    # section, day, and 3-period in-segment window: sum over theory-session
    # candidate booleans of (overlap-period count * boolean) <= 2.
    # Practical sessions contribute 0 and are excluded; each placement
    # boolean appears once per window with its period-weighted coefficient.
    # Phase 6F: specialization theory contributes ONCE per section per
    # period (representative indicator, never multiply-counted); practicals
    # contribute 0. Breaks/free periods reset via windows (same as normal).
    theory_by_section = {}
    for s_idx, sess in enumerate(sessions):
        if sess["session_type"] != "theory":
            continue
        if is_spec_idx[s_idx]:
            continue  # spec theory handled via representative below
        theory_by_section.setdefault(sess["group_key"], []).append(s_idx)
    # Representative spec-theory sessions per cohort/index (for HN1 terms).
    spec_theory_rep = {}  # (enrollment, section_id) -> [(rep_idx, length)]
    if cohort_order:
        for enr, order in cohort_order.items():
            sids_sorted = sorted(order[0].keys(), key=str) if order else []
            if not sids_sorted:
                continue
            sections_in_cohort = [sec for sec, e in spec_section_union.items()
                                  if e == enr]
            for i, per_spec in order.items():
                rep_idx = per_spec[sids_sorted[0]]
                if sessions[rep_idx]["session_type"] != "theory":
                    continue
                rep_len = sessions[rep_idx]["length"]
                for sec_id in sections_in_cohort:
                    spec_theory_rep.setdefault((enr, sec_id), []).append(
                        (rep_idx, rep_len))
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
                # Phase 6F: add the cohort's spec-theory footprint once.
                if sec_key.startswith("section:"):
                    try:
                        _sid = int(sec_key.split(":", 1)[1])
                    except (ValueError, IndexError):
                        _sid = None
                    if _sid is not None:
                        _enr = spec_section_union.get(_sid)
                        if _enr is not None:
                            for (rep_idx, rep_len) in spec_theory_rep.get(
                                    (_enr, _sid), []):
                                for (od, start, r) in session_options[rep_idx]:
                                    if od != d:
                                        continue
                                    coeff = overlap_count(start, rep_len, window)
                                    if coeff:
                                        terms.append(
                                            coeff * x[(rep_idx, od, start, r)])
                # Phase 6E: locked theory periods in this window count as
                # constants (pre-solve occupancy, never moved).
                locked_n = sum(
                    1 for p in window
                    if (sec_key, d, p) in locked_theory) if locked_placements else 0
                if terms:
                    if locked_n:
                        model.Add(sum(terms) + locked_n <= 2)
                    else:
                        model.Add(sum(terms) <= 2)
                elif locked_n > 2:
                    return _locked_infeasible(
                        f"locked theory blocks violate MAX_TWO_THEORY "
                        f"({sec_key} on {d}, periods {list(window)}).")
    # Sections whose only theory is specialization theory (no normal theory
    # entry above) still need HN1 windows over spec + locked occupancy.
    if spec_theory_rep:
        covered_secs = {k for k in theory_by_section}
        for (enr, sec_id), reps in sorted(spec_theory_rep.items()):
            sec_key = f"section:{sec_id}"
            if sec_key in covered_secs:
                continue  # already constrained above (normal + spec)
            for d in days:
                for window in hn1_windows(num_periods, break_after):
                    terms = []
                    for (rep_idx, rep_len) in reps:
                        for (od, start, r) in session_options[rep_idx]:
                            if od != d:
                                continue
                            coeff = overlap_count(start, rep_len, window)
                            if coeff:
                                terms.append(coeff * x[(rep_idx, od, start, r)])
                    locked_n = sum(
                        1 for p in window
                        if (sec_key, d, p) in locked_theory) if locked_placements else 0
                    if terms:
                        if locked_n:
                            model.Add(sum(terms) + locked_n <= 2)
                        else:
                            model.Add(sum(terms) <= 2)
                    elif locked_n > 2:
                        return _locked_infeasible(
                            f"locked theory blocks violate MAX_TWO_THEORY "
                            f"({sec_key} on {d}, periods {list(window)}).")

    # ---- Soft objective: minimize start periods (compact + early-finish),
    # with strictly subordinate preferred-theory-room (6I) and faculty
    # preference (6J) tie-breaks ----
    # Without faculty prefs the scale is #sessions + 1 (see
    # preferred_time_scale): one start-period unit always outweighs every
    # possible preferred-room improvement combined, so time-compactness
    # dominates exactly as before and the room preference only arbitrates
    # among time-equal alternatives. With faculty prefs the scale is
    # 2 * #sessions + 1 (see faculty_time_scale): one start-period unit
    # outweighs room + faculty improvements combined, and the two
    # secondary categories share equal footing (each bounded by
    # #sessions total). Penalties are 0/1 per placement (whole-section
    # theory with a mapped preference only, 0 elsewhere; faculty penalty
    # via faculty_time_penalty). Domains and hard constraints are
    # untouched: feasibility is identical with or without either map,
    # and locked placements (constants, never variables) are unaffected.
    preferred_map = normalize_preferred_rooms(preferred_theory_rooms, rooms)
    faculty_map = normalize_faculty_preferences(
        faculty_preferences, days, num_periods)
    if faculty_map:
        time_scale = faculty_time_scale(len(sessions))
    else:
        time_scale = preferred_time_scale(len(sessions))
    objective_terms = []
    for s_idx, sess in enumerate(sessions):
        for (d, start, r) in session_options[s_idx]:
            # squared-ish weighting via linear scale keeps it simple & fast for CP-SAT
            objective_terms.append(
                (start * time_scale
                 + preferred_room_penalty(sess, r, preferred_map)
                 + faculty_time_penalty(sess.get("faculty_id"), d, start,
                                        sess["length"], faculty_map))
                * x[(s_idx, d, start, r)])
    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        msg = ("No valid timetable could be found with the current data and "
               "constraints. Try adding more rooms, relaxing faculty availability, "
               "or checking for faculty overloaded across too many sections.")
        if locked_ids:
            msg += (f" Locked block(s) {sorted(locked_ids)} are part of the "
                    f"conflict and were not moved.")
        return "INFEASIBLE", [], msg

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
