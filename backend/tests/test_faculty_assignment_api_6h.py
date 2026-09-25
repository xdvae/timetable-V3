"""Phase 6H.4 tests: faculty reassignment/swap API integration.

Thin-route tests: request parsing, auth, dry-run purity, success shapes,
structured error preservation (code/details/failures intact), 404 vs 422
mapping, and atomicity through the HTTP layer. Domain rules themselves
are covered by the 6H.2/6H.3 domain suites; no scheduler involvement.

Every test uses throwaway SQLite files in a temp dir — never the real
database. Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_faculty_assignment_api_6h -v
"""
import json
import os
import tempfile
import unittest

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))


class ApiTestBase(unittest.TestCase):
    """Throwaway app + seeded timetable + logged-in API test client."""

    def setUp(self):
        from flask import Flask
        from flask_login import LoginManager
        from backend import models as m
        from backend.api_routes import init_api
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6h4.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.secret_key = "6h4-test"
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6H4", working_days=DAYS,
                                  periods=PERIODS, break_after_periods=4,
                                  max_consecutive_teaching=3))
        m.db.session.add(m.Program(id=1, name="BCA"))
        m.db.session.add(m.Enrollment(id=1, program_id=1, year_label="Y1",
                                      total_students=60))
        m.db.session.add(m.Section(id=1, enrollment_id=1, name="BCA-1-A",
                                   student_count=30))
        m.db.session.add(m.Section(id=2, enrollment_id=1, name="BCA-1-B",
                                   student_count=30))
        m.db.session.add(m.LabGroup(id=10, section_id=1, name="BCA-1-A-G1",
                                    student_count=15))
        m.db.session.add(m.Room(id=1, name="R101", room_type="theory",
                                capacity=100))
        m.db.session.add(m.Room(id=2, name="R102", room_type="theory",
                                capacity=100))
        m.db.session.add(m.Room(id=3, name="R103", room_type="theory",
                                capacity=20))
        m.db.session.add(m.Room(id=4, name="L1", room_type="lab", capacity=40,
                                equipment_count=40))
        m.db.session.add(m.Faculty(id=1, name="F1", weekly_max_hours=24))
        m.db.session.add(m.Faculty(id=2, name="F2", weekly_max_hours=24))
        m.db.session.add(m.Faculty(id=3, name="F3", weekly_max_hours=24))
        m.db.session.add(m.Faculty(id=4, name="F4", weekly_max_hours=3))
        m.db.session.add(m.Subject(id=1, name="SUB1", enrollment_id=1))
        m.db.session.add(m.Subject(id=2, name="SUB2", enrollment_id=1))
        m.db.session.add(m.TeachingAssignment(
            id=1, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=5, block_length=1))
        m.db.session.add(m.TeachingAssignment(
            id=2, faculty_id=2, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=5, block_length=1))
        m.db.session.add(m.TeachingAssignment(
            id=3, faculty_id=1, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=3, block_length=1))
        m.db.session.add(m.TeachingAssignment(
            id=4, faculty_id=2, subject_id=1, session_type="practical",
            lab_group_id=10, periods_per_week=2, block_length=2))
        m.db.session.add(m.TeachingAssignment(
            id=5, faculty_id=3, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=3, block_length=1))
        m.db.session.add(m.TeachingAssignment(
            id=6, faculty_id=4, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=2, block_length=1))
        m.db.session.commit()
        self._place(1, 1, "Mon", 0, 1, 1)
        self._place(2, 1, "Mon", 1, 1, 1)
        self._place(3, 2, "Mon", 4, 1, 2)
        self._place(4, 3, "Tue", 0, 1, 1)
        self._place(5, 4, "Tue", 0, 2, 4)
        self._place(6, 5, "Wed", 0, 1, 2)
        self._place(7, 2, "Wed", 1, 1, 1)
        self._place(8, 6, "Wed", 2, 1, 2)

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
        # Independent client without a session: exercises the 401 path.
        self.anon = self.app.test_client()

    def tearDown(self):
        try:
            self.m.db.session.remove()
            self.m.db.engine.dispose()
        except Exception:
            pass

    def _anon_post(self, path, payload):
        """Unauthenticated request with a pristine app context.

        The harness holds one outer app context for DB access, and
        Flask's `g` (where Flask-Login caches the request user) would
        otherwise leak the setUp login into the anonymous request. Pop
        the outer context for the request so it gets a fresh one,
        exactly like production; always restore it afterwards.
        """
        self.ctx.pop()
        try:
            return self.anon.post(path, json=payload)
        finally:
            self.ctx.push()

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

    def _faculty_of(self, aid):
        return self.m.TeachingAssignment.query.get(aid).faculty_id

    def _assignment_map(self):
        return {a.id: a.faculty_id
                for a in self.m.TeachingAssignment.query.all()}

    def _state(self):
        return (self._assignment_map(), self._rows(),
                sorted((lb.id, lb.assignment_id, lb.faculty_id)
                       for lb in self.m.LockedBlock.query.all()),
                sorted((s.id, s.specialization_id, s.day, s.start_period,
                        s.length)
                       for s in self.m.SpecializationSlot.query.all()))

    def _lock_assignment_1(self):
        lb = self.m.LockedBlock(
            kind="interdepartment", assignment_id=1, subject_id=1,
            faculty_id=1, section_id=1, day="Mon", start_period=0,
            length=1, room_id=1, room_locked=True)
        self.m.db.session.add(lb)
        self.m.db.session.flush()
        sc = self.m.ScheduledClass.query.get(1)
        sc.is_locked = True
        sc.locked_block_id = lb.id
        self.m.db.session.commit()
        return lb

    def _mk_spec_cohort(self, day="Tue", start=2, room_ids=(2, 1)):
        from backend import specializations as spec_svc
        cyber = spec_svc.create_specialization(
            self.m.db, name="Cyber", enrollment_id=1,
            session_type="theory", block_length=1, periods_per_week=1)
        ai = spec_svc.create_specialization(
            self.m.db, name="AI", enrollment_id=1,
            session_type="theory", block_length=1, periods_per_week=1)
        for spec in (cyber, ai):
            spec_svc.add_or_update_membership(self.m.db, spec.id, 1, 10)
        ca = self.m.TeachingAssignment(
            faculty_id=3, subject_id=2, session_type="theory",
            section_id=None, lab_group_id=None,
            specialization_id=cyber.id, periods_per_week=1, block_length=1)
        aa = self.m.TeachingAssignment(
            faculty_id=2, subject_id=2, session_type="theory",
            section_id=None, lab_group_id=None,
            specialization_id=ai.id, periods_per_week=1, block_length=1)
        self.m.db.session.add(ca)
        self.m.db.session.add(aa)
        self.m.db.session.commit()
        out = {}
        for spec, assign, room in ((cyber, ca, room_ids[0]),
                                  (ai, aa, room_ids[1])):
            slot = self.m.SpecializationSlot(
                specialization_id=spec.id, day=day,
                start_period=start, length=1)
            self.m.db.session.add(slot)
            self.m.db.session.flush()
            sc = self.m.ScheduledClass(
                assignment_id=assign.id, day=day, start_period=start,
                length=1, room_id=room, run_id="run1", slot_id=slot.id)
            self.m.db.session.add(sc)
            self.m.db.session.flush()
            out[spec.name] = (spec, assign, sc, slot)
        self.m.db.session.commit()
        return out


# ------------------------------------------------------- reassign API
class TestReassignApi(ApiTestBase):
    def test_validate_requires_auth(self):
        resp = self._anon_post("/api/assignments/1/validate-reassign",
                               {"faculty_id": 2})
        self.assertEqual(resp.status_code, 401)
        self.assertIn("error", resp.get_json())

    def test_reassign_requires_auth(self):
        resp = self._anon_post("/api/assignments/1/reassign",
                               {"faculty_id": 2})
        self.assertEqual(resp.status_code, 401)

    def test_missing_faculty_id(self):
        resp = self.client.post("/api/assignments/1/validate-reassign",
                                json={})
        self.assertEqual(resp.status_code, 422)
        self.assertIn("faculty_id", resp.get_json().get("field_errors", {}))

    def test_malformed_faculty_id(self):
        resp = self.client.post("/api/assignments/1/reassign",
                                json={"faculty_id": "abc"})
        self.assertEqual(resp.status_code, 422)
        self.assertIn("faculty_id", resp.get_json().get("field_errors", {}))

    def test_missing_assignment_validate(self):
        resp = self.client.post("/api/assignments/999/validate-reassign",
                                json={"faculty_id": 2})
        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertEqual(body["code"], "UNKNOWN_ASSIGNMENT")

    def test_missing_assignment_reassign(self):
        before = self._state()
        resp = self.client.post("/api/assignments/999/reassign",
                                json={"faculty_id": 2})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self._state(), before)

    def test_missing_faculty(self):
        resp = self.client.post("/api/assignments/1/reassign",
                                json={"faculty_id": 999})
        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertEqual(body["code"], "UNKNOWN_FACULTY")
        self.assertEqual(self._faculty_of(1), 1)

    def test_validate_ok_dry_run(self):
        before = self._state()
        resp = self.client.post("/api/assignments/5/validate-reassign",
                                json={"faculty_id": 1})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["noop"])
        self.assertTrue(body["dry_run"])
        self.assertEqual((body["assignment_id"], body["current_faculty_id"],
                          body["new_faculty_id"]), (5, 3, 1))
        self.assertEqual(body["scheduled_class_ids"], [6])
        self.assertIsNone(body["warning"])
        self.assertEqual(self._state(), before)

    def test_reassign_ok(self):
        before_rows = self._rows()
        resp = self.client.post("/api/assignments/5/reassign",
                                json={"faculty_id": 1})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        json.dumps(body)  # JSON serializable.
        self.assertTrue(body["ok"])
        self.assertFalse(body["noop"])
        item = body["assignment"]
        self.assertEqual((item["id"], item["faculty_id"],
                          item["faculty_name"]), (5, 1, "F1"))
        self.assertEqual(item["subject_name"], "SUB1")
        self.assertEqual(body["result"]["previous_faculty_id"], 3)
        self.assertEqual(self._faculty_of(5), 1)
        self.assertEqual(self._rows(), before_rows)

    def test_reassign_noop(self):
        before = self._state()
        resp = self.client.post("/api/assignments/1/reassign",
                                json={"faculty_id": 1})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["noop"])
        self.assertEqual(body["assignment"]["faculty_id"], 1)
        self.assertEqual(self._state(), before)

    def test_reassign_unavailable(self):
        f2 = self.m.Faculty.query.get(2)
        f2.unavailable_slots = "Mon:0"
        self.m.db.session.commit()
        before = self._state()
        resp = self.client.post("/api/assignments/1/reassign",
                                json={"faculty_id": 2})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "FACULTY_UNAVAILABLE")
        self.assertIn("details", body)
        self.assertTrue(body["failures"])
        self.assertEqual(self._state(), before)

    def test_reassign_conflict(self):
        self.m.db.session.add(self.m.TeachingAssignment(
            id=7, faculty_id=2, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        self._place(9, 7, "Mon", 0, 1, 2)
        before = self._state()
        resp = self.client.post("/api/assignments/1/reassign",
                                json={"faculty_id": 2})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "FACULTY_CONFLICT")
        self.assertEqual(body["details"]["conflicting_assignment_id"], 7)
        self.assertIn("conflicting_class_id", body["details"])
        self.assertTrue(body["failures"])
        self.assertEqual(self._state(), before)

    def test_reassign_consecutive(self):
        self.m.db.session.add(self.m.TeachingAssignment(
            id=12, faculty_id=3, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=2, block_length=1))
        self.m.db.session.commit()
        self._place(10, 12, "Mon", 2, 1, 2)
        self._place(11, 12, "Mon", 3, 1, 2)
        resp = self.client.post("/api/assignments/1/reassign",
                                json={"faculty_id": 3})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "FACULTY_CONSECUTIVE")
        self.assertEqual(self._faculty_of(1), 1)

    def test_reassign_locked(self):
        self._lock_assignment_1()
        before = self._state()
        resp = self.client.post("/api/assignments/1/reassign",
                                json={"faculty_id": 2})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "LOCKED_BLOCK")
        self.assertEqual(self._state(), before)

    def test_reassign_spec_failure_code_preserved(self):
        specs = self._mk_spec_cohort()
        cyber_id = specs["Cyber"][1].id
        # F2 busy Tue P2 in another room: the spec slot's own room stays
        # free, so the primary failure is the faculty conflict.
        self.m.db.session.add(self.m.TeachingAssignment(
            id=16, faculty_id=2, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        self._place(20, 16, "Tue", 2, 1, 3)
        before = self._state()
        resp = self.client.post(f"/api/assignments/{cyber_id}/reassign",
                                json={"faculty_id": 2})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "FACULTY_CONFLICT")
        self.assertTrue(body["failures"])
        self.assertEqual(self._state(), before)

    def test_reassign_load_warning_succeeds(self):
        # F4 (max 3, load 2) gains A5 (3): 2-... warning, still 200.
        resp = self.client.post("/api/assignments/5/reassign",
                                json={"faculty_id": 4})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body["ok"])
        warn = body["result"]["warning"]
        self.assertIsNotNone(warn)
        self.assertTrue(warn["exceeded"])
        self.assertEqual(warn["resulting_load"], 5)
        self.assertEqual(self._faculty_of(5), 4)


# ------------------------------------------------------- swap API
class TestSwapApi(ApiTestBase):
    def test_validate_swap_requires_auth(self):
        resp = self._anon_post("/api/assignments/validate-swap",
                               {"assignment_a_id": 1,
                                "assignment_b_id": 5})
        self.assertEqual(resp.status_code, 401)

    def test_swap_requires_auth(self):
        resp = self._anon_post("/api/assignments/swap",
                               {"assignment_a_id": 1,
                                "assignment_b_id": 5})
        self.assertEqual(resp.status_code, 401)

    def test_missing_a(self):
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_b_id": 5})
        self.assertEqual(resp.status_code, 422)
        self.assertIn("assignment_a_id",
                      resp.get_json().get("field_errors", {}))

    def test_missing_b(self):
        resp = self.client.post("/api/assignments/validate-swap", json={
            "assignment_a_id": 1})
        self.assertEqual(resp.status_code, 422)
        self.assertIn("assignment_b_id",
                      resp.get_json().get("field_errors", {}))

    def test_malformed_a(self):
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": "x", "assignment_b_id": 5})
        self.assertEqual(resp.status_code, 422)

    def test_malformed_b(self):
        resp = self.client.post("/api/assignments/validate-swap", json={
            "assignment_a_id": 1, "assignment_b_id": "y"})
        self.assertEqual(resp.status_code, 422)

    def test_missing_assignment(self):
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": 1, "assignment_b_id": 999})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "UNKNOWN_ASSIGNMENT")

    def test_validate_swap_ok_dry_run(self):
        before = self._state()
        resp = self.client.post("/api/assignments/validate-swap", json={
            "assignment_a_id": 1, "assignment_b_id": 5})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["noop"])
        self.assertTrue(body["dry_run"])
        self.assertEqual((body["assignment_a_id"], body["assignment_b_id"],
                          body["faculty_a_id"], body["faculty_b_id"]),
                         (1, 5, 1, 3))
        self.assertEqual(body["scheduled_class_ids_a"], [1, 2])
        self.assertEqual(body["scheduled_class_ids_b"], [6])
        self.assertEqual(body["warnings"], [])
        self.assertEqual(self._state(), before)

    def test_swap_ok(self):
        before_rows = self._rows()
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": 1, "assignment_b_id": 5})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        json.dumps(body)  # JSON serializable.
        self.assertTrue(body["ok"])
        self.assertFalse(body["noop"])
        by_id = {a["id"]: a["faculty_id"] for a in body["assignments"]}
        self.assertEqual(by_id, {1: 3, 5: 1})
        self.assertEqual((self._faculty_of(1), self._faculty_of(5)), (3, 1))
        self.assertEqual(self._rows(), before_rows)

    def test_swap_noop_same_faculty(self):
        before = self._state()
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": 1, "assignment_b_id": 3})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["noop"])
        self.assertEqual(self._state(), before)

    def test_swap_same_assignment_rejected(self):
        before = self._state()
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": 1, "assignment_b_id": 1})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "INVALID_SWAP")
        self.assertEqual(self._state(), before)

    def test_swap_a_unavailable(self):
        f2 = self.m.Faculty.query.get(2)
        f2.unavailable_slots = "Mon:0"
        self.m.db.session.commit()
        before = self._state()
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": 1, "assignment_b_id": 2})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "FACULTY_UNAVAILABLE")
        sides = {f["details"].get("swap_side") for f in body["failures"]}
        self.assertIn("A", sides)
        self.assertEqual(self._state(), before)

    def test_swap_b_unavailable(self):
        f1 = self.m.Faculty.query.get(1)
        f1.unavailable_slots = "Wed:0"
        self.m.db.session.commit()
        before = self._state()
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": 1, "assignment_b_id": 5})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "FACULTY_UNAVAILABLE")
        sides = {f["details"].get("swap_side") for f in body["failures"]}
        self.assertIn("B", sides)
        self.assertEqual(self._state(), before)

    def test_swap_conflict(self):
        self.m.db.session.add(self.m.TeachingAssignment(
            id=7, faculty_id=2, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        self._place(9, 7, "Mon", 0, 1, 2)
        before = self._state()
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": 1, "assignment_b_id": 2})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "FACULTY_CONFLICT")
        self.assertIn("conflicting_class_id", body["details"])
        self.assertEqual(body["details"]["conflicting_assignment_id"], 7)
        self.assertTrue(body["failures"])
        self.assertEqual(self._state(), before)

    def test_swap_h12(self):
        self.m.db.session.add(self.m.TeachingAssignment(
            id=12, faculty_id=3, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=2, block_length=1))
        self.m.db.session.commit()
        self._place(10, 12, "Mon", 2, 1, 2)
        self._place(11, 12, "Mon", 3, 1, 2)
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": 1, "assignment_b_id": 5})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "FACULTY_CONSECUTIVE")
        self.assertEqual((self._faculty_of(1), self._faculty_of(5)), (1, 3))

    def test_swap_locked_a(self):
        self._lock_assignment_1()
        before = self._state()
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": 1, "assignment_b_id": 5})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "LOCKED_BLOCK")
        self.assertEqual(self._state(), before)

    def test_swap_locked_b(self):
        self._lock_assignment_1()
        before = self._state()
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": 5, "assignment_b_id": 1})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "LOCKED_BLOCK")
        self.assertEqual(body["details"].get("swap_side"), "B")
        self.assertEqual(self._state(), before)

    def test_swap_normal_spec_rejected(self):
        specs = self._mk_spec_cohort()
        cyber_id = specs["Cyber"][1].id
        before = self._state()
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": 1, "assignment_b_id": cyber_id})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "SPECIALIZATION_SWAP")
        self.assertEqual(self._state(), before)

    def test_swap_spec_failure_structured(self):
        specs = self._mk_spec_cohort()
        cyber_id = specs["Cyber"][1].id
        ai_id = specs["AI"][1].id
        # F2 busy Tue P2 in another room: the spec slot's own room stays
        # free, so the primary failure is the faculty conflict.
        self.m.db.session.add(self.m.TeachingAssignment(
            id=16, faculty_id=2, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        self._place(20, 16, "Tue", 2, 1, 3)
        before = self._state()
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": cyber_id, "assignment_b_id": ai_id})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "FACULTY_CONFLICT")
        self.assertTrue(body["failures"])
        self.assertEqual(self._state(), before)

    def test_swap_valid_spec_pair(self):
        specs = self._mk_spec_cohort()
        cyber_id = specs["Cyber"][1].id
        ai_id = specs["AI"][1].id
        slots_before = self._state()[3]
        resp = self.client.post("/api/assignments/swap", json={
            "assignment_a_id": cyber_id, "assignment_b_id": ai_id})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        by_id = {a["id"]: a["faculty_id"] for a in body["assignments"]}
        self.assertEqual(by_id, {cyber_id: 2, ai_id: 3})
        self.assertEqual(self._state()[3], slots_before)


if __name__ == "__main__":
    unittest.main()
