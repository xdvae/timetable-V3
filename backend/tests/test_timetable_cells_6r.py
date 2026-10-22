"""Phase 6R tests: read-only timetable lane cells surface fixed/spec state.

The read-only day x period views (`GET /api/timetable/<view>/<id>`) render
lane cells without per-class identity. Phase 6R cards need to badge Fixed
(locked) and Specialization classes there, so `_cell_json` additively
carries `is_locked`, `locked_block_id`, `specialization_id`, and
`specialization`. Every pre-6R key is unchanged.

Every test uses throwaway SQLite files in a temp dir — never the real
database. Run from the repository root:

    venv\\Scripts\\python.exe -m pytest backend/tests/test_timetable_cells_6r.py -q
"""
import hashlib
import os
import tempfile
import unittest

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _flat_classes(payload):
    return [cell["class"] for row in payload["day_rows"]
            for lane in row["lanes"] for cell in lane
            if not cell.get("empty")]


class RBase(unittest.TestCase):
    """Throwaway Flask app + small seeded timetable (all placements valid)."""

    def setUp(self):
        from flask import Flask
        from backend import models as m
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6r.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6R", working_days=DAYS,
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
        m.db.session.add(m.Subject(id=1, name="SUB1", enrollment_id=1))
        m.db.session.add(m.TeachingAssignment(
            id=1, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=2, block_length=1))
        m.db.session.add(m.TeachingAssignment(
            id=2, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=2, block_length=2))
        m.db.session.commit()
        from flask_login import LoginManager
        from backend.api_routes import init_api
        self.app.secret_key = "6r-test"
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

    def tearDown(self):
        try:
            self.m.db.session.remove()
            self.m.db.engine.dispose()
        except Exception:
            pass


class TestTimetableCellShape(RBase):
    def setUp(self):
        super().setUp()
        self.m.db.session.add(self.m.ScheduledClass(
            id=1, assignment_id=1, day="Mon", start_period=0,
            length=1, room_id=1, run_id="run1"))
        self.m.db.session.add(self.m.ScheduledClass(
            id=2, assignment_id=2, day="Tue", start_period=1,
            length=2, room_id=2, run_id="run1"))
        self.m.db.session.commit()

    def test_pre_6r_keys_untouched(self):
        resp = self.client.get("/api/timetable/section/1")
        self.assertEqual(resp.status_code, 200)
        classes = _flat_classes(resp.get_json())
        self.assertEqual(len(classes), 2)
        for cell in classes:
            for key in ("assignment_id", "subject", "faculty", "group",
                        "room", "session_type", "kind", "css_class",
                        "start_period", "length", "day"):
                self.assertIn(key, cell, f"missing key {key}")
        by_start = {(c["day"], c["start_period"]): c for c in classes}
        self.assertEqual(by_start[("Mon", 0)]["length"], 1)
        self.assertEqual(by_start[("Tue", 1)]["length"], 2)
        self.assertEqual(by_start[("Mon", 0)]["subject"], "SUB1")

    def test_plain_rows_default_to_unlocked_unspecialized(self):
        resp = self.client.get("/api/timetable/section/1")
        classes = _flat_classes(resp.get_json())
        for cell in classes:
            self.assertIn("is_locked", cell)
            self.assertIn("locked_block_id", cell)
            self.assertIn("specialization_id", cell)
            self.assertIn("specialization", cell)
            self.assertFalse(cell["is_locked"])
            self.assertIsNone(cell["locked_block_id"])
            self.assertIsNone(cell["specialization_id"])
            self.assertIsNone(cell["specialization"])

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
        resp = self.client.get("/api/timetable/section/1")
        by_start = {(c["day"], c["start_period"]): c
                    for c in _flat_classes(resp.get_json())}
        self.assertTrue(by_start[("Mon", 0)]["is_locked"])
        self.assertEqual(by_start[("Mon", 0)]["locked_block_id"], lb.id)
        self.assertFalse(by_start[("Tue", 1)]["is_locked"])

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
        resp = self.client.get("/api/timetable/section/1")
        # Section view excludes specialization assignments by design
        # (they belong to no section); the faculty view carries them.
        fac = self.client.get("/api/timetable/faculty/1")
        self.assertEqual(fac.status_code, 200)
        spec_cells = [c for c in _flat_classes(fac.get_json())
                      if c.get("specialization_id") == spec.id]
        self.assertEqual(len(spec_cells), 1)
        self.assertEqual(spec_cells[0]["specialization"], "Cyber")
        self.assertFalse(spec_cells[0]["is_locked"])

    def test_view_read_is_read_only(self):
        before = _sha(self.db_path)
        count_before = self.m.ScheduledClass.query.count()
        resp = self.client.get("/api/timetable/section/1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.m.ScheduledClass.query.count(), count_before)
        self.assertEqual(_sha(self.db_path), before)

    def test_invalid_view_still_404(self):
        resp = self.client.get("/api/timetable/cohort/1")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
