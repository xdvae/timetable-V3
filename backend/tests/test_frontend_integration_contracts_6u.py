"""Phase 6U tests: frontend/backend integration contracts.

Proves the exact payloads the Phase 6P-6T frontend sends still match the
Flask API, through the real stack (throwaway SQLite files in a temp dir
-- never the reference databases):

* auth/session contract (login/me/logout/unauthorized)
* timetable editor contracts (classes/validate-move/move/free faculty)
* reassignment + swap contracts (dry-run vs authoritative, noop, locks)
* specialization / locked-block / preferred-room / preference contracts
* generation status mapping (OPTIMAL/FEASIBLE/INFEASIBLE/UNKNOWN/MODEL_INVALID)
* read-only safety (GETs + dry-runs change nothing, scheduler untouched)
* HTTP method semantics (405 JSON contract)

Run from the repository root:

    venv\\Scripts\\python.exe -m pytest backend\\tests\\test_frontend_integration_contracts_6u.py -q
"""
import os
import tempfile
import unittest
from unittest import mock

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))


class FrontendContract6UBase(unittest.TestCase):
    """Throwaway app + seeded school + logged-in API test client."""

    def setUp(self):
        from flask import Flask
        from flask_login import LoginManager
        from backend import models as m
        from backend.api_routes import init_api
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6u.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.secret_key = "6u-test"
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6U", working_days=DAYS,
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
        m.db.session.add(m.Faculty(id=1, name="F1", weekly_max_hours=24))
        m.db.session.add(m.Faculty(id=2, name="F2", weekly_max_hours=24))
        m.db.session.add(m.Subject(id=1, name="SUB1", enrollment_id=1))
        m.db.session.add(m.TeachingAssignment(
            id=1, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=2, block_length=1))
        m.db.session.add(m.TeachingAssignment(
            id=2, faculty_id=2, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=2, block_length=1))
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
        self.anon = self.app.test_client()

    def tearDown(self):
        try:
            self.m.db.session.remove()
            self.m.db.engine.dispose()
        except Exception:
            pass

    def _anon(self, method, path, payload=None):
        self.ctx.pop()
        try:
            if method == "get":
                return self.anon.get(path)
            return self.anon.post(path, json=payload or {})
        finally:
            self.ctx.push()

    def _counts(self):
        m = self.m
        return {
            "scheduled": m.ScheduledClass.query.count(),
            "assignments": m.TeachingAssignment.query.count(),
            "locked": m.LockedBlock.query.count(),
            "specs": m.Specialization.query.count(),
            "prefs": m.FacultyPreference.query.count(),
        }

    def _schedule_rows(self):
        return [(r.assignment_id, r.day, r.start_period, r.length, r.room_id)
                for r in self.m.ScheduledClass.query.order_by(
                    self.m.ScheduledClass.id).all()]

    def _seed_class(self, assignment_id=1, day="Mon", start=0, room_id=1):
        m = self.m
        sc = m.ScheduledClass(assignment_id=assignment_id, day=day,
                              start_period=start, length=1, room_id=room_id,
                              run_id="seed6u")
        m.db.session.add(sc)
        m.db.session.commit()
        return sc.id


class TestAuthContracts(FrontendContract6UBase):
    def test_login_success_shape(self):
        resp = self.client.post("/api/login",
                                json={"username": "admin",
                                      "password": "password123"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["username"], "admin")

    def test_login_failure_is_401_invalid_credentials(self):
        # A fresh (unauthenticated) client: the logged-in harness client
        # would get 200 "Already signed in." on any credential POST.
        self.ctx.pop()
        try:
            resp = self.anon.post("/api/login",
                                  json={"username": "admin",
                                        "password": "wrong"})
        finally:
            self.ctx.push()
        self.assertEqual(resp.status_code, 401)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "INVALID_CREDENTIALS")
        self.assertIsInstance(body["error"], str)

    def test_me_and_logout(self):
        me = self.client.get("/api/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json()["username"], "admin")
        out = self.client.post("/api/logout")
        self.assertEqual(out.status_code, 200)

    def test_unauthenticated_read_is_401_json_not_html(self):
        resp = self._anon("get", "/api/schedule/classes")
        self.assertEqual(resp.status_code, 401)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "AUTH_REQUIRED")
        self.assertNotIn("<html", resp.get_data(as_text=True).lower())

    def test_unauthenticated_mutation_is_401_json(self):
        resp = self._anon("post", "/api/assignments/1/reassign",
                          {"faculty_id": 2})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.get_json()["code"], "AUTH_REQUIRED")


class TestTimetableEditorContracts(FrontendContract6UBase):
    def test_schedule_classes_read_shape(self):
        self._seed_class()
        resp = self.client.get("/api/schedule/classes")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        for key in ("classes", "days", "periods", "has_schedule"):
            self.assertIn(key, body)
        self.assertTrue(body["has_schedule"])
        row = body["classes"][0]
        for key in ("id", "assignment_id", "day", "start_period", "length",
                    "room_id", "is_locked", "faculty_id"):
            self.assertIn(key, row)

    def test_validate_move_dry_run_changes_nothing(self):
        cid = self._seed_class()
        before = self._schedule_rows()
        resp = self.client.post(f"/api/schedule/classes/{cid}/validate-move",
                                json={"day": "Tue", "start_period": 1,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("noop", body)
        self.assertIn("candidate", body)
        self.assertEqual(self._schedule_rows(), before)

    def test_move_success_relocates_one_class(self):
        cid = self._seed_class()
        resp = self.client.post(f"/api/schedule/classes/{cid}/move",
                                json={"day": "Tue", "start_period": 1,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["noop"])
        self.assertIn("scheduled_class", body)
        sc = self.m.ScheduledClass.query.get(cid)
        self.assertEqual((sc.day, sc.start_period), ("Tue", 1))

    def test_move_noop_same_position(self):
        cid = self._seed_class()
        resp = self.client.post(f"/api/schedule/classes/{cid}/move",
                                json={"day": "Mon", "start_period": 0,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["noop"])

    def test_locked_class_move_rejected_and_preserved(self):
        resp = self.client.post("/api/locked-blocks",
                                json={"assignment_id": 1, "day": "Mon",
                                      "start_period": 0, "length": 1,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 201)
        sc_id = resp.get_json()["scheduled_class"]["id"]
        before = self._schedule_rows()
        move = self.client.post(f"/api/schedule/classes/{sc_id}/move",
                                json={"day": "Tue", "start_period": 1,
                                      "room_id": 1})
        self.assertEqual(move.status_code, 422)
        self.assertEqual(move.get_json()["code"], "LOCKED_BLOCK")
        self.assertEqual(self._schedule_rows(), before)

    def test_failed_move_preserves_placement(self):
        cid = self._seed_class()
        before = self._schedule_rows()
        resp = self.client.post(f"/api/schedule/classes/{cid}/move",
                                json={"day": "NoDay", "start_period": 0,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(self._schedule_rows(), before)

    def test_free_faculty_and_timetable_reads(self):
        for path in ("/api/timetable", "/api/timetable/free?day=Mon",
                     "/api/timetable/section/1"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, path)

    def test_unknown_timetable_view_is_404_json(self):
        resp = self.client.get("/api/timetable/section/9999")
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.get_json()["ok"])


class TestReassignSwapContracts(FrontendContract6UBase):
    def test_validate_reassign_dry_run_changes_nothing(self):
        before = self.m.TeachingAssignment.query.get(1).faculty_id
        resp = self.client.post("/api/assignments/1/validate-reassign",
                                json={"faculty_id": 2})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["dry_run"])
        self.assertEqual(self.m.TeachingAssignment.query.get(1).faculty_id,
                         before)

    def test_reassign_success_changes_faculty(self):
        resp = self.client.post("/api/assignments/1/reassign",
                                json={"faculty_id": 2})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("assignment", body)
        self.assertEqual(self.m.TeachingAssignment.query.get(1).faculty_id, 2)

    def test_reassign_noop_same_faculty(self):
        resp = self.client.post("/api/assignments/1/reassign",
                                json={"faculty_id": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["noop"])

    def test_reassign_locked_assignment_rejected(self):
        created = self.client.post(
            "/api/locked-blocks",
            json={"assignment_id": 1, "day": "Mon", "start_period": 0,
                  "length": 1, "room_id": 1})
        self.assertEqual(created.status_code, 201)
        resp = self.client.post("/api/assignments/1/reassign",
                                json={"faculty_id": 2})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "LOCKED_BLOCK")
        self.assertEqual(self.m.TeachingAssignment.query.get(1).faculty_id, 1)

    def test_swap_success_exchanges_faculties(self):
        resp = self.client.post("/api/assignments/swap",
                                json={"assignment_a_id": 1,
                                      "assignment_b_id": 2})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("assignments", body)
        self.assertEqual(self.m.TeachingAssignment.query.get(1).faculty_id, 2)
        self.assertEqual(self.m.TeachingAssignment.query.get(2).faculty_id, 1)

    def test_validate_swap_dry_run_changes_nothing(self):
        resp = self.client.post("/api/assignments/validate-swap",
                                json={"assignment_a_id": 1,
                                      "assignment_b_id": 2})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["dry_run"])
        self.assertEqual(self.m.TeachingAssignment.query.get(1).faculty_id, 1)
        self.assertEqual(self.m.TeachingAssignment.query.get(2).faculty_id, 2)

    def test_failed_swap_is_atomic(self):
        created = self.client.post(
            "/api/locked-blocks",
            json={"assignment_id": 1, "day": "Mon", "start_period": 0,
                  "length": 1, "room_id": 1})
        self.assertEqual(created.status_code, 201)
        resp = self.client.post("/api/assignments/swap",
                                json={"assignment_a_id": 1,
                                      "assignment_b_id": 2})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(self.m.TeachingAssignment.query.get(1).faculty_id, 1)
        self.assertEqual(self.m.TeachingAssignment.query.get(2).faculty_id, 2)


class TestSpecializationContracts(FrontendContract6UBase):
    def _create_spec(self):
        resp = self.client.post("/api/specializations",
                                json={"name": "AI", "enrollment_id": 1})
        self.assertEqual(resp.status_code, 201, resp.get_data(as_text=True))
        return resp.get_json()["specialization"]["id"]

    def test_crud_round_trip(self):
        sid = self._create_spec()
        listed = self.client.get("/api/specializations")
        self.assertEqual(listed.status_code, 200)
        self.assertIn("specializations", listed.get_json())
        detail = self.client.get(f"/api/specializations/{sid}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("specialization", detail.get_json())
        mem = self.client.post(f"/api/specializations/{sid}/memberships",
                               json={"section_id": 1, "student_count": 20})
        self.assertIn(mem.status_code, (200, 201))
        unmem = self.client.post(
            f"/api/specializations/{sid}/memberships/delete",
            json={"section_id": 1})
        self.assertEqual(unmem.status_code, 200)
        deleted = self.client.post(f"/api/specializations/{sid}/delete")
        self.assertEqual(deleted.status_code, 200)
        self.assertIsNone(self.m.Specialization.query.get(sid))

    def test_create_requires_name(self):
        resp = self.client.post("/api/specializations",
                                json={"enrollment_id": 1})
        self.assertEqual(resp.status_code, 422)


class TestLockedBlockContracts(FrontendContract6UBase):
    def test_create_and_delete_round_trip(self):
        resp = self.client.post("/api/locked-blocks",
                                json={"assignment_id": 1, "day": "Mon",
                                      "start_period": 0, "length": 1,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("locked_block", body)
        self.assertIn("scheduled_class", body)
        bid = body["locked_block"]["id"]
        listed = self.client.get("/api/locked-blocks")
        self.assertEqual(listed.status_code, 200)
        self.assertIn("locked_blocks", listed.get_json())
        deleted = self.client.post(f"/api/locked-blocks/{bid}/delete")
        self.assertEqual(deleted.status_code, 200)
        self.assertIsNone(self.m.LockedBlock.query.get(bid))

    def test_double_booking_conflict_rejected(self):
        first = self.client.post("/api/locked-blocks",
                                 json={"assignment_id": 1, "day": "Mon",
                                       "start_period": 0, "length": 1,
                                       "room_id": 1})
        self.assertEqual(first.status_code, 201)
        second = self.client.post("/api/locked-blocks",
                                  json={"assignment_id": 2, "day": "Mon",
                                        "start_period": 0, "length": 1,
                                        "room_id": 1})
        self.assertEqual(second.status_code, 422)
        body = second.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("code", body)

    def test_delete_missing_is_404(self):
        resp = self.client.post("/api/locked-blocks/9999/delete")
        self.assertEqual(resp.status_code, 404)


class TestPreferredRoomContracts(FrontendContract6UBase):
    def test_set_and_clear(self):
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": 1})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("section", body)
        cleared = self.client.post("/api/sections/1/preferred-room",
                                   json={"room_id": None})
        self.assertEqual(cleared.status_code, 200)

    def test_unknown_section_and_room(self):
        missing_section = self.client.post(
            "/api/sections/9999/preferred-room", json={"room_id": 1})
        self.assertEqual(missing_section.status_code, 404)
        self.assertEqual(missing_section.get_json()["code"],
                         "UNKNOWN_SECTION")
        missing_room = self.client.post("/api/sections/1/preferred-room",
                                        json={"room_id": 9999})
        self.assertEqual(missing_room.status_code, 404)
        self.assertEqual(missing_room.get_json()["code"], "UNKNOWN_ROOM")

    def test_existing_schedule_untouched_by_preference(self):
        self._seed_class()
        before = self._schedule_rows()
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._schedule_rows(), before)


class TestFacultyPreferenceContracts(FrontendContract6UBase):
    def test_crud_round_trip(self):
        created = self.client.post("/api/faculty/1/preferences",
                                   json={"kind": "DAY_OFF_PREFERENCE",
                                         "days": ["Mon"]})
        self.assertEqual(created.status_code, 201, created.get_data(as_text=True))
        pid = created.get_json()["preference"]["id"]
        listed = self.client.get("/api/faculty/1/preferences")
        self.assertEqual(listed.status_code, 200)
        self.assertIn("preferences", listed.get_json())
        updated = self.client.post(f"/api/faculty/preferences/{pid}",
                                   json={"weight": 7})
        self.assertEqual(updated.status_code, 200)
        deleted = self.client.post(
            f"/api/faculty/preferences/{pid}/delete")
        self.assertEqual(deleted.status_code, 200)

    def test_hard_preference_rejected(self):
        resp = self.client.post("/api/faculty/1/preferences",
                                json={"kind": "DAY_OFF_PREFERENCE",
                                      "days": ["Mon"], "is_hard": True})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "PREF_HARD_UNSUPPORTED")

    def test_unsupported_kind_rejected(self):
        resp = self.client.post("/api/faculty/1/preferences",
                                json={"kind": "SUBJECT_AFFINITY"})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "PREF_INVALID_KIND")

    def test_unknown_faculty_is_404(self):
        resp = self.client.get("/api/faculty/9999/preferences")
        self.assertEqual(resp.status_code, 404)


class TestGenerationContracts(FrontendContract6UBase):
    def _mock_run(self, status, placements, message):
        return mock.patch("backend.api_routes.run_scheduler",
                          return_value=(status, placements, message))

    def test_optimal_success_shape(self):
        placements = [{"assignment_id": 1, "day": "Mon", "start_period": 0,
                       "length": 1, "room_id": 1}]
        with self._mock_run("OPTIMAL", placements, "ok"):
            resp = self.client.post("/api/schedule/run", json={})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "OPTIMAL")
        self.assertEqual(body["placements"], 1)
        self.assertIn("run_id", body)

    def test_infeasible_preserves_previous_schedule(self):
        self._seed_class()
        before = self._schedule_rows()
        with self._mock_run("INFEASIBLE", [], "No valid timetable."):
            resp = self.client.post("/api/schedule/run", json={})
        self.assertEqual(resp.status_code, 422)
        self.assertFalse(resp.get_json()["ok"])
        self.assertEqual(self._schedule_rows(), before)

    def test_unknown_is_timeout_never_infeasible(self):
        self._seed_class()
        before = self._schedule_rows()
        with self._mock_run("UNKNOWN", [], "time limit reached"):
            resp = self.client.post("/api/schedule/run", json={})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "SCHEDULING_FAILED")
        self.assertTrue(body["details"]["timeout"])
        self.assertNotIn("INFEASIBLE", resp.get_data(as_text=True))
        self.assertNotIn("infeasible", body["error"].lower())
        self.assertEqual(self._schedule_rows(), before)

    def test_model_invalid_sanitized_and_preserves_schedule(self):
        self._seed_class()
        before = self._schedule_rows()
        with self._mock_run("MODEL_INVALID", [], "solver /tmp/secret.db"):
            resp = self.client.post("/api/schedule/run", json={})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json()["code"], "INTERNAL_ERROR")
        text = resp.get_data(as_text=True)
        self.assertNotIn("secret", text)
        self.assertEqual(self._schedule_rows(), before)


class TestReadOnlyAndMethodSafety(FrontendContract6UBase):
    READ_PATHS = ("/api/schedule/classes", "/api/timetable",
                  "/api/timetable/free", "/api/assignments", "/api/faculty",
                  "/api/rooms", "/api/overview", "/api/dashboard",
                  "/api/config", "/api/programs", "/api/subjects",
                  "/api/enrollments", "/api/specializations",
                  "/api/locked-blocks", "/api/faculty/1/preferences")

    def test_read_only_gets_change_nothing(self):
        self._seed_class()
        before = (self._counts(), self._schedule_rows())
        for path in self.READ_PATHS:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, path)
        self.assertEqual((self._counts(), self._schedule_rows()), before)

    def test_dry_runs_change_nothing(self):
        self._seed_class()
        cid = self.m.ScheduledClass.query.first().id
        before = (self._counts(), self._schedule_rows())
        self.client.post(f"/api/schedule/classes/{cid}/validate-move",
                         json={"day": "Tue", "start_period": 1, "room_id": 1})
        self.client.post("/api/assignments/1/validate-reassign",
                         json={"faculty_id": 2})
        self.client.post("/api/assignments/validate-swap",
                         json={"assignment_a_id": 1, "assignment_b_id": 2})
        self.assertEqual((self._counts(), self._schedule_rows()), before)

    def test_reads_never_invoke_scheduler(self):
        with mock.patch("backend.api_routes.run_scheduler") as run:
            for path in self.READ_PATHS:
                self.client.get(path)
            cid = self._seed_class()
            self.client.post(
                f"/api/schedule/classes/{cid}/validate-move",
                json={"day": "Tue", "start_period": 1, "room_id": 1})
        run.assert_not_called()

    def test_wrong_method_is_405_json(self):
        resp = self.client.get("/api/schedule/run")
        self.assertEqual(resp.status_code, 405)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "METHOD_NOT_ALLOWED")


if __name__ == "__main__":
    unittest.main()
