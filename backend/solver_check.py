"""
Quick health check for the timetable solver (OR-Tools CP-SAT).

    python -m backend.solver_check

Solves a tiny two-class timetable in a child process, exactly the way the
web app does. If this prints "Solver OK", generation will work; if it
reports a crash, fix the solver install (see the message) before
generating timetables.
"""
import platform
import struct
import sys


def main():
    print(f"Python {platform.python_version()} "
          f"({struct.calcsize('P') * 8}-bit) on {platform.system()} "
          f"{platform.machine()}")
    try:
        import ortools  # noqa: F401
        print(f"OR-Tools {getattr(ortools, '__version__', '?')} imported.")
    except Exception as exc:  # noqa: BLE001
        print(f"OR-Tools could not be imported: {exc}")
        print("Install it with: pip install -r backend/requirements.txt")
        return 1
    if struct.calcsize("P") * 8 != 64:
        print("This is a 32-bit Python. OR-Tools needs 64-bit Python.")
        return 1

    from backend import solver_runner as sr
    payload = {
        "assignments": [
            {"id": 1, "faculty_id": 1, "subject_id": 1,
             "session_type": "theory", "section_id": 1,
             "lab_group_id": None, "periods_per_week": 2, "block_length": 1,
             "specialization_id": None, "lab_group": None,
             "group_key": "section:1", "group_label": "TEST-A",
             "group_size": 30},
            {"id": 2, "faculty_id": 2, "subject_id": 2,
             "session_type": "theory", "section_id": 1,
             "lab_group_id": None, "periods_per_week": 2, "block_length": 1,
             "specialization_id": None, "lab_group": None,
             "group_key": "section:1", "group_label": "TEST-A",
             "group_size": 30},
        ],
        "rooms": [{"id": 1, "name": "101", "room_type": "theory",
                   "capacity": 60, "equipment_count": None}],
        "faculty_unavailable": [],
        "days": ["Mon", "Tue"],
        "num_periods": 4,
        "break_after": 2,
        "max_consecutive": 3,
        "time_limit_seconds": 10,
        "locked_placements": [],
        "specialization_data": [],
        "preferred_theory_rooms": [],
        "faculty_preferences": [],
    }
    try:
        status, placements, message = sr.run_isolated(payload, grace_seconds=30)
    except sr.SolverCrashed as exc:
        print("Solver FAILED:", exc.message)
        return 1
    if status in ("OPTIMAL", "FEASIBLE") and len(placements) == 4:
        print(f"Solver OK ({status}, {len(placements)} classes placed).")
        return 0
    print(f"Solver returned an unexpected result: {status} {message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
