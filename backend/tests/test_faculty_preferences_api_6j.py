"""Phase 6J API tests: faculty custom-preference endpoints.

Covers list/create/update/delete through
GET|POST /api/faculty/<fid>/preferences,
POST /api/faculty/preferences/<pid>,
POST /api/faculty/preferences/<pid>/delete, plus unknown faculty/
preference codes, auth, invalid kind/days/periods/weight, hard-unsupported
rejection, deferred-kind rejection, structured error shape, schedule
immutability (ScheduledClass/LockedBlock/SpecializationSlot untouched),
and the end-to-end chain API -> DB -> scheduler preference.

Every test uses throwaway SQLite files in a temp dir — never the real
database. Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_faculty_preferences_api_6j -v
"""
import os
import tempfile
import unittest

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))


class PreferencesApiBase(unittest.TestCase):
    """Throwaway app + seeded school + logged-in API test client."""

    def setUp(self):
        from flask import Flask
        from flask_login import LoginManager
        from backend import models as m
        from backend.api_routes import init_api
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6japi.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.secret_key = "6japi-test"
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6JAPI", working_days=DAYS,
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
        m.db.session.add(m.Faculty(id=1, name="F1", weekly_max_hours=24))
        m.db.session.add(m.Faculty(id=2, name="F2", weekly_max_hours=24))
        m.db.session.add(m.Subject(id=1, name="SUB1", enrollment_id=1))
        m.db.session.add(m.TeachingAssignment(
            id=1, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=1, block_length=1))
        m.db.session.add(m.TeachingAssignment(
            id=2, faculty_id=2, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
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

    def _schedule_state(self):
        return (
            sorted((c.id, c.assignment_id, c.day, c.start_period, c.length,
                    c.room_id, c.run_id, bool(c.is_locked), c.slot_id,
                    c.locked_block_id)
                   for c in self.m.ScheduledClass.query.all()),
            sorted(lb.id for lb in self.m.LockedBlock.query.all()),
            sorted(s.id for s in self.m.SpecializationSlot.query.all()),
        )

    def _anon_post(self, path, payload):
        """Anonymous request with a pristine app context (see 6H.4: the
        harness's shared outer context would otherwise leak the login)."""
        self.ctx.pop()
        try:
            return self.anon.post(path, json=payload)
        finally:
            self.ctx.push()

    def _anon_get(self, path):
        self.ctx.pop()
        try:
            return self.anon.get(path)
        finally:
            self.ctx.push()


# ------------------------------------------------------- read + write
class TestPreferencesApi(PreferencesApiBase):
    def test_list_empty_with_context(self):
        resp = self.client.get("/api/faculty/1/preferences")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["faculty"], {"id": 1, "name": "F1"})
        self.assertEqual(body["days"], ["Mon", "Tue", "Wed"])
        self.assertEqual(body["num_periods"], 7)
        self.assertEqual(len(body["periods"]), 7)
        self.assertEqual(body["preferences"], [])

    def test_create_time_window(self):
        before = self._schedule_state()
        resp = self.client.post("/api/faculty/1/preferences", json={
            "kind": "TIME_WINDOW", "days": "Mon,Tue",
            "start_period": 0, "end_period": 3, "weight": 7})
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("Future", body["message"])
        self.assertIn("unchanged", body["message"])
        pref = body["preference"]
        self.assertEqual(pref["faculty_id"], 1)
        self.assertEqual(pref["kind"], "TIME_WINDOW")
        self.assertEqual(pref["days"], ["Mon", "Tue"])
        self.assertEqual((pref["start_period"], pref["end_period"],
                          pref["weight"]), (0, 3, 7))
        self.assertFalse(pref["is_hard"])
        self.assertTrue(pref["enabled"])
        # List reflects authoritative state; schedule untouched.
        listed = self.client.get("/api/faculty/1/preferences").get_json()
        self.assertEqual(len(listed["preferences"]), 1)
        self.assertEqual(self._schedule_state(), before)

    def test_create_day_off_and_defaults(self):
        resp = self.client.post("/api/faculty/2/preferences", json={
            "kind": "DAY_OFF_PREFERENCE", "days": ["Wed"]})
        self.assertEqual(resp.status_code, 201)
        pref = resp.get_json()["preference"]
        self.assertEqual(pref["days"], ["Wed"])
        self.assertIsNone(pref["start_period"])
        self.assertIsNone(pref["end_period"])
        self.assertEqual(pref["weight"], 5)
        self.assertTrue(pref["enabled"])

    def test_update_partial(self):
        pid = self.client.post("/api/faculty/1/preferences", json={
            "kind": "DAY_OFF_PREFERENCE", "days": "Mon"}).get_json()[
                "preference"]["id"]
        before = self._schedule_state()
        resp = self.client.post(f"/api/faculty/preferences/{pid}", json={
            "days": ["Tue", "Wed"], "enabled": False})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("unchanged", body["message"])
        self.assertEqual(body["preference"]["days"], ["Tue", "Wed"])
        self.assertFalse(body["preference"]["enabled"])
        self.assertEqual(self._schedule_state(), before)

    def test_update_kind_morph(self):
        pid = self.client.post("/api/faculty/1/preferences", json={
            "kind": "TIME_WINDOW", "days": "Mon",
            "start_period": 1, "end_period": 4}).get_json()[
                "preference"]["id"]
        resp = self.client.post(f"/api/faculty/preferences/{pid}", json={
            "kind": "DAY_OFF_PREFERENCE", "days": "Mon",
            "start_period": None, "end_period": None})
        self.assertEqual(resp.status_code, 200)
        pref = resp.get_json()["preference"]
        self.assertEqual(pref["kind"], "DAY_OFF_PREFERENCE")
        self.assertIsNone(pref["start_period"])

    def test_delete(self):
        pid = self.client.post("/api/faculty/1/preferences", json={
            "kind": "DAY_OFF_PREFERENCE", "days": "Mon"}).get_json()[
                "preference"]["id"]
        before = self._schedule_state()
        resp = self.client.post(f"/api/faculty/preferences/{pid}/delete")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("unchanged", body["message"])
        self.assertEqual(
            self.client.get("/api/faculty/1/preferences").get_json()[
                "preferences"], [])
        self.assertEqual(self._schedule_state(), before)

    def test_unknown_faculty_404(self):
        for method in ("get", "post"):
            client = getattr(self.client, method)
            resp = client("/api/faculty/999/preferences",
                          json={"kind": "DAY_OFF_PREFERENCE",
                                "days": "Mon"} if method == "post" else None)
            self.assertEqual(resp.status_code, 404, method)
            body = resp.get_json()
            self.assertEqual(body["code"], "UNKNOWN_FACULTY")
            self.assertIn("failures", body)

    def test_unknown_preference_404(self):
        resp = self.client.post("/api/faculty/preferences/999",
                                json={"days": "Mon"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "UNKNOWN_PREFERENCE")
        resp = self.client.post("/api/faculty/preferences/999/delete")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "UNKNOWN_PREFERENCE")

    def test_invalid_inputs(self):
        cases = [
            ({"kind": "NOPE"}, "PREF_INVALID_KIND"),
            ({}, "PREF_INVALID_KIND"),
            ({"kind": "SUBJECT_AFFINITY", "days": "Mon"},
             "PREF_INVALID_KIND"),
            ({"kind": "DAY_OFF_PREFERENCE", "days": "Mon",
              "is_hard": True}, "PREF_HARD_UNSUPPORTED"),
            ({"kind": "DAY_OFF_PREFERENCE", "days": "Funday"},
             "PREF_INVALID_DAYS"),
            ({"kind": "DAY_OFF_PREFERENCE", "days": ""},
             "PREF_INVALID_DAYS"),
            ({"kind": "DAY_OFF_PREFERENCE", "days": "Mon",
              "start_period": 0}, "PREF_INVALID_PERIOD"),
            ({"kind": "TIME_WINDOW", "days": "Mon"},
             "PREF_INVALID_PERIOD"),
            ({"kind": "TIME_WINDOW", "days": "Mon", "start_period": 2,
              "end_period": 2}, "PREF_INVALID_PERIOD"),
            ({"kind": "TIME_WINDOW", "days": "Mon", "start_period": 0,
              "end_period": 99}, "PREF_INVALID_PERIOD"),
            ({"kind": "DAY_OFF_PREFERENCE", "days": "Mon",
              "weight": 99}, "PREF_INVALID_WEIGHT"),
        ]
        before = self._schedule_state()
        for payload, code in cases:
            resp = self.client.post("/api/faculty/1/preferences",
                                    json=payload)
            self.assertEqual(resp.status_code, 422, payload)
            body = resp.get_json()
            self.assertEqual(body["code"], code, payload)
            self.assertIn("error", body)
            self.assertIn("failures", body)
            self.assertTrue(body["failures"], payload)
            self.assertEqual(body["failures"][0]["code"], code, payload)
        # Nothing persisted; schedule untouched.
        self.assertEqual(
            self.client.get("/api/faculty/1/preferences").get_json()[
                "preferences"], [])
        self.assertEqual(self._schedule_state(), before)

    def test_auth_required(self):
        self.assertEqual(
            self._anon_get("/api/faculty/1/preferences").status_code, 401)
        self.assertEqual(
            self._anon_post("/api/faculty/1/preferences",
                            {"kind": "DAY_OFF_PREFERENCE",
                             "days": "Mon"}).status_code, 401)
        self.assertEqual(
            self._anon_post("/api/faculty/preferences/1",
                            {"days": "Mon"}).status_code, 401)
        self.assertEqual(
            self._anon_post("/api/faculty/preferences/1/delete",
                            {}).status_code, 401)

    def test_end_to_end_api_to_scheduler(self):
        """A preference created via the API reaches the solver as a soft
        tie-break: with Mon/Tue time-tied, a Tue window pulls F1's class
        to Tue while F2 (no prefs) stays wherever time puts it."""
        from backend.scheduler import run_scheduler
        # Second room + second section already seeded; place nothing new.
        self.client.post("/api/faculty/1/preferences", json={
            "kind": "TIME_WINDOW", "days": "Tue",
            "start_period": 0, "end_period": 2})
        rows = self.m.FacultyPreference.query.all()
        self.assertEqual(len(rows), 1)
        assignments = self.m.TeachingAssignment.query.all()
        rooms = self.m.Room.query.all()
        status, placements, _ = run_scheduler(
            assignments, rooms, {}, ["Mon", "Tue"], 2, None, None,
            time_limit_seconds=10, faculty_preferences=rows)
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        by_aid = {p["assignment_id"]: p for p in placements}
        self.assertEqual(by_aid[1]["day"], "Tue")
        # Seeded timetable rows are byte-identical (API never reschedules).
        sc = self.m.ScheduledClass.query.get(1)
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Mon", 0, 2))


if __name__ == "__main__":
    unittest.main()
