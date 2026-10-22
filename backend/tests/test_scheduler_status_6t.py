"""Phase 6T tests: scheduler result-status correctness (UNKNOWN/timeout).

The 6S audit found the solver wrapper folded every non-OPTIMAL/FEASIBLE
outcome into "INFEASIBLE", so a mere time-limit/UNKNOWN was reported as a
proven infeasibility. These tests pin the corrected contract:

* solver OPTIMAL -> "OPTIMAL" (unchanged)
* solver FEASIBLE -> "FEASIBLE" (unchanged)
* solver INFEASIBLE -> "INFEASIBLE" (proven; unchanged message)
* solver UNKNOWN (e.g. time limit) -> "UNKNOWN", never "INFEASIBLE"
* solver MODEL_INVALID -> "MODEL_INVALID" (never "INFEASIBLE")
* API maps "UNKNOWN" -> 422 SCHEDULING_FAILED (timeout details, no
  infeasibility claim) and preserves the previous schedule
* API maps "MODEL_INVALID" -> sanitized 500 INTERNAL_ERROR and preserves
  the previous schedule

All tests use throwaway SQLite files in a temp dir (solver unit tests use
duck-typed fakes with no ORM/IO at all) — never the reference databases.

Run from the repository root:

    venv\\Scripts\\python.exe -m pytest backend\\tests\\test_scheduler_status_6t.py -q
"""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from ortools.sat.python import cp_model


# ------------------------------------------------------- solver fakes (no DB)
def _room(rid, name=None, room_type="theory", capacity=100):
    return SimpleNamespace(id=rid, name=name or f"R{rid}",
                           room_type=room_type, capacity=capacity,
                           equipment_count=None)


class _FakeAssignment:
    """Duck-typed TeachingAssignment (normal section theory)."""

    def __init__(self, aid, faculty_id, section_id=1, ppw=1, block=1):
        self.id = aid
        self.faculty_id = faculty_id
        self.subject_id = 900 + aid
        self.session_type = "theory"
        self.section_id = section_id
        self.lab_group_id = None
        self.periods_per_week = ppw
        self.block_length = block
        self.specialization_id = None
        self.lab_group = None

    def group_key(self):
        return f"section:{self.section_id}"

    def group_label(self):
        return self.group_key()

    def group_size(self):
        return 30


def _tiny_model():
    from backend.scheduler import run_scheduler  # noqa (import here: keeps collection light)
    assignments = [_FakeAssignment(1, faculty_id=1)]
    rooms = [_room(1, "R101")]
    return run_scheduler, (assignments, rooms, {}, ["Mon", "Tue"], 4,
                           None, 0)


class TestSolverStatusMapping(unittest.TestCase):
    """run_scheduler must surface the solver's verdict honestly."""

    def test_optimal_preserved(self):
        run_scheduler, args = _tiny_model()
        status, placements, _ = run_scheduler(*args, time_limit_seconds=10)
        self.assertEqual(status, "OPTIMAL")
        self.assertEqual(len(placements), 1)

    def test_unknown_not_infeasible(self):
        run_scheduler, args = _tiny_model()
        with mock.patch.object(cp_model.CpSolver, "Solve",
                               return_value=cp_model.UNKNOWN):
            status, placements, message = run_scheduler(
                *args, time_limit_seconds=10)
        self.assertEqual(status, "UNKNOWN")
        self.assertEqual(placements, [])
        self.assertNotEqual(status, "INFEASIBLE")
        self.assertNotIn("infeasible", (message or "").lower())
        self.assertIn("time limit", (message or "").lower())

    def test_true_infeasible_preserved(self):
        run_scheduler, args = _tiny_model()
        with mock.patch.object(cp_model.CpSolver, "Solve",
                               return_value=cp_model.INFEASIBLE):
            status, placements, message = run_scheduler(
                *args, time_limit_seconds=10)
        self.assertEqual(status, "INFEASIBLE")
        self.assertEqual(placements, [])
        self.assertIn("No valid timetable", message or "")

    def test_model_invalid_not_infeasible(self):
        run_scheduler, args = _tiny_model()
        with mock.patch.object(cp_model.CpSolver, "Solve",
                               return_value=cp_model.MODEL_INVALID):
            status, placements, message = run_scheduler(
                *args, time_limit_seconds=10)
        self.assertEqual(status, "MODEL_INVALID")
        self.assertEqual(placements, [])
        self.assertNotIn("infeasible", (message or "").lower())


DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))


class SchedulerStatusApiBase(unittest.TestCase):
    """Throwaway app + seeded school + previous schedule + login."""

    def setUp(self):
        from flask import Flask
        from flask_login import LoginManager
        from backend import models as m
        from backend.api_routes import init_api
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6t.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.secret_key = "6t-test"
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6T", working_days=DAYS,
                                  periods=PERIODS, break_after_periods=4,
                                  max_consecutive_teaching=3))
        m.db.session.add(m.Program(id=1, name="BCA"))
        m.db.session.add(m.Enrollment(id=1, program_id=1, year_label="Y1",
                                      total_students=60))
        m.db.session.add(m.Section(id=1, enrollment_id=1, name="BCA-1-A",
                                   student_count=30))
        m.db.session.add(m.Room(id=1, name="R101", room_type="theory",
                                capacity=100))
        m.db.session.add(m.Faculty(id=1, name="F1", weekly_max_hours=24))
        m.db.session.add(m.Subject(id=1, name="SUB1", enrollment_id=1))
        m.db.session.add(m.TeachingAssignment(
            id=1, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=2, block_length=1))
        m.db.session.commit()
        # Previous valid schedule that failures must preserve untouched.
        m.db.session.add(m.ScheduledClass(
            assignment_id=1, day="Mon", start_period=0, length=1,
            room_id=1, run_id="prevrun"))
        m.db.session.commit()

        lm = LoginManager()
        lm.init_app(self.app)
        m_ref = m

        @lm.user_loader
        def _load(uid):
            return m_ref.AdminUser.query.get(int(uid))

        init_api(self.app, lm)
        admin = self.m.AdminUser(username="admin")
        admin.set_password("password123")
        self.m.db.session.add(admin)
        self.m.db.session.commit()
        self.client = self.app.test_client()
        resp = self.client.post("/api/login",
                                json={"username": "admin",
                                      "password": "password123"})
        self.assertEqual(resp.status_code, 200)

    def tearDown(self):
        try:
            self.m.db.session.remove()
            self.m.db.engine.dispose()
        except Exception:
            pass

    def _schedule_snapshot(self):
        rows = self.m.ScheduledClass.query.order_by(
            self.m.ScheduledClass.id).all()
        return [(r.assignment_id, r.day, r.start_period, r.length,
                 r.room_id, r.run_id) for r in rows]


class TestSchedulerStatusApi(SchedulerStatusApiBase):
    def test_unknown_returns_timeout_failure_and_preserves_schedule(self):
        before = self._schedule_snapshot()
        self.assertEqual(len(before), 1)
        with mock.patch("backend.api_routes.run_scheduler",
                         return_value=("UNKNOWN", [],
                                       "The scheduler could not finish within "
                                       "the time limit, so no timetable was "
                                       "produced and feasibility is unknown.")):
            resp = self.client.post("/api/schedule/run", json={})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "SCHEDULING_FAILED")
        self.assertNotIn("INFEASIBLE", resp.get_data(as_text=True))
        self.assertIn("timeout", body["details"])
        self.assertTrue(body["details"]["timeout"])
        self.assertEqual(self._schedule_snapshot(), before)

    def test_model_invalid_sanitized_500_and_preserves_schedule(self):
        before = self._schedule_snapshot()
        with mock.patch("backend.api_routes.run_scheduler",
                         return_value=("MODEL_INVALID", [],
                                       "solver internals /tmp/secret.db")):
            resp = self.client.post("/api/schedule/run", json={})
        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "INTERNAL_ERROR")
        text = resp.get_data(as_text=True)
        self.assertNotIn("secret", text)
        self.assertNotIn("solver internals", text)
        self.assertEqual(self._schedule_snapshot(), before)

    def test_true_infeasible_still_422_and_preserves_schedule(self):
        before = self._schedule_snapshot()
        with mock.patch("backend.api_routes.run_scheduler",
                         return_value=("INFEASIBLE", [],
                                       "No valid timetable could be found.")):
            resp = self.client.post("/api/schedule/run", json={})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(self._schedule_snapshot(), before)


if __name__ == "__main__":
    unittest.main()
