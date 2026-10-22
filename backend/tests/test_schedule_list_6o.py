"""Phase 6O tests: GET /api/schedule/classes list endpoint.

The interactive editor needs every ScheduledClass display-ready (identity,
placement, lock + specialization linkage) in one bulk read. The existing
lane-cell timetable payload deliberately omits per-class identity, so this
additive endpoint fills that gap without changing any existing response.

Every test uses throwaway SQLite files in a temp dir — never the real
database. Run from the repository root:

    venv\\Scripts\\python.exe -m pytest backend/tests/test_schedule_list_6o.py -q
"""
import hashlib
import os
import tempfile
import unittest
from unittest import mock

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class OBase(unittest.TestCase):
    """Throwaway Flask app + small seeded timetable (all placements valid)."""

    def setUp(self):
        from flask import Flask
        from backend import models as m
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6o.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6O", working_days=DAYS,
                                  periods=PERIODS, break_after_periods=4,
                                  max_consecutive_teaching=3))
        m.db.session.add(m.Program(id=1, name="BCA"))
        m.db.session.add(m.Enrollment(id=1, program_id=1, year_label="Y1",
                                      total_students=60))
        m.db.session.add(m.Section(id=1, enrollment_id=1, name="BCA-1-A",
                                   student_count=30))
        m.db.session.add(m.Room(id=1, name="R101", room_type="theory",
                                capacity=100))
        m.db.session.add(m.Room(id=2, name="R102", room_type="theory",
                                capacity=100))
        m.db.session.add(m.Faculty(id=1, name="F1"))
        m.db.session.add(m.Faculty(id=2, name="F2"))
        m.db.session.add(m.Subject(id=1, name="SUB1", enrollment_id=1))
        m.db.session.add(m.TeachingAssignment(
            id=1, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=2, block_length=1))
        m.db.session.add(m.TeachingAssignment(
            id=2, faculty_id=2, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=2, block_length=1))
        m.db.session.commit()

    def tearDown(self):
        try:
            self.m.db.session.remove()
            self.m.db.engine.dispose()
        except Exception:
            pass


class OApiBase(OBase):
    def setUp(self):
        super().setUp()
        from flask_login import LoginManager
        from backend.api_routes import init_api
        self.app.secret_key = "6o-test"
        lm = LoginManager()
        lm.init_app(self.app)
        # Bind the loader late so it sees this test's AdminUser rows.
        @lm.user_loader  # noqa: F811 — test-local loader rebinding
        def _load(uid):
            return self.m.AdminUser.query.get(int(uid))

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
        self.anon = self.app.test_client()

    def _anon_get(self, path):
        self.ctx.pop()
        try:
            return self.anon.get(path)
        finally:
            self.ctx.push()


class TestScheduleListAuth(OApiBase):
    def test_anonymous_list_rejected_db_untouched(self):
        before = _sha(self.db_path)
        resp = self._anon_get("/api/schedule/classes")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(_sha(self.db_path), before)


class TestScheduleListEmpty(OApiBase):
    def test_empty_schedule_shape(self):
        resp = self.client.get("/api/schedule/classes")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload["classes"], [])
        self.assertFalse(payload["has_schedule"])
        self.assertEqual(payload["days"], ["Mon", "Tue", "Wed"])
        self.assertEqual(len(payload["periods"]), 7)
        self.assertEqual(payload["break_after"], 4)


class TestScheduleListPopulated(OApiBase):
    def setUp(self):
        super().setUp()
        self.m.db.session.add(self.m.ScheduledClass(
            id=1, assignment_id=1, day="Mon", start_period=0,
            length=1, room_id=1, run_id="run1"))
        self.m.db.session.add(self.m.ScheduledClass(
            id=2, assignment_id=2, day="Tue", start_period=1,
            length=2, room_id=2, run_id="run1"))
        self.m.db.session.commit()

    def test_display_ready_shape(self):
        resp = self.client.get("/api/schedule/classes")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["has_schedule"])
        self.assertEqual(len(payload["classes"]), 2)
        by_id = {c["id"]: c for c in payload["classes"]}
        one = by_id[1]
        for key in ("id", "assignment_id", "day", "start_period",
                    "length", "room_id", "room", "subject",
                    "subject_id", "faculty", "faculty_id",
                    "session_type", "section_id", "section",
                    "lab_group_id", "lab_group", "specialization_id",
                    "specialization", "run_id", "is_locked",
                    "slot_id", "locked_block_id"):
            self.assertIn(key, one, f"missing key {key}")
        self.assertEqual(one["day"], "Mon")
        self.assertEqual(one["start_period"], 0)
        self.assertEqual(one["length"], 1)
        self.assertEqual(one["room_id"], 1)
        self.assertEqual(one["subject"], "SUB1")
        self.assertEqual(one["faculty"], "F1")
        self.assertEqual(one["section"], "BCA-1-A")
        self.assertFalse(one["is_locked"])
        self.assertIsNone(one["locked_block_id"])
        self.assertIsNone(one["specialization_id"])
        two = by_id[2]
        self.assertEqual(two["length"], 2)
        self.assertEqual(two["faculty"], "F2")

    def test_locked_row_surfaces_lock_linkage(self):
        lb = self.m.LockedBlock(
            kind="manual_fix", assignment_id=1, subject_id=1,
            faculty_id=1, section_id=1, day="Mon", start_period=0,
            length=1, room_id=1, room_locked=True)
        self.m.db.session.add(lb)
        self.m.db.session.flush()
        sc = self.m.ScheduledClass.query.get(1)
        sc.is_locked = True
        sc.locked_block_id = lb.id
        self.m.db.session.commit()
        resp = self.client.get("/api/schedule/classes")
        by_id = {c["id"]: c for c in resp.get_json()["classes"]}
        self.assertTrue(by_id[1]["is_locked"])
        self.assertEqual(by_id[1]["locked_block_id"], lb.id)

    def test_specialization_row_surfaces_spec_linkage(self):
        from backend import specializations as spec_svc
        spec = spec_svc.create_specialization(
            self.m.db, name="Cyber", enrollment_id=1,
            session_type="theory", block_length=1, periods_per_week=1)
        spec_svc.add_or_update_membership(self.m.db, spec.id, 1, 10)
        assign = self.m.TeachingAssignment(
            faculty_id=1, subject_id=1, session_type="theory",
            section_id=None, lab_group_id=None,
            specialization_id=spec.id, periods_per_week=1,
            block_length=1)
        self.m.db.session.add(assign)
        self.m.db.session.commit()
        slot = self.m.SpecializationSlot(
            specialization_id=spec.id, day="Wed", start_period=0,
            length=1)
        self.m.db.session.add(slot)
        self.m.db.session.flush()
        self.m.db.session.add(self.m.ScheduledClass(
            assignment_id=assign.id, day="Wed", start_period=0,
            length=1, room_id=1, run_id="run1", slot_id=slot.id))
        self.m.db.session.commit()
        resp = self.client.get("/api/schedule/classes")
        spec_rows = [c for c in resp.get_json()["classes"]
                     if c["specialization_id"] == spec.id]
        self.assertEqual(len(spec_rows), 1)
        self.assertEqual(spec_rows[0]["specialization"], "Cyber")
        self.assertEqual(spec_rows[0]["slot_id"], slot.id)

    def test_get_is_read_only(self):
        before = _sha(self.db_path)
        count_before = self.m.ScheduledClass.query.count()
        resp = self.client.get("/api/schedule/classes")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.m.ScheduledClass.query.count(),
                         count_before)
        self.assertEqual(_sha(self.db_path), before)

    def test_list_never_invokes_scheduler(self):
        with mock.patch("backend.scheduler.run_scheduler",
                        side_effect=AssertionError("must not run")):
            resp = self.client.get("/api/schedule/classes")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.get_json()["classes"]), 2)

    def test_existing_timetable_view_unchanged(self):
        # The lane-cell contract the read-only views rely on is untouched:
        # day_rows with {empty, colspan, class} cells still served.
        resp = self.client.get("/api/timetable/section/1")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIn("day_rows", payload)
        flat = [cell for row in payload["day_rows"]
                for lane in row["lanes"] for cell in lane]
        self.assertTrue(any(not c.get("empty") for c in flat))


if __name__ == "__main__":
    unittest.main()
