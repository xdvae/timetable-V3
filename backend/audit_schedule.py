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

    assignments = {}
    for r in conn.execute(
            "SELECT id, faculty_id, subject_id, session_type, section_id, "
            "lab_group_id, periods_per_week, block_length "
            "FROM teaching_assignment ORDER BY id"):
        aid, fac_id, subj_id, stype, sec_id, lg_id = r[0:6]
        if stype == "practical" and lg_id is not None:
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
        }

    classes = []
    for r in conn.execute(
            "SELECT id, assignment_id, day, start_period, length, room_id "
            "FROM scheduled_class ORDER BY id"):
        classes.append({"id": r[0], "assignment_id": r[1], "day": r[2],
                        "start_period": r[3], "length": r[4],
                        "room_id": r[5]})

    return {
        "days": days,
        "num_periods": len(periods),
        "break_after": cfg[2],
        "max_consecutive": cfg[3],
        "rooms": rooms,
        "faculty_names": faculty_names,
        "sec_names": sec_names,
        "labgroup_section": lg_sections,
        "assignments": assignments,
        "classes": classes,
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

    def check_overlap(occ, code, label, kind):
        for res in rules.check_no_overlap(occ, code, label):
            key, day, period = (res.details["resource"],
                               res.details["day"], res.details["period"])
            ids = "; ".join(cell_desc[(kind, key, day, period)])
            problems.append(f"{label} DOUBLE-BOOKED: {(key, day)} at period {period} -> {ids}")

    check_overlap(room_occ, "ROOM_CONFLICT", "ROOM", "room")
    check_overlap(fac_occ, "FACULTY_CONFLICT", "FACULTY", "faculty")
    check_overlap(group_occ, "GROUP_CONFLICT", "STUDENT GROUP", "group")

    # H8: hierarchical check via the shared rule — a lab group's students are
    # a subset of their parent section, so a lab-group session must never
    # overlap a whole-section theory session.
    lg_sections = snap["labgroup_section"]
    section_theory_periods = defaultdict(set)   # section_id -> {(day, period)}
    labgroup_periods = defaultdict(set)         # lab_group_id -> {(day, period)}
    for sc in snap["classes"]:
        a = snap["assignments"].get(sc["assignment_id"])
        if a is None:
            continue
        periods = rules.covers(sc["start_period"], sc["length"])
        if a["session_type"] == "theory" and a["section_id"]:
            for p in periods:
                section_theory_periods[a["section_id"]].add((sc["day"], p))
        elif a["session_type"] == "practical" and a["lab_group_id"]:
            for p in periods:
                labgroup_periods[a["lab_group_id"]].add((sc["day"], p))
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

    return problems, notes


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
