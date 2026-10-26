"""
Run the CP-SAT scheduler in an isolated child process.

Why: OR-Tools is native C++. When it crashes (on Windows this shows up as
an access violation, exit code 0xC0000005, typically from a missing or
mismatched Visual C++ runtime or a broken ortools wheel) it takes the
whole Python process with it. Inside the web server that meant the Flask
process died mid-request, and the browser only ever saw a bare
"Request failed (502)" from the dev proxy, with the backend gone until
someone restarted it.

Running the solve in a short-lived child process keeps the web server
alive no matter what the solver does, enforces a hard wall-clock limit,
and turns a native crash into a clear, actionable error.

The scheduler itself (backend/scheduler.py) is unchanged: this module
only snapshots its ORM inputs into plain data, ships them to
``python -m backend.solver_worker`` and reads the result back.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# One generation at a time per server process: two concurrent runs would
# both replace the stored timetable and race each other.
_generation_lock = threading.Lock()


class SolverCrashed(Exception):
    """The solver process died or produced no result."""

    def __init__(self, message, exit_code=None):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class GenerationBusy(Exception):
    """Another timetable generation is already running."""


# ----------------------------------------------------------- snapshotting
class _LabGroupSnap:
    __slots__ = ("id", "section_id")

    def __init__(self, id, section_id):
        self.id = id
        self.section_id = section_id


class AssignmentSnap:
    """Picklable / JSON-able stand-in for a TeachingAssignment row.

    Exposes exactly the attributes and methods run_scheduler() reads
    (including the residual-copy path for locked blocks), with the
    ORM-derived values captured up front.
    """

    def __init__(self, d):
        self.id = d["id"]
        self.faculty_id = d["faculty_id"]
        self.subject_id = d["subject_id"]
        self.session_type = d["session_type"]
        self.section_id = d.get("section_id")
        self.lab_group_id = d.get("lab_group_id")
        self.periods_per_week = d["periods_per_week"]
        self.block_length = d["block_length"]
        self.specialization_id = d.get("specialization_id")
        self.specialization = None
        lg = d.get("lab_group")
        self.lab_group = _LabGroupSnap(lg["id"], lg["section_id"]) if lg else None
        self._group_key = d["group_key"]
        self._group_label = d["group_label"]
        self._group_size = d["group_size"]

    def group_key(self):
        return self._group_key

    def group_label(self):
        return self._group_label

    def group_size(self):
        return self._group_size


class RoomSnap:
    def __init__(self, d):
        self.id = d["id"]
        self.name = d["name"]
        self.room_type = d["room_type"]
        self.capacity = d["capacity"]
        self.equipment_count = d.get("equipment_count")


def snapshot_assignment(a):
    lg = getattr(a, "lab_group", None)
    return {
        "id": a.id,
        "faculty_id": a.faculty_id,
        "subject_id": a.subject_id,
        "session_type": a.session_type,
        "section_id": getattr(a, "section_id", None),
        "lab_group_id": getattr(a, "lab_group_id", None),
        "periods_per_week": a.periods_per_week,
        "block_length": a.block_length,
        "specialization_id": getattr(a, "specialization_id", None),
        "lab_group": ({"id": lg.id, "section_id": lg.section_id}
                      if lg is not None else None),
        "group_key": a.group_key(),
        "group_label": a.group_label(),
        "group_size": a.group_size(),
    }


def snapshot_room(r):
    return {"id": r.id, "name": r.name, "room_type": r.room_type,
            "capacity": r.capacity, "equipment_count": r.equipment_count}


def snapshot_preference(p):
    get = (p.get if isinstance(p, dict) else
           (lambda name, default=None: getattr(p, name, default)))
    return {"faculty_id": get("faculty_id"), "enabled": get("enabled", True),
            "kind": get("kind"), "days": get("days"),
            "start_period": get("start_period"),
            "end_period": get("end_period")}


def build_payload(*, assignments, rooms, faculty_unavailable, days,
                  num_periods, break_after, max_consecutive,
                  time_limit_seconds, locked_placements,
                  specialization_data, preferred_theory_rooms,
                  faculty_preferences):
    """Plain-JSON form of every run_scheduler() input."""
    return {
        "assignments": [snapshot_assignment(a) for a in assignments],
        "rooms": [snapshot_room(r) for r in rooms],
        # JSON object keys are strings: send pairs to keep int ids intact.
        "faculty_unavailable": [[fid, sorted(slots)] for fid, slots in
                                (faculty_unavailable or {}).items()],
        "days": list(days),
        "num_periods": num_periods,
        "break_after": break_after,
        "max_consecutive": max_consecutive,
        "time_limit_seconds": time_limit_seconds,
        "locked_placements": list(locked_placements or []),
        "specialization_data": [[sid, info] for sid, info in
                                (specialization_data or {}).items()],
        "preferred_theory_rooms": [[sid, rid] for sid, rid in
                                   (preferred_theory_rooms or {}).items()],
        "faculty_preferences": [snapshot_preference(p)
                                for p in (faculty_preferences or [])],
    }


def payload_to_kwargs(payload):
    """Inverse of build_payload(): run_scheduler() keyword arguments."""
    return {
        "assignments": [AssignmentSnap(d) for d in payload["assignments"]],
        "rooms": [RoomSnap(d) for d in payload["rooms"]],
        "faculty_unavailable": {fid: set(slots) for fid, slots in
                                payload["faculty_unavailable"]},
        "days": payload["days"],
        "num_periods": payload["num_periods"],
        "break_after": payload["break_after"],
        "max_consecutive": payload["max_consecutive"],
        "time_limit_seconds": payload["time_limit_seconds"],
        "locked_placements": payload["locked_placements"],
        "specialization_data": {sid: info for sid, info in
                                payload["specialization_data"]},
        "preferred_theory_rooms": {sid: rid for sid, rid in
                                   payload["preferred_theory_rooms"]},
        "faculty_preferences": payload["faculty_preferences"],
    }


# ---------------------------------------------------------------- running
def _crash_message(exit_code):
    code_txt = ""
    if exit_code is not None:
        code_txt = f" (exit code {exit_code}"
        if exit_code < 0 or exit_code > 0xFFFF:
            code_txt += f", 0x{exit_code & 0xFFFFFFFF:08X}"
        code_txt += ")"
    hint = (" On Windows this almost always means OR-Tools' native library "
            "could not run: install the latest 64-bit Microsoft Visual C++ "
            "Redistributable (2015-2022) and reinstall the solver with "
            "'pip install --force-reinstall --no-cache-dir -r "
            "backend/requirements.txt'."
            if os.name == "nt" else
            " Reinstall the solver with 'pip install --force-reinstall "
            "--no-cache-dir -r backend/requirements.txt'.")
    return ("The timetable solver crashed before it could finish"
            f"{code_txt}. Your data and the current timetable are untouched."
            + hint + " Run 'python -m backend.solver_check' to test the "
            "solver on its own.")


def run_isolated(payload, *, grace_seconds=60):
    """Solve in a child process. Returns (status, placements, message).

    Raises SolverCrashed if the child dies, times out hard, or returns
    nothing readable.
    """
    time_limit = payload.get("time_limit_seconds") or 30
    with tempfile.TemporaryDirectory(prefix="timetable-solve-") as tmp:
        in_path = os.path.join(tmp, "input.json")
        out_path = os.path.join(tmp, "output.json")
        with open(in_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        env = dict(os.environ)
        env["PYTHONPATH"] = _ROOT_DIR + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "backend.solver_worker",
                 in_path, out_path],
                cwd=_ROOT_DIR, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=time_limit + grace_seconds)
        except subprocess.TimeoutExpired:
            raise SolverCrashed(
                "The timetable solver stopped responding and was shut down. "
                "Your data and the current timetable are untouched. Try "
                "again; if it keeps happening, reduce the data or check the "
                "server's free memory.")
        except OSError:
            raise SolverCrashed(
                "The timetable solver could not be started on this server. "
                "Your data and the current timetable are untouched.")
        result = None
        if os.path.isfile(out_path):
            try:
                with open(out_path, encoding="utf-8") as fh:
                    result = json.load(fh)
            except (OSError, ValueError):
                result = None
        if proc.returncode != 0 or not isinstance(result, dict):
            # Keep the native diagnostics in the server log, never in the
            # API response.
            tail = (proc.stderr or b"").decode("utf-8", "replace")[-4000:]
            if tail.strip():
                print("[solver] child process stderr:\n" + tail,
                      file=sys.stderr)
            if isinstance(result, dict) and result.get("error"):
                raise SolverCrashed(
                    "The timetable solver hit an internal error. Your data "
                    "and the current timetable are untouched. Details are "
                    "in the server log.", proc.returncode)
            raise SolverCrashed(_crash_message(proc.returncode),
                                proc.returncode)
        return (result.get("status"), result.get("placements") or [],
                result.get("message"))


def acquire_generation_slot():
    if not _generation_lock.acquire(blocking=False):
        raise GenerationBusy()


def release_generation_slot():
    try:
        _generation_lock.release()
    except RuntimeError:
        pass
