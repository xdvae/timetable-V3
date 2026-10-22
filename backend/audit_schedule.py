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

Phase 6D.2: this script is STRICTLY READ-ONLY. It never imports
backend.app (whose import runs init_db()/init_admin_from_env() and can
create tables + insert the admin user), never calls create_all(), never
runs migrations, and opens SQLite in read-only URI mode so the engine
itself refuses any write. It reads through stdlib sqlite3 only (no ORM),
so a pre-Phase-6C database without the additive columns/tables is still
auditable on its legacy columns; a missing-6C schema is reported as an
explicit NOTE, never auto-repaired.

Usage (from the repository root):
    python -m backend.audit_schedule [--db PATH]

Exit codes: 0 = no problems, 1 = problems found, 2 = usage/schema error.
"""
import argparse
import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import schedule_rules as rules

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "instance", "timetable.db")

# Core tables/columns the audit reads. Everything here exists both
# pre- and post-Phase-6C, so legacy databases stay auditable.
REQUIRED_TABLES = ("config", "scheduled_class", "teaching_assignment",
                   "room", "faculty", "section", "lab_group", "subject")

# Phase 6C additive footprint. Absence is NOT fatal (the audit never reads
# these fields); it is reported explicitly and no migration is performed.
SIXC_COLUMNS = (("scheduled_class", "is_locked"),
                ("scheduled_class", "slot_id"),
                ("scheduled_class", "locked_block_id"),
                ("section", "preferred_theory_room_id"))
SIXC_TABLES = ("specialization", "specialization_membership",
               "specialization_slot", "locked_block", "faculty_preference")


def open_readonly(db_path):
    """Open SQLite strictly read-only: no CREATE/INSERT/UPDATE/DELETE is
    possible through the returned connection (the engine rejects writes)."""
    abs_path = os.path.abspath(db_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")
    # mode=ro: the open itself fails if the file is not a readable database.
    return sqlite3.connect(f"file:{abs_path}?mode=ro", uri=True)


def _table_cols(conn, table):
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def check_required_schema(conn):
    """Return a list of human-readable schema problems (empty == usable).

    Only core audit inputs are required. Phase 6C additions are reported
    separately as a NOTE by report_6c_footprint(), never as an error.
    """
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    problems = []
    for t in REQUIRED_TABLES:
        if t not in tables:
            problems.append(f"missing required table: {t}")
    if problems:
        return problems
    need = {
        "config": {"working_days", "periods", "break_after_periods",
                   "max_consecutive_teaching"},
        "scheduled_class": {"assignment_id", "day", "start_period",
                            "length", "room_id"},
        "teaching_assignment": {"faculty_id", "subject_id", "session_type",
                                "section_id", "lab_group_id",
                                "periods_per_week", "block_length"},
        "room": {"name", "room_type", "capacity"},
        "section": {"name", "student_count"},
        "lab_group": {"section_id", "name", "student_count"},
        "subject": {"name"},
        "faculty": {"name"},
    }
    for table, cols in need.items():
        missing = cols - _table_cols(conn, table)
        if missing:
            problems.append(f"table {table} is missing columns: "
                            f"{sorted(missing)}")
    return problems


def report_6c_footprint(conn):
    """Explicit NOTE when the Phase 6C additive schema is absent.

    Returns the note string (empty when the footprint is present). Never
    migrates, creates, or repairs anything.
    """
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing_cols = [f"{t}.{c}" for t, c in SIXC_COLUMNS
                    if t in tables and c not in _table_cols(conn, t)]
    missing_tables = [t for t in SIXC_TABLES if t not in tables]
    if not missing_cols and not missing_tables:
        return ""
    bits = []
    if missing_cols:
        bits.append("columns: " + ", ".join(sorted(missing_cols)))
    if missing_tables:
        bits.append("tables: " + ", ".join(sorted(missing_tables)))
    return ("NOTE: Database schema is missing Phase 6C additive schema "
            f"({'; '.join(bits)}). Running legacy-compatible audit on "
            "pre-migration columns only; no migration was performed.")


def load_snapshot(conn):
    """Read every audit input with SELECTs only. Returns a plain-dict
    snapshot (no ORM objects, so pre-6C rows map cleanly)."""
    cfg = conn.execute(
        "SELECT working_days, periods, break_after_periods, "
        "max_consecutive_teaching FROM config LIMIT 1").fetchone()
    if cfg is None:
        raise ValueError("config table has no rows")
    days = [d.strip() for d in (cfg[0] or "").split(",") if d.strip()]
    periods = [p.strip() for p in (cfg[1] or "").split("|") if p.strip()]

    rooms = {}
    for r in conn.execute(
            'SELECT id, name, room_type, capacity, equipment_count '
            'FROM room'):
        rooms[r[0]] = {"name": r[1], "room_type": r[2], "capacity": r[3],
                       "equipment_count": r[4]}

    faculty_names = {r[0]: r[1] for r in conn.execute(
        "SELECT id, name FROM faculty")}
    subject_names = {r[0]: r[1] for r in conn.execute(
        "SELECT id, name FROM subject")}
    sec_names = {}
    sec_sizes = {}
    for r in conn.execute("SELECT id, name, student_count FROM section"):
        sec_names[r[0]] = r[1]
        sec_sizes[r[0]] = r[2] or 0
    lg_names, lg_sizes, lg_sections = {}, {}, {}
    for r in conn.execute(
            "SELECT id, section_id, name, student_count FROM lab_group"):
        lg_sections[r[0]] = r[1]
        lg_names[r[0]] = r[2]
        lg_sizes[r[0]] = r[3] or 0

    # Phase 6E: faculty unavailability is needed to re-validate locked
    # placements (read-only SELECT; absent column -> treat as available).
    faculty_unavailable = {}
    try:
        for r in conn.execute("SELECT id, unavailable_slots FROM faculty"):
            slots = {(t.strip()) for t in (r[1] or "").split(",") if t.strip()}
            faculty_unavailable[r[0]] = slots
    except sqlite3.OperationalError:
        faculty_unavailable = {}

    # Phase 6F: specialization link on assignments (absent column ->
    # legacy-compatible None). Spec group size comes from membership totals
    # (loaded below), never from section size.
    try:
        _ta_cols = _table_cols(conn, "teaching_assignment")
        _has_spec_col = "specialization_id" in _ta_cols
    except Exception:
        _has_spec_col = False
    # Section -> enrollment for cross-cohort validation (read-only).
    sec_enrollment = {}
    try:
        for r in conn.execute("SELECT id, enrollment_id FROM section"):
            sec_enrollment[r[0]] = r[1]
    except sqlite3.OperationalError:
        sec_enrollment = {}

    assignments = {}
    if _has_spec_col:
        _rows = conn.execute(
            "SELECT id, faculty_id, subject_id, session_type, section_id, "
            "lab_group_id, periods_per_week, block_length, specialization_id "
            "FROM teaching_assignment ORDER BY id")
    else:
        _rows = conn.execute(
            "SELECT id, faculty_id, subject_id, session_type, section_id, "
            "lab_group_id, periods_per_week, block_length "
            "FROM teaching_assignment ORDER BY id")
    for r in _rows:
        aid, fac_id, subj_id, stype, sec_id, lg_id = r[0:6]
        spec_id = r[8] if (_has_spec_col and len(r) > 8) else None
        if spec_id is not None:
            group_key = f"specialization:{spec_id}"
            group_label = f"specialization:{spec_id}"
            group_size = 0  # filled from membership totals below
        elif stype == "practical" and lg_id is not None:
            group_key = f"labgroup:{lg_id}"
            group_label = lg_names.get(lg_id, "?")
            group_size = lg_sizes.get(lg_id, 0)
        else:
            group_key = f"section:{sec_id}"
            group_label = sec_names.get(sec_id, "?")
            group_size = sec_sizes.get(sec_id, 0)
        assignments[aid] = {
            "id": aid, "faculty_id": fac_id, "subject_id": subj_id,
            "subject_name": subject_names.get(subj_id, "?"),
            "session_type": stype, "section_id": sec_id,
            "lab_group_id": lg_id, "group_key": group_key,
            "group_label": group_label, "group_size": group_size,
            "specialization_id": spec_id,
        }

    # Phase 6E: lock columns + locked_block rows when the additive schema
    # is present (missing table/columns -> legacy-compatible empty lists).
    sc_cols = _table_cols(conn, "scheduled_class")
    has_lock_cols = {"is_locked", "locked_block_id"} <= sc_cols
    classes = []
    try:
        if has_lock_cols:
            rows = conn.execute(
                "SELECT id, assignment_id, day, start_period, length, room_id, "
                "is_locked, locked_block_id FROM scheduled_class ORDER BY id")
            for r in rows:
                classes.append({"id": r[0], "assignment_id": r[1], "day": r[2],
                                "start_period": r[3], "length": r[4],
                                "room_id": r[5], "is_locked": bool(r[6]),
                                "locked_block_id": r[7]})
        else:
            raise sqlite3.OperationalError("no lock columns")
    except sqlite3.OperationalError:
        for r in conn.execute(
                "SELECT id, assignment_id, day, start_period, length, room_id "
                "FROM scheduled_class ORDER BY id"):
            classes.append({"id": r[0], "assignment_id": r[1], "day": r[2],
                            "start_period": r[3], "length": r[4],
                            "room_id": r[5], "is_locked": False,
                            "locked_block_id": None})

    locked_blocks = []
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "locked_block" in tables:
        lb_cols = _table_cols(conn, "locked_block")
        has_assign = "assignment_id" in lb_cols
        try:
            if has_assign:
                rows = conn.execute(
                    "SELECT id, kind, assignment_id, subject_id, faculty_id, "
                    "section_id, lab_group_id, day, start_period, length, "
                    "room_id, room_locked, department, is_external "
                    "FROM locked_block ORDER BY id")
                for r in rows:
                    locked_blocks.append({
                        "id": r[0], "kind": r[1], "assignment_id": r[2],
                        "subject_id": r[3], "faculty_id": r[4],
                        "section_id": r[5], "lab_group_id": r[6],
                        "day": r[7], "start_period": r[8], "length": r[9],
                        "room_id": r[10], "room_locked": bool(r[11]),
                        "department": r[12], "is_external": bool(r[13])})
            else:
                rows = conn.execute(
                    "SELECT id, kind, subject_id, faculty_id, section_id, "
                    "lab_group_id, day, start_period, length, room_id, "
                    "room_locked, department, is_external "
                    "FROM locked_block ORDER BY id")
                for r in rows:
                    locked_blocks.append({
                        "id": r[0], "kind": r[1], "assignment_id": None,
                        "subject_id": r[2], "faculty_id": r[3],
                        "section_id": r[4], "lab_group_id": r[5],
                        "day": r[6], "start_period": r[7], "length": r[8],
                        "room_id": r[9], "room_locked": bool(r[10]),
                        "department": r[11], "is_external": bool(r[12])})
        except sqlite3.OperationalError:
            locked_blocks = []

    # Phase 6F: specializations / memberships / slots (read-only SELECTs;
    # absent tables -> legacy-compatible empty lists, never a migration).
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    specializations, memberships, spec_slots = [], [], []
    if "specialization" in tables:
        try:
            for r in conn.execute(
                    "SELECT id, name, enrollment_id, session_type, "
                    "block_length, periods_per_week FROM specialization "
                    "ORDER BY id"):
                specializations.append({
                    "id": r[0], "name": r[1], "enrollment_id": r[2],
                    "session_type": r[3], "block_length": r[4],
                    "periods_per_week": r[5]})
        except sqlite3.OperationalError:
            specializations = []
    if "specialization_membership" in tables:
        try:
            for r in conn.execute(
                    "SELECT id, specialization_id, section_id, student_count "
                    "FROM specialization_membership ORDER BY id"):
                memberships.append({
                    "id": r[0], "specialization_id": r[1],
                    "section_id": r[2], "student_count": r[3]})
        except sqlite3.OperationalError:
            memberships = []
    if "specialization_slot" in tables:
        try:
            for r in conn.execute(
                    "SELECT id, specialization_id, day, start_period, length "
                    "FROM specialization_slot ORDER BY id"):
                spec_slots.append({
                    "id": r[0], "specialization_id": r[1], "day": r[2],
                    "start_period": r[3], "length": r[4]})
        except sqlite3.OperationalError:
            spec_slots = []
    # Fill spec group sizes from membership totals (source of truth for
    # room-capacity checks below).
    _totals = {}
    for m in memberships:
        _totals[m["specialization_id"]] = _totals.get(
            m["specialization_id"], 0) + (m["student_count"] or 0)
    for a in assignments.values():
        if a.get("specialization_id") is not None:
            tot = _totals.get(a["specialization_id"], 0)
            a["group_size"] = tot
            a["group_label"] = next(
                (s["name"] for s in specializations
                 if s["id"] == a["specialization_id"]),
                f"specialization:{a['specialization_id']}")

    # ScheduledClass slot link (absent column -> None, legacy-compatible).
    try:
        _sc_cols = _table_cols(conn, "scheduled_class")
        _has_slot = "slot_id" in _sc_cols
    except Exception:
        _has_slot = False
    if _has_slot:
        try:
            _slot_by_id = {sc["id"]: sc for sc in classes}
            for r in conn.execute(
                    "SELECT id, slot_id FROM scheduled_class ORDER BY id"):
                if r[0] in _slot_by_id:
                    _slot_by_id[r[0]]["slot_id"] = r[1]
        except sqlite3.OperationalError:
            pass
        for sc in classes:
            sc.setdefault("slot_id", None)
    else:
        for sc in classes:
            sc.setdefault("slot_id", None)

    return {
        "days": days,
        "num_periods": len(periods),
        "break_after": cfg[2],
        "max_consecutive": cfg[3],
        "rooms": rooms,
        "faculty_names": faculty_names,
        "faculty_unavailable": faculty_unavailable,
        "sec_names": sec_names,
        "sec_sizes": sec_sizes,
        "sec_enrollment": sec_enrollment,
        "labgroup_section": lg_sections,
        "assignments": assignments,
        "classes": classes,
        "locked_blocks": locked_blocks,
        "has_lock_schema": has_lock_cols and "locked_block" in tables,
        "specializations": specializations,
        "memberships": memberships,
        "spec_slots": spec_slots,
        "has_spec_schema": ("specialization" in tables
                            and "specialization_membership" in tables
                            and "specialization_slot" in tables),
    }


def audit_snapshot(snap):
    """Pure audit over the snapshot. Returns (problems, notes)."""
    break_after = snap["break_after"]
    max_consec = snap["max_consecutive"]
    problems = []
    notes = []
    room_occ = {}
    fac_occ = {}
    group_occ = {}
    # cell -> human-readable assignment descriptions (for messages only;
    # the validity decision comes from schedule_rules).
    cell_desc = defaultdict(list)
    # Phase 6E: cell -> scheduled-class ids that are locked (for
    # LOCKED_BLOCK_CONFLICT attribution; read-only bookkeeping).
    cell_locked = defaultdict(list)

    def _describe(a):
        return (f"assignment {a['id']} ({a['subject_name']}, "
                f"{a['group_label']})")

    for sc in snap["classes"]:
        a = snap["assignments"].get(sc["assignment_id"])
        if a is None:
            problems.append(
                f"ORPHAN CLASS: scheduled class {sc['id']} references "
                f"missing assignment {sc['assignment_id']}.")
            continue
        periods = list(rules.covers(sc["start_period"], sc["length"]))

        # H10: break geometry (shared rule).
        res = rules.check_break_geometry(sc["start_period"], sc["length"],
                                         break_after,
                                         group_label=a["group_label"])
        if not res.ok:
            problems.append(
                f"BREAK VIOLATION: {_describe(a)} on {sc['day']} spans across "
                f"the break (starts {sc['start_period']}, length {sc['length']}).")

        # H2+H3+H4: room compatibility (shared rule).
        room = snap["rooms"].get(sc["room_id"])
        if room is None:
            problems.append(
                f"ROOM VIOLATION: {_describe(a)} references missing room "
                f"{sc['room_id']}.")
        else:
            res = rules.check_room_compatible(
                room["room_type"], room["capacity"],
                room["equipment_count"],
                a["session_type"], a["group_size"],
                room_name=room["name"], group_label=a["group_label"])
            if not res.ok:
                kind = {"ROOM_CAPACITY": "CAPACITY",
                        "ROOM_TYPE_MISMATCH": "ROOM TYPE",
                        "ROOM_EQUIPMENT": "EQUIPMENT"}.get(res.code, "ROOM")
                problems.append(
                    f"{kind} VIOLATION: {res.message} — {_describe(a)}.")

        for p in periods:
            rules.add_placement(room_occ, sc["room_id"], sc["day"], p, 1)
            rules.add_placement(fac_occ, a["faculty_id"], sc["day"], p, 1)
            rules.add_placement(group_occ, a["group_key"], sc["day"], p, 1)
            desc = _describe(a)
            cell_desc[("room", sc["room_id"], sc["day"], p)].append(desc)
            cell_desc[("faculty", a["faculty_id"], sc["day"], p)].append(desc)
            cell_desc[("group", a["group_key"], sc["day"], p)].append(desc)
            if sc.get("is_locked"):
                cell_locked[("room", sc["room_id"], sc["day"], p)].append(sc["id"])
                cell_locked[("faculty", a["faculty_id"], sc["day"], p)].append(sc["id"])
                cell_locked[("group", a["group_key"], sc["day"], p)].append(sc["id"])

    def check_overlap(occ, code, label, kind):
        for res in rules.check_no_overlap(occ, code, label):
            key, day, period = (res.details["resource"],
                               res.details["day"], res.details["period"])
            ids = "; ".join(cell_desc[(kind, key, day, period)])
            problems.append(f"{label} DOUBLE-BOOKED: {(key, day)} at period {period} -> {ids}")
            # Phase 6E: attribute overlaps touching an immutable block.
            locked_ids = cell_locked.get((kind, key, day, period), [])
            if locked_ids:
                problems.append(
                    f"LOCKED_BLOCK_CONFLICT: locked class(es) {sorted(locked_ids)} "
                    f"overlap {label.lower()} {(key, day)} at period {period} "
                    f"({code}).")

    check_overlap(room_occ, "ROOM_CONFLICT", "ROOM", "room")
    check_overlap(fac_occ, "FACULTY_CONFLICT", "FACULTY", "faculty")
    check_overlap(group_occ, "GROUP_CONFLICT", "STUDENT GROUP", "group")

    # H8: hierarchical check via the shared rule — a lab group's students are
    # a subset of their parent section, so a lab-group session must never
    # overlap a whole-section theory session.
    lg_sections = snap["labgroup_section"]
    section_theory_periods = defaultdict(set)   # section_id -> {(day, period)}
    labgroup_periods = defaultdict(set)         # lab_group_id -> {(day, period)}
    # Normal section/lab occupancy for specialization overlap checks.
    section_periods = defaultdict(set)          # section_id -> {(day, period)}
    for sc in snap["classes"]:
        a = snap["assignments"].get(sc["assignment_id"])
        if a is None:
            continue
        periods = rules.covers(sc["start_period"], sc["length"])
        if a.get("specialization_id") is not None:
            continue  # spec footprint handled deduped below
        if a["session_type"] == "theory" and a["section_id"]:
            for p in periods:
                section_theory_periods[a["section_id"]].add((sc["day"], p))
                section_periods[a["section_id"]].add((sc["day"], p))
        elif a["session_type"] == "practical" and a["lab_group_id"]:
            for p in periods:
                labgroup_periods[a["lab_group_id"]].add((sc["day"], p))
        elif a["section_id"]:
            for p in periods:
                section_periods[a["section_id"]].add((sc["day"], p))
    # Phase 6F: specialization theory contributes ONCE per section (deduped
    # per synchronized group); practicals never count toward HN1.
    _spec_groups = {}  # (enrollment, day, start, length) -> {sections, theory_sections}
    _spec_by_id = {s["id"]: s for s in snap.get("specializations", []) or []}
    _mem_by_spec = defaultdict(list)
    for m in snap.get("memberships", []) or []:
        _mem_by_spec[m["specialization_id"]].append(m)
    for sc in snap["classes"]:
        a = snap["assignments"].get(sc["assignment_id"])
        if a is None or a.get("specialization_id") is None:
            continue
        spec_id = a["specialization_id"]
        spec = _spec_by_id.get(spec_id, {})
        enr = spec.get("enrollment_id")
        key = (enr, sc["day"], sc["start_period"], sc["length"])
        g = _spec_groups.setdefault(key, {"sections": set(),
                                          "theory_sections": set()})
        for m in _mem_by_spec.get(spec_id, []):
            g["sections"].add(m["section_id"])
            if a.get("session_type") == "theory":
                g["theory_sections"].add(m["section_id"])
    for (_enr, _day, _st, _ln), g in _spec_groups.items():
        for p in rules.covers(_st, _ln):
            for sec_id in g["theory_sections"]:
                section_theory_periods[sec_id].add((_day, p))
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
    num_periods = snap["num_periods"]
    day_order = {d: i for i, d in enumerate(snap["days"])}
    sec_names = snap["sec_names"]
    for sec_id in sorted(section_theory_periods):
        by_day = defaultdict(set)
        for (d, p) in section_theory_periods[sec_id]:
            by_day[d].add(p)
        for d in sorted(by_day, key=lambda x: (day_order.get(x, 999), str(x))):
            for res in rules.check_max_two_theory(
                    by_day[d], num_periods, break_after,
                    sec_names.get(sec_id, f"section {sec_id}"), d, sec_id):
                problems.append(f"MAX_TWO_THEORY VIOLATION: {res.message}")

    # Phase 6F: specialization overlap (normal teaching vs synchronized
    # spec footprint, conservative section-level). Unrelated sections may
    # coexist; participating sections must not.
    _spec_sec_periods = defaultdict(set)  # section_id -> {(day, period)}
    for (_enr, _day, _st, _ln), g in _spec_groups.items():
        for p in rules.covers(_st, _ln):
            for sec_id in g["sections"]:
                _spec_sec_periods[sec_id].add((_day, p))
    for sec_id, normal_cells in sorted(section_periods.items()):
        overlap = normal_cells & _spec_sec_periods.get(sec_id, set())
        if overlap:
            problems.append(
                f"SPECIALIZATION_OVERLAP: section {sec_id} "
                f"({snap.get('sec_names', {}).get(sec_id, '?')}) has normal "
                f"teaching overlapping specialization slots at "
                f"{sorted(overlap)[:5]}.")
    # Lab-group practicals vs specialization (parent-section footprint).
    for lg_id, sec_id in (snap.get("labgroup_section", {}) or {}).items():
        overlap = labgroup_periods.get(lg_id, set()) & _spec_sec_periods.get(
            sec_id, set())
        if overlap:
            problems.append(
                f"SPECIALIZATION_OVERLAP: lab group {lg_id} (section {sec_id}) "
                f"has a practical overlapping specialization slots at "
                f"{sorted(overlap)[:5]}.")

    # Phase 6E: locked-block consistency (no-ops when the additive schema
    # is absent; always read-only).
    problems.extend(audit_locked_blocks(snap))

    # Phase 6F: specialization domain consistency (read-only).
    problems.extend(audit_specializations(snap))

    return problems, notes


def audit_specializations(snap):
    """Phase 6F read-only checks over specialization domain data.

    Covers: orphans, invalid memberships, cross-enrollment, aggregate and
    room capacity, synchronization, and slot/geometry sanity. Never writes.
    """
    problems = []
    specs = snap.get("specializations", []) or []
    mems = snap.get("memberships", []) or []
    slots = snap.get("spec_slots", []) or []
    if not snap.get("has_spec_schema", False) and not specs \
            and not mems and not slots:
        return problems
    by_id = {s["id"]: s for s in specs}
    sec_sizes = snap.get("sec_sizes", {}) or {}
    sec_enr = snap.get("sec_enrollment", {}) or {}
    sec_names = snap.get("sec_names", {}) or {}
    # Orphans: membership/slot referencing missing spec/section.
    for m in mems:
        if m["specialization_id"] not in by_id:
            problems.append(
                f"SPECIALIZATION_ORPHAN: membership {m['id']} references "
                f"missing specialization {m['specialization_id']}.")
        if m["section_id"] not in sec_sizes:
            problems.append(
                f"SPECIALIZATION_ORPHAN: membership {m['id']} references "
                f"missing section {m['section_id']}.")
        if not isinstance(m["student_count"], int) or m["student_count"] <= 0:
            problems.append(
                f"SPECIALIZATION_MEMBERSHIP_INVALID: membership {m['id']} "
                f"has invalid count {m['student_count']!r} (must be > 0).")
    for sl in slots:
        if sl["specialization_id"] not in by_id:
            problems.append(
                f"SPECIALIZATION_ORPHAN: slot {sl['id']} references missing "
                f"specialization {sl['specialization_id']}.")
    for s in specs:
        if s.get("enrollment_id") is None:
            problems.append(
                f"SPECIALIZATION_ORPHAN: specialization {s['id']} "
                f"('{s.get('name', '?')}') has no enrollment/cohort.")
    # Enrollment invariant + aggregate capacity per section.
    mem_by_section = defaultdict(list)
    for m in mems:
        mem_by_section[m["section_id"]].append(m)
    for m in mems:
        spec = by_id.get(m["specialization_id"])
        if spec is None:
            continue
        s_enr = sec_enr.get(m["section_id"])
        if s_enr is not None and spec.get("enrollment_id") != s_enr:
            problems.append(
                f"SPECIALIZATION_ENROLLMENT: section {m['section_id']} "
                f"(enrollment {s_enr}) cannot join specialization "
                f"{spec['id']} ('{spec.get('name', '?')}', enrollment "
                f"{spec.get('enrollment_id')}): cross-cohort membership.")
    for sec_id, lst in sorted(mem_by_section.items()):
        cap = sec_sizes.get(sec_id, 0) or 0
        total = sum((m["student_count"] or 0) for m in lst)
        if cap and total > cap:
            problems.append(
                f"SPECIALIZATION_CAPACITY: section {sec_id} "
                f"({sec_names.get(sec_id, '?')}, {cap} enrolled) allocates "
                f"{total} students across specializations "
                f"{sorted(m['specialization_id'] for m in lst)}: exceeds "
                f"enrollment.")
    # Room capacity for scheduled spec classes (total vs room).
    totals = {}
    for m in mems:
        totals[m["specialization_id"]] = totals.get(
            m["specialization_id"], 0) + (m["student_count"] or 0)
    for sc in snap.get("classes", []) or []:
        a = snap.get("assignments", {}).get(sc["assignment_id"])
        if a is None or a.get("specialization_id") is None:
            continue
        spec_id = a["specialization_id"]
        total = totals.get(spec_id, 0) or 0
        room = snap.get("rooms", {}).get(sc["room_id"])
        if room is not None and (room.get("capacity") or 0) < total:
            problems.append(
                f"SPECIALIZATION_ROOM_CAPACITY: specialization {spec_id} "
                f"({total} students) in room {room.get('name', '?')} "
                f"(capacity {room.get('capacity')}) at "
                f"{sc['day']} period {sc['start_period']}: undersized room.")
    # Synchronization: active specs (with memberships) sharing an enrollment
    # must have identical slot patterns (day/start/length). Empty (unscheduled)
    # cohorts pass; single-spec cohorts always pass.
    active_by_enr = defaultdict(list)
    for s in specs:
        has_mem = any(m["specialization_id"] == s["id"] for m in mems)
        if has_mem:
            active_by_enr[s.get("enrollment_id")].append(s["id"])
    slots_by_spec = defaultdict(list)
    for sl in slots:
        slots_by_spec[sl["specialization_id"]].append(
            (sl["day"], sl["start_period"], sl["length"]))
    for enr, sids in sorted(active_by_enr.items(), key=lambda kv: str(kv[0])):
        if len(sids) <= 1:
            continue
        # If none have slots yet (unscheduled), not a violation.
        if not any(slots_by_spec.get(sid) for sid in sids):
            continue
        ref = sorted(slots_by_spec.get(sorted(sids, key=str)[0], []))
        for sid in sorted(sids, key=str)[1:]:
            got = sorted(slots_by_spec.get(sid, []))
            if got != ref:
                problems.append(
                    f"SPECIALIZATION_SYNC: specialization {sid} slots {got} "
                    f"do not match cohort {enr} pattern {ref}: all "
                    f"specializations must share identical (day, start, "
                    f"length).")
    # Slot geometry sanity (day/period/break) via shared rules.
    days = snap.get("days", []) or []
    num_periods = snap.get("num_periods", 0) or 0
    break_after = snap.get("break_after")
    for sl in slots:
        res = rules.check_day_known(sl["day"], days)
        if not res.ok:
            problems.append(
                f"SPECIALIZATION_SYNC: slot {sl['id']} has unknown day "
                f"'{sl['day']}'.")
        res = rules.check_block_geometry(sl["start_period"], sl["length"],
                                         num_periods)
        if not res.ok:
            problems.append(
                f"SPECIALIZATION_SYNC: slot {sl['id']} geometry invalid: "
                f"{res.message}")
        res = rules.check_break_geometry(sl["start_period"], sl["length"],
                                         break_after)
        if not res.ok:
            problems.append(
                f"SPECIALIZATION_SYNC: slot {sl['id']} spans the break.")
    return problems


def audit_locked_blocks(snap):
    """Detect LockedBlock <-> ScheduledClass inconsistencies.

    Covers: locked block with no class, class pointing at a missing block,
    is_locked flag missing, day/start/length mismatch, room mismatch,
    faculty/assignment mismatch, and locked placements violating a hard
    rule (re-checked through schedule_rules). Pure + read-only.
    """
    problems = []
    blocks = snap.get("locked_blocks", []) or []
    if not snap.get("has_lock_schema", False) and not blocks:
        return problems
    by_block = defaultdict(list)  # locked_block_id -> [class dicts]
    for sc in snap["classes"]:
        lbid = sc.get("locked_block_id")
        if lbid is not None:
            by_block[lbid].append(sc)
    block_ids = {lb["id"] for lb in blocks}
    for sc in snap["classes"]:
        lbid = sc.get("locked_block_id")
        if lbid is not None and lbid not in block_ids:
            problems.append(
                f"LOCKED_BLOCK_MISSING: scheduled class {sc['id']} points to "
                f"missing locked block {lbid}.")
        if lbid is not None and not sc.get("is_locked"):
            problems.append(
                f"LOCKED_FLAG_MISSING: scheduled class {sc['id']} references "
                f"locked block {lbid} but is not marked is_locked.")
    for lb in blocks:
        linked = by_block.get(lb["id"], [])
        if not linked:
            problems.append(
                f"LOCKED_BLOCK_ORPHAN: locked block {lb['id']} ({lb['day']} "
                f"period {lb['start_period']} x{lb['length']}) has no "
                f"scheduled class; the timetable view is missing its placement.")
            continue
        if len(linked) > 1:
            problems.append(
                f"LOCKED_BLOCK_DUPLICATE: locked block {lb['id']} has "
                f"{len(linked)} scheduled classes "
                f"{sorted(c['id'] for c in linked)}; exactly one is allowed.")
        for sc in linked:
            a = snap["assignments"].get(sc["assignment_id"])
            if (sc["day"] != lb["day"]
                    or sc["start_period"] != lb["start_period"]
                    or sc["length"] != lb["length"]):
                problems.append(
                    f"LOCKED_BLOCK_MISMATCH: locked block {lb['id']} says "
                    f"{lb['day']} period {lb['start_period']} x{lb['length']} "
                    f"but scheduled class {sc['id']} is {sc['day']} period "
                    f"{sc['start_period']} x{sc['length']}.")
            if lb.get("room_id") is not None and sc["room_id"] != lb["room_id"]:
                problems.append(
                    f"LOCKED_ROOM_MISMATCH: locked block {lb['id']} fixes room "
                    f"{lb['room_id']} but scheduled class {sc['id']} uses room "
                    f"{sc['room_id']}.")
            if (lb.get("assignment_id") is not None
                    and sc["assignment_id"] != lb["assignment_id"]):
                problems.append(
                    f"LOCKED_ASSIGNMENT_MISMATCH: locked block {lb['id']} pins "
                    f"assignment {lb['assignment_id']} but scheduled class "
                    f"{sc['id']} places assignment {sc['assignment_id']}.")
            if a is not None:
                if a["faculty_id"] != lb["faculty_id"]:
                    problems.append(
                        f"LOCKED_ASSIGNMENT_MISMATCH: locked block {lb['id']} "
                        f"names faculty {lb['faculty_id']} but its class "
                        f"{sc['id']} (assignment {a['id']}) uses faculty "
                        f"{a['faculty_id']}.")
                if a["session_type"] == "practical":
                    if lb.get("lab_group_id") != a["lab_group_id"]:
                        problems.append(
                            f"LOCKED_ASSIGNMENT_MISMATCH: locked block {lb['id']} "
                            f"names lab group {lb.get('lab_group_id')} but class "
                            f"{sc['id']} uses {a['lab_group_id']}.")
                elif lb.get("section_id") != a["section_id"]:
                    problems.append(
                        f"LOCKED_ASSIGNMENT_MISMATCH: locked block {lb['id']} "
                        f"names section {lb.get('section_id')} but class "
                        f"{sc['id']} uses {a['section_id']}.")
            # Re-validate the locked placement against hard rules.
            if a is not None:
                res = rules.check_day_known(lb["day"], snap["days"])
                if not res.ok:
                    problems.append(
                        f"LOCKED_BLOCK_RULE_VIOLATION: locked block {lb['id']} "
                        f"violates UNKNOWN_DAY: {res.message}")
                res = rules.check_block_geometry(
                    lb["start_period"], lb["length"], snap["num_periods"])
                if not res.ok:
                    problems.append(
                        f"LOCKED_BLOCK_RULE_VIOLATION: locked block {lb['id']} "
                        f"violates PERIOD_OUT_OF_RANGE: {res.message}")
                res = rules.check_break_geometry(
                    lb["start_period"], lb["length"], snap["break_after"])
                if not res.ok:
                    problems.append(
                        f"LOCKED_BLOCK_RULE_VIOLATION: locked block {lb['id']} "
                        f"violates BREAK_SPAN: {res.message}")
                room = snap["rooms"].get(lb["room_id"]) if lb.get("room_id") else None
                if lb.get("room_id") is not None and room is not None:
                    res = rules.check_room_compatible(
                        room["room_type"], room["capacity"],
                        room["equipment_count"], a["session_type"],
                        a["group_size"], room_name=room["name"],
                        group_label=a["group_label"])
                    if not res.ok:
                        problems.append(
                            f"LOCKED_BLOCK_RULE_VIOLATION: locked block {lb['id']} "
                            f"violates {res.code}: {res.message}")
                unavail = (snap.get("faculty_unavailable", {}) or {}).get(
                    lb["faculty_id"], set())
                res = rules.check_faculty_available(
                    unavail, lb["day"], lb["start_period"], lb["length"])
                if not res.ok:
                    problems.append(
                        f"LOCKED_BLOCK_RULE_VIOLATION: locked block {lb['id']} "
                        f"violates FACULTY_UNAVAILABLE: {res.message}")
    return problems


def report_6e_footprint(conn):
    """Explicit NOTE when the Phase 6E assignment-link column is absent.

    Never migrates or repairs; a 6C-schema database stays auditable for
    locked blocks on its legacy columns.
    """
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    except Exception:
        return ""
    if "locked_block" not in tables:
        return ""
    try:
        cols = _table_cols(conn, "locked_block")
    except Exception:
        return ""
    if "assignment_id" not in cols:
        return ("NOTE: locked_block table is missing the Phase 6E "
                "assignment_id column. Auditing locked blocks on legacy "
                "columns only; no migration was performed.")
    return ""


def run_audit(db_path):
    """Audit the database at `db_path` read-only.

    Returns (exit_code, problems). Prints the human-readable report.
    Never writes, migrates, or creates schema.
    """
    try:
        conn = open_readonly(db_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2, []
    with conn:
        schema_problems = check_required_schema(conn)
        if schema_problems:
            print("ERROR: Database schema is missing required audit inputs:")
            for sp in schema_problems:
                print(f" - {sp}")
            print("The audit does not migrate databases. Copy the database "
                  "and run an explicit migration command first "
                  "(see backend/migrate.py --help).")
            return 2, []
        note = report_6c_footprint(conn)
        note_6e = report_6e_footprint(conn)
        if note_6e and note:
            note = note + "\n" + note_6e
        elif note_6e:
            note = note_6e
        snap = load_snapshot(conn)
    # Connection closed before analysis: the audit holds a plain snapshot.
    conn.close()

    print(f"Auditing {len(snap['classes'])} scheduled class blocks...\n")
    if note:
        print(note + "\n")
    problems, _ = audit_snapshot(snap)
    if problems:
        print(f"[FAIL] {len(problems)} PROBLEM(S) FOUND:\n")
        for p in problems:
            print(" -", p)
        return 1, problems
    print("[OK] No conflicts found: rooms, faculty, and student groups are never "
          "double-booked, no session crosses the break, room type/capacity/equipment "
          "always match, no faculty member exceeds the consecutive-teaching limit, "
          "no lab group's practical overlaps a whole-section theory class for its "
          "own section, and no section has three consecutive theory periods in "
          "one teaching segment of a day.")
    return 0, []


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only audit of a generated timetable. "
                    "Never writes to the database.")
    parser.add_argument("--db", default=DEFAULT_DB,
                        help="SQLite file to audit (default: %(default)s). "
                             "Use a copy for diagnostics; the audit never "
                             "modifies the file.")
    args = parser.parse_args(argv)
    code, _ = run_audit(args.db)
    return code


if __name__ == "__main__":
    sys.exit(main())
