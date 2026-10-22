"""Phase 6I.4 tests: preferred theory room configuration API.

Covers GET exposure (null + set), set/change/clear through
POST /api/sections/<id>/preferred-room, unknown section/room codes,
auth, invalid input, soft semantics for non-theory rooms, schedule
immutability (set + clear), no scheduler invocation, and the end to
end chain API -> DB -> scheduler preference.

Every test uses throwaway SQLite files in a temp dir — never the real
database. Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_preferred_room_api_6i -v
"""
import os
import tempfile
import unittest
from unittest import mock

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))


class PreferredApiBase(unittest.TestCase):
    """Throwaway app + seeded school + logged-in API test client."""

    def setUp(self):
        from flask import Flask
        from flask_login import LoginManager
        from backend import models as m
        from backend.api_routes import init_api
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6i4.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.secret_key = "6i4-test"
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6I4", working_days=DAYS,
                                  periods=PERIODS, break_after_periods=4,
                                  max_consecutive_teaching=3))
        m.db.session.add(m.Program(id=1, name="BCA"))
        m.db.session.add(m.Enrollment(id=1, program_id=1, year_label="Y1",
                                      total_students=60))
        m.db.session.add(m.Section(id=1, enrollment_id=1, name="BCA-1-A",
                                   student_count=30))
        m.db.session.add(m.Section(id=2, enrollment_id=1, name="BCA-1-B",
                                   student_count=30))
        m.db.session.add(m.Room(id=1, name="R101", room_type="theory",
                                capacity=100))
        m.db.session.add(m.Room(id=2, name="R102", room_type="theory",
                                capacity=100))
        m.db.session.add(m.Room(id=3, name="L1", room_type="lab", capacity=40,
                                equipment_count=40))
        m.db.session.add(m.Faculty(id=1, name="F1", weekly_max_hours=24))
        m.db.session.add(m.Subject(id=1, name="SUB1", enrollment_id=1))
        m.db.session.add(m.TeachingAssignment(
            id=1, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=1, block_length=1))
        m.db.session.commit()
        self._place(1, 1, "Mon", 0, 1, 2)  # SC1 A1 Mon P0 R102

        lm = LoginManager()
        lm.init_app(self.app)

        @lm.user_loader
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

    def tearDown(self):
        try:
            self.m.db.session.remove()
            self.m.db.engine.dispose()
        except Exception:
            pass

    # -- helpers ------------------------------------------------------
    def _place(self, cid, aid, day, start, length, room, run_id="run1"):
        self.m.db.session.add(self.m.ScheduledClass(
            id=cid, assignment_id=aid, day=day, start_period=start,
            length=length, room_id=room, run_id=run_id))
        self.m.db.session.commit()

    def _rows(self):
        return sorted(
            (c.id, c.assignment_id, c.day, c.start_period, c.length,
             c.room_id, c.run_id, bool(c.is_locked), c.slot_id,
             c.locked_block_id)
            for c in self.m.ScheduledClass.query.all())

    def _state(self):
        return (self._rows(),
                sorted((lb.id, lb.assignment_id)
                       for lb in self.m.LockedBlock.query.all()),
                sorted((s.id, s.specialization_id)
                       for s in self.m.SpecializationSlot.query.all()))

    def _pref(self, sid=1):
        return self.m.Section.query.get(sid).preferred_theory_room_id

    def _anon_post(self, path, payload):
        """Anonymous request with a pristine app context (see 6H.4: the
        harness's shared outer context would otherwise leak the login)."""
        self.ctx.pop()
        try:
            return self.anon.post(path, json=payload)
        finally:
            self.ctx.push()


# ------------------------------------------------------- read + write
class TestPreferredRoomApi(PreferredApiBase):
    def test_get_exposes_null_preference(self):
        resp = self.client.get("/api/enrollments/1/sections")
        self.assertEqual(resp.status_code, 200)
        secs = {s["id"]: s for s in resp.get_json()["sections"]}
        self.assertIsNone(secs[1]["preferred_theory_room_id"])
        # Compact section lists expose the same key.
        resp = self.client.get("/api/assignments")
        self.assertEqual(resp.status_code, 200)
        for s in resp.get_json()["sections"]:
            self.assertIn("preferred_theory_room_id", s)

    def test_set_valid_room(self):
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": 1})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["section"]["id"], 1)
        self.assertEqual(body["section"]["preferred_theory_room_id"], 1)
        self.assertIsNone(body["warning"])
        self.assertEqual(self._pref(), 1)

    def test_change_room(self):
        self.client.post("/api/sections/1/preferred-room",
                         json={"room_id": 1})
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": 2})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["section"]
                         ["preferred_theory_room_id"], 2)
        self.assertEqual(self._pref(), 2)

    def test_clear_preference(self):
        self.client.post("/api/sections/1/preferred-room",
                         json={"room_id": 1})
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": None})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.get_json()["section"]
                          ["preferred_theory_room_id"])
        self.assertEqual(self._pref(), None)

    def test_unknown_room(self):
        self.client.post("/api/sections/1/preferred-room",
                         json={"room_id": 1})
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": 999})
        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertEqual(body["code"], "UNKNOWN_ROOM")
        self.assertEqual(body["details"]["room_id"], 999)
        self.assertTrue(body["failures"])
        self.assertEqual(self._pref(), 1)

    def test_unknown_section(self):
        resp = self.client.post("/api/sections/999/preferred-room",
                                json={"room_id": 1})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "UNKNOWN_SECTION")

    def test_requires_auth(self):
        resp = self._anon_post("/api/sections/1/preferred-room",
                               {"room_id": 1})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self._pref(), None)

    def test_invalid_input(self):
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": "abc"})
        self.assertEqual(resp.status_code, 422)
        self.assertIn("room_id", resp.get_json().get("field_errors", {}))
        resp = self.client.post("/api/sections/1/preferred-room", json={})
        self.assertEqual(resp.status_code, 422)
        self.assertIn("room_id", resp.get_json().get("field_errors", {}))
        self.assertEqual(self._pref(), None)

    def test_lab_room_accepted_with_warning(self):
        # Soft semantics: a lab is accepted (scheduling-time concern),
        # with an administrative warning, never a rejection.
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": 3})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertEqual(body["section"]["preferred_theory_room_id"], 3)
        self.assertIsNotNone(body["warning"])
        self.assertEqual(self._pref(), 3)


# ------------------------------------------------------- safety
class TestScheduleUntouched(PreferredApiBase):
    def test_set_leaves_schedule_unchanged(self):
        before = self._state()
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._state(), before)
        sc = self.m.ScheduledClass.query.get(1)
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Mon", 0, 2))

    def test_clear_leaves_schedule_unchanged(self):
        self.client.post("/api/sections/1/preferred-room",
                         json={"room_id": 1})
        before = self._state()
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": None})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._state(), before)

    def test_no_scheduler_invocation(self):
        import backend.api_routes as routes
        with mock.patch.object(routes, "run_scheduler",
                               side_effect=AssertionError("must not run")):
            self.client.post("/api/sections/1/preferred-room",
                             json={"room_id": 1})
            self.client.post("/api/sections/1/preferred-room",
                             json={"room_id": None})


# ------------------------------------------------------- end to end
class TestSchedulerSeesPreference(PreferredApiBase):
    def _placed_rooms(self):
        view = self.client.get("/api/timetable/section/1")
        self.assertEqual(view.status_code, 200)
        rooms = set()
        for row in view.get_json().get("day_rows", []):
            for lane in row.get("lanes", []):
                for cell in lane:
                    if not cell.get("empty"):
                        rooms.add(cell["class"]["room"])
        return rooms

    def test_api_configuration_drives_next_generation(self):
        # Two tied rooms; run once without preference, then prefer the
        # room that was NOT chosen: the next generation must flip to it.
        first = self.client.post("/api/schedule/run")
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        first_rooms = self._placed_rooms()
        self.assertEqual(len(first_rooms), 1)
        first_room = next(iter(first_rooms))
        other_id = 1 if first_room == "R102" else 2
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": other_id})
        self.assertEqual(resp.status_code, 200)
        second = self.client.post("/api/schedule/run")
        self.assertEqual(second.status_code, 200,
                         second.get_data(as_text=True))
        expected = "R101" if other_id == 1 else "R102"
        self.assertEqual(self._placed_rooms(), {expected})


if __name__ == "__main__":
    unittest.main()
