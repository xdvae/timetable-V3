"""Phase 6Q tests: unified error system (contract + integration + safety).

Covers representative backend error surfaces through the real Flask stack
(throwaway SQLite files in a temp dir — never the reference databases):

* unified contract: ok:false marker + stable code + legacy keys intact
* structured errors, field errors, details preservation
* unknown/internal exception sanitization (no traceback/SQL/path/secret)
* auth (401), not-found (404), validation (422), scheduler failure
* manual-edit / reassignment / swap / specialization / locked-block /
  preference / CSV-import failures
* validation-only vs authoritative-mutation distinguishability

Run from the repository root:

    venv\\Scripts\\python.exe -m pytest backend\\tests\\test_errors_6q.py -q
"""
import io
import os
import tempfile
import unittest
from unittest import mock

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))


class Errors6QBase(unittest.TestCase):
    """Throwaway app + seeded school + logged-in API test client."""

    def setUp(self):
        from flask import Flask
        from flask_login import LoginManager
        from backend import models as m
        from backend.api_routes import init_api
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6q.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.secret_key = "6q-test"
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6Q", working_days=DAYS,
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

    def _anon_get(self, path):
        self.ctx.pop()
        try:
            return self.anon.get(path)
        finally:
            self.ctx.push()

    def _anon_post(self, path, payload):
        """Anonymous request with a pristine app context (the harness's
        shared outer context would otherwise leak the login)."""
        self.ctx.pop()
        try:
            return self.anon.post(path, json=payload)
        finally:
            self.ctx.push()


class TestErrorContract(unittest.TestCase):
    """Pure contract unit tests (no Flask app needed)."""

    def test_unified_shape_additive(self):
        from backend.errors import error_payload
        body = error_payload(code="ROOM_CONFLICT", message="Taken.", status=422,
                             details={"day": "Mon"},
                             field_errors={"room": "Taken."},
                             failures=[{"code": "ROOM_CONFLICT",
                                        "message": "Taken.", "details": {}}])
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "Taken.")
        self.assertEqual(body["code"], "ROOM_CONFLICT")
        self.assertEqual(body["details"], {"day": "Mon"})
        self.assertEqual(body["field_errors"], {"room": "Taken."})
        self.assertEqual(len(body["failures"]), 1)

    def test_unset_keys_omitted(self):
        from backend.errors import error_payload
        body = error_payload(code="X", message="m")
        self.assertNotIn("details", body)
        self.assertNotIn("field_errors", body)
        self.assertNotIn("failures", body)

    def test_message_sanitized(self):
        from backend.errors import error_payload
        self.assertEqual(error_payload(code="X", message=None)["error"],
                         "The operation could not be completed.")
        self.assertEqual(error_payload(code="X", message="  ")["error"],
                         "The operation could not be completed.")

    def test_secret_like_detail_keys_dropped(self):
        from backend.errors import error_payload
        body = error_payload(code="X", message="m",
                             details={"day": "Mon", "password": "s3cret",
                                      "traceback": "frame..."})
        self.assertEqual(body["details"], {"day": "Mon"})

    def test_field_errors_normalized(self):
        from backend.errors import error_payload
        body = error_payload(code="X", message="m",
                             field_errors={"a": "bad", "b": {"o": 1},
                                           "c": None, "d": ["x", "y"]})
        self.assertEqual(body["field_errors"],
                         {"a": "bad", "d": "x, y"})

    def test_category_semantics(self):
        from backend.errors import category_for
        self.assertEqual(category_for(401), "auth")
        self.assertEqual(category_for(404), "not_found")
        self.assertEqual(category_for(422), "validation")
        self.assertEqual(category_for(422, "SCHEDULING_INFEASIBLE"), "scheduler")
        self.assertEqual(category_for(500), "internal")


class TestApiErrorSurfaces(Errors6QBase):
    def test_structured_error_preserved(self):
        resp = self.client.post("/api/sections/1/preferred-room",
                                json={"room_id": 999})
        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "UNKNOWN_ROOM")
        self.assertIn("error", body)
        self.assertIn("details", body)

    def test_field_errors_preserved(self):
        resp = self.client.post("/api/change-password",
                                json={"current_password": "password123",
                                      "new_password": "short",
                                      "confirm_password": "short"})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["field_errors"]["new_password"],
                         "New password must be at least 8 characters.")

    def test_auth_failures_distinguishable(self):
        bad = self._anon_post("/api/login",
                              {"username": "admin",
                               "password": "wrong"})
        self.assertEqual(bad.status_code, 401)
        bad_body = bad.get_json()
        self.assertEqual(bad_body["code"], "INVALID_CREDENTIALS")
        self.assertEqual(bad_body["error"], "Incorrect username or password.")
        anon = self._anon_get("/api/rooms")
        self.assertEqual(anon.status_code, 401)
        self.assertEqual(anon.get_json()["code"], "AUTH_REQUIRED")

    def test_not_found_has_code(self):
        resp = self.client.get("/api/definitely-not-here")
        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertEqual(body["code"], "NOT_FOUND")
        self.assertFalse(body["ok"])

    def test_validation_error_has_marker(self):
        resp = self.client.post("/api/rooms", json={})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("field_errors", body)

    def test_status_code_semantics_distinct(self):
        login = self._anon_post("/api/login",
                                {"username": "admin",
                                 "password": "wrong"})
        validation = self.client.post("/api/rooms", json={})
        missing = self.client.get("/api/definitely-not-here")
        self.assertEqual(
            (login.status_code, validation.status_code, missing.status_code),
            (401, 422, 404))
        codes = {login.get_json()["code"], validation.get_json().get("code"),
                 missing.get_json()["code"]}
        self.assertIn("INVALID_CREDENTIALS", codes)
        self.assertIn("NOT_FOUND", codes)

    def test_manual_edit_failure(self):
        resp = self.client.post("/api/schedule/classes/99999/move",
                                json={"day": "Mon", "start_period": 0,
                                      "length": 1, "room_id": 1})
        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertEqual(body["code"], "MANUAL_EDIT_INVALID")
        self.assertFalse(body["ok"])

    def test_validate_only_does_not_mutate(self):
        before = self.m.ScheduledClass.query.count()
        resp = self.client.post("/api/schedule/classes/99999/validate-move",
                                json={"day": "Mon", "start_period": 0,
                                      "length": 1, "room_id": 1})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "MANUAL_EDIT_INVALID")
        self.assertEqual(self.m.ScheduledClass.query.count(), before)

    def test_reassign_unknown_faculty(self):
        resp = self.client.post("/api/assignments/1/reassign",
                                json={"faculty_id": 9999})
        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertEqual(body["code"], "UNKNOWN_FACULTY")
        self.assertIn("failures", body)

    def test_swap_invalid(self):
        resp = self.client.post("/api/assignments/swap",
                                json={"assignment_a_id": 1,
                                      "assignment_b_id": 1})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "INVALID_SWAP")

    def test_specialization_failure(self):
        resp = self.client.post("/api/specializations", json={})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("error", body)

    def test_locked_block_failure(self):
        resp = self.client.post("/api/locked-blocks", json={})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("field_errors", body)

    def test_preference_failure(self):
        resp = self.client.post("/api/faculty/1/preferences",
                                json={"kind": "NOPE", "weight": 1})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "PREF_INVALID_KIND")
        self.assertIn("field_errors", body)
        self.assertIn("failures", body)

    def test_scheduler_failure_has_code(self):
        self.m.TeachingAssignment.query.delete()
        self.m.db.session.commit()
        resp = self.client.post("/api/schedule/run", json={})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "SCHEDULING_FAILED")
        self.assertIn("Scheduling failed", body["error"])
        self.assertIn("reason", body["details"])

    def test_persistence_error_sanitized(self):
        leak = ("UNIQUE constraint failed: sections.name; "
                "traceback /tmp/secret.db SELECT * FROM admin")
        with mock.patch.object(self.m.db.session, "commit",
                               side_effect=Exception(leak)):
            resp = self.client.post("/api/sections/1/preferred-room",
                                    json={"room_id": 1})
        self.assertEqual(resp.status_code, 422)
        text = resp.get_data(as_text=True)
        self.assertEqual(resp.get_json()["error"],
                         "Could not save preferred room.")
        self.assertNotIn("UNIQUE", text)
        self.assertNotIn("traceback", text)
        self.assertNotIn("secret", text)

    def test_unhandled_exception_sanitized_500(self):
        leak = "traceback RuntimeError boom /etc/passwd SELECT password"
        with mock.patch("backend.api_routes.run_scheduler",
                        side_effect=RuntimeError(leak)):
            resp = self.client.post("/api/schedule/run", json={})
        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertEqual(body["code"], "INTERNAL_ERROR")
        text = resp.get_data(as_text=True)
        for token in ("traceback", "RuntimeError", "passwd", "password",
                      "SELECT"):
            self.assertNotIn(token, text)

    def test_import_missing_file(self):
        resp = self.client.post("/api/import/rooms",
                                data={}, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("file", body["field_errors"])

    def test_import_row_errors_preserved(self):
        csv_text = ("name,room_type,capacity\n"
                    "R201,theory,50\n"
                    "R202,bogus,10\n")
        resp = self.client.post(
            "/api/import/rooms",
            data={"file": (io.BytesIO(csv_text.encode("utf-8")),
                           "rooms.csv")},
            content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["counts"]["created"], 1)
        self.assertEqual(len(body["errors"]), 1)
        self.assertIn("Row 3", body["errors"][0])


if __name__ == "__main__":
    unittest.main()
