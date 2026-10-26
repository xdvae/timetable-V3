"""
Child-process entry point for timetable solving.

    python -m backend.solver_worker <input.json> <output.json>

Reads the plain-JSON scheduler inputs written by backend/solver_runner.py,
runs backend.scheduler.run_scheduler() and writes
{"status", "placements", "message"} to <output.json>. Never touches the
database. If OR-Tools crashes natively, this process dies and the parent
web server reports it instead of dying with it.
"""
import json
import sys
import traceback


def main(argv):
    if len(argv) != 3:
        print("usage: python -m backend.solver_worker IN.json OUT.json",
              file=sys.stderr)
        return 2
    in_path, out_path = argv[1], argv[2]
    try:
        with open(in_path, encoding="utf-8") as fh:
            payload = json.load(fh)
        from backend.solver_runner import payload_to_kwargs
        from backend.scheduler import run_scheduler
        status, placements, message = run_scheduler(**payload_to_kwargs(payload))
        result = {"status": status, "placements": placements or [],
                  "message": message}
        code = 0
    except Exception:  # noqa: BLE001 - reported to the parent, logged here
        traceback.print_exc()
        result = {"error": True}
        code = 1
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
