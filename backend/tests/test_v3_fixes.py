"""Tests for the v3 fixes: bulk teaching assignments, dependency-aware
deletes + orphan repair, crash-isolated generation, room Block + number,
configuration validation and CSV decoding.

Every test uses throwaway SQLite files in a temp dir. Run from the
repository root:

    python -m pytest backend/tests/test_v3_fixes.py
"""
import io
import os
import subprocess
import tempfile
import unittest
from unittest import mock

DAYS = "Mon,Tue,Wed,Thu,Fri"
PERIODS = "|".join(f"p{i}" for i in range(6))


class V3Base(unittest.TestCase):
    """Throwaway app + small school (two years, three sections) + login."""

    isolation = False

    def setUp(self):
        from flask import Flask
        from flask_login import LoginManager
        from backend import models as m
        from backend.api_routes import init_api
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "v3.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SOLVER_ISOLATION"] = self.isolation
        self.app.config["SOLVER_TIME_LIMIT"] = 10
        self.app.secret_key = "v3-test"
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        add = m.db.session.add
        add(m.Config(session_name="V3", working_days=DAYS, periods=PERIODS,
                     break_after_periods=3, max_consecutive_teaching=3,
                     max_section_size=60, max_lab_group_size=30))
        add(m.Program(id=1, name="BBA"))
        add(m.Enrollment(id=1, program_id=1, year_label="1", total_students=120))
        add(m.Enrollment(id=2, program_id=1, year_label="2", total_students=50))
        add(m.Section(id=1, enrollment_id=1, name="BBA-1-A", student_count=60))
        add(m.Section(id=2, enrollment_id=1, name="BBA-1-B", student_count=60))
        add(m.Section(id=3, enrollment_id=2, name="BBA-2-A", student_count=50))
        add(m.LabGroup(id=11, section_id=1, name="BBA-1-A-G1", student_count=30))
        add(m.LabGroup(id=12, section_id=1, name="BBA-1-A-G2", student_count=30))
        add(m.LabGroup(id=21, section_id=2, name="BBA-1-B-G1", student_count=30))
        add(m.LabGroup(id=31, section_id=3, name="BBA-2-A-G1", student_count=25))
        add(m.Room(id=1, name="101-A", room_type="theory", capacity=80))
        add(m.Room(id=2, name="102-A", room_type="theory", capacity=80))
        add(m.Room(id=3, name="301-C", room_type="lab", capacity=40,
                   equipment_count=40))
        add(m.Faculty(id=1, name="Vaibhav", weekly_max_hours=24))
        add(m.Faculty(id=2, name="Dr. Khan", weekly_max_hours=24))
        add(m.Subject(id=1, name="Business Computations", enrollment_id=1,
                      theory_hours_per_week=4))
        add(m.Subject(id=2, name="Computer Lab", enrollment_id=1,
                      practical_hours_per_week=2, practical_block_length=2))
        add(m.Subject(id=3, name="Year 2 Economics", enrollment_id=2,
                      theory_hours_per_week=3))
        m.db.session.commit()

        lm = LoginManager()
        lm.init_app(self.app)

        @lm.user_loader
        def _load(uid):
            return m.AdminUser.query.get(int(uid))

        init_api(self.app, lm)
        admin = m.AdminUser(username="admin")
        admin.set_password("pw")
        m.db.session.add(admin)
        m.db.session.commit()
        self.client = self.app.test_client()
        resp = self.client.post("/api/login",
                                json={"username": "admin", "password": "pw"})
        self.assertEqual(resp.status_code, 200)

    def tearDown(self):
        try:
            self.m.db.session.remove()
            self.m.db.engine.dispose()
        except Exception:
            pass

    def post(self, path, payload=None):
        return self.client.post(path, json=payload or {})

    def bulk(self, **overrides):
        payload = {"faculty_id": 1, "subject_id": 1, "session_type": "theory",
                   "periods_per_week": 4, "block_length": 1,
                   "section_ids": [1, 2]}
        payload.update(overrides)
        return self.post("/api/assignments/bulk", payload)

    def count(self, model):
        return model.query.count()


# --------------------------------------------------------------- bulk assign
class TestBulkAssignments(V3Base):

    def test_assigns_one_teacher_to_many_sections_at_once(self):
        resp = self.bulk()
        self.assertEqual(resp.status_code, 201, resp.get_json())
        body = resp.get_json()
        self.assertEqual(body["created"], 2)
        self.assertEqual(sorted(a["group"] for a in body["assignments"]),
                         ["BBA-1-A", "BBA-1-B"])
        self.assertEqual(body["faculty_load"], {"before": 0, "after": 8})
        self.assertIn("BBA-1-A, BBA-1-B", body["message"])
        rows = self.m.TeachingAssignment.query.all()
        self.assertEqual({(a.faculty_id, a.subject_id, a.section_id,
                           a.periods_per_week) for a in rows},
                         {(1, 1, 1, 4), (1, 1, 2, 4)})

    def test_lab_groups_across_sections(self):
        resp = self.bulk(subject_id=2, session_type="practical",
                         periods_per_week=2, block_length=2,
                         section_ids=[], lab_group_ids=[11, 12, 21])
        self.assertEqual(resp.status_code, 201, resp.get_json())
        rows = self.m.TeachingAssignment.query.all()
        self.assertEqual(sorted(a.lab_group_id for a in rows), [11, 12, 21])
        self.assertTrue(all(a.section_id is None for a in rows))

    def test_rejects_section_from_another_year_and_creates_nothing(self):
        resp = self.bulk(section_ids=[1, 3])
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "SUBJECT_SECTION_MISMATCH")
        self.assertIn("BBA-2-A", body["error"])
        self.assertEqual(self.count(self.m.TeachingAssignment), 0)

    def test_duplicate_is_rejected_atomically_and_names_the_teacher(self):
        self.assertEqual(self.bulk(faculty_id=2, section_ids=[1]).status_code, 201)
        resp = self.bulk(section_ids=[1, 2])
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "DUPLICATE_ASSIGNMENT")
        self.assertIn("Dr. Khan", body["error"])
        # Section 2 was free but nothing was created: all-or-nothing.
        self.assertEqual(self.count(self.m.TeachingAssignment), 1)

    def test_invalid_hours_and_targets(self):
        cases = [
            ({"block_length": 5}, "block_length"),
            ({"periods_per_week": 0}, "periods_per_week"),
            ({"block_length": 0}, "block_length"),
            ({"session_type": "seminar"}, "session_type"),
            ({"section_ids": []}, "section_ids"),
            ({"section_ids": ["x"]}, "section_ids"),
            ({"periods_per_week": 8, "block_length": 7}, "block_length"),
        ]
        for overrides, field in cases:
            with self.subTest(overrides=overrides):
                resp = self.bulk(**overrides)
                self.assertEqual(resp.status_code, 422, resp.get_json())
                self.assertIn(field, resp.get_json().get("field_errors", {}))
        self.assertEqual(self.count(self.m.TeachingAssignment), 0)

    def test_missing_teacher_subject_or_section(self):
        self.assertEqual(self.bulk(faculty_id=99).status_code, 404)
        self.assertEqual(self.bulk(subject_id=99).status_code, 404)
        self.assertEqual(self.bulk(section_ids=[1, 99]).status_code, 404)
        self.assertEqual(self.count(self.m.TeachingAssignment), 0)

    def test_over_limit_is_a_warning_not_an_error(self):
        resp = self.bulk(periods_per_week=6, block_length=1, section_ids=[1, 2])
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["category"], "success")  # 12 hrs
        resp = self.bulk(subject_id=2, session_type="practical",
                         periods_per_week=8, block_length=2,
                         section_ids=[], lab_group_ids=[11, 12])
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertEqual(body["faculty_load"], {"before": 12, "after": 28})
        self.assertEqual(body["category"], "warning")
        self.assertIn("exceeds their configured max of 24", body["message"])

    def test_single_create_rejects_subject_from_another_year(self):
        resp = self.post("/api/assignments", {
            "faculty_id": 1, "subject_id": 1, "session_type": "theory",
            "section_id": 3, "periods_per_week": 3, "block_length": 1})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "SUBJECT_SECTION_MISMATCH")
        self.assertEqual(self.count(self.m.TeachingAssignment), 0)

    def test_assignment_options_expose_grouping_fields(self):
        body = self.client.get("/api/assignments").get_json()
        self.assertEqual({s["id"]: s["enrollment_id"] for s in body["sections"]},
                         {1: 1, 2: 1, 3: 2})
        self.assertEqual({g["id"]: g["section_id"] for g in body["lab_groups"]},
                         {11: 1, 12: 1, 21: 2, 31: 3})
        self.assertEqual({s["id"]: s["enrollment_id"] for s in body["subjects"]},
                         {1: 1, 2: 1, 3: 2})


# ------------------------------------------------------------------ deletes
class TestCascadingDeletes(V3Base):

    def _seed_schedule(self):
        self.assertEqual(self.bulk().status_code, 201)
        self.assertEqual(self.bulk(faculty_id=2, subject_id=2,
                                   session_type="practical",
                                   periods_per_week=2, block_length=2,
                                   section_ids=[], lab_group_ids=[11, 12]).status_code, 201)
        resp = self.post("/api/schedule/run")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertGreater(self.count(self.m.ScheduledClass), 0)

    def assertNoOrphans(self):
        from backend.deletion import purge_orphans
        report = purge_orphans()
        self.m.db.session.rollback()
        self.assertEqual(report.counts, {}, "orphaned rows were left behind")

    def test_deleting_a_teacher_removes_their_assignments_and_classes(self):
        self._seed_schedule()
        resp = self.post("/api/faculty/1/delete")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["removed"]["assignments"], 2)
        self.assertIn("2 teaching assignments", body["message"])
        self.assertIn("Regenerate", body["message"])
        self.assertEqual(self.m.TeachingAssignment.query.filter_by(
            faculty_id=1).count(), 0)
        self.assertEqual(self.m.ScheduledClass.query.join(
            self.m.TeachingAssignment).filter(
                self.m.TeachingAssignment.faculty_id == 1).count(), 0)
        self.assertNoOrphans()
        # The remaining data still generates.
        self.assertEqual(self.post("/api/schedule/run").status_code, 200)

    def test_deleting_a_subject(self):
        self._seed_schedule()
        resp = self.post("/api/subjects/1/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.m.TeachingAssignment.query.filter_by(
            subject_id=1).count(), 0)
        self.assertNoOrphans()

    def test_deleting_an_enrollment_removes_everything_under_it(self):
        self._seed_schedule()
        resp = self.post("/api/enrollments/1/delete")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        m = self.m
        self.assertEqual(m.Section.query.filter_by(enrollment_id=1).count(), 0)
        self.assertEqual(m.LabGroup.query.filter(
            m.LabGroup.id.in_([11, 12, 21])).count(), 0)
        self.assertEqual(m.Subject.query.filter_by(enrollment_id=1).count(), 0)
        self.assertEqual(m.TeachingAssignment.query.count(), 0)
        self.assertEqual(m.ScheduledClass.query.count(), 0)
        # Year 2 is untouched.
        self.assertEqual(m.Section.query.get(3).name, "BBA-2-A")
        self.assertNoOrphans()

    def test_deleting_a_program_cascades_through_its_years(self):
        self._seed_schedule()
        self.assertEqual(self.post("/api/programs/1/delete").status_code, 200)
        m = self.m
        for model in (m.Program, m.Enrollment, m.Section, m.LabGroup,
                      m.Subject, m.TeachingAssignment, m.ScheduledClass):
            self.assertEqual(model.query.count(), 0, model.__name__)
        self.assertNoOrphans()

    def test_deleting_an_assignment_removes_its_classes(self):
        self._seed_schedule()
        aid = self.m.TeachingAssignment.query.first().id
        before = self.m.ScheduledClass.query.filter_by(assignment_id=aid).count()
        self.assertGreater(before, 0)
        resp = self.post(f"/api/assignments/{aid}/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.m.ScheduledClass.query.filter_by(
            assignment_id=aid).count(), 0)
        self.assertNoOrphans()

    def test_deleting_a_room_frees_its_classes_and_home_room(self):
        self._seed_schedule()
        sec = self.m.Section.query.get(1)
        sec.preferred_theory_room_id = 1
        self.m.db.session.commit()
        resp = self.post("/api/rooms/1/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.m.ScheduledClass.query.filter_by(room_id=1).count(), 0)
        self.assertIsNone(self.m.Section.query.get(1).preferred_theory_room_id)
        self.assertNoOrphans()

    def test_room_used_by_a_fixed_block_cannot_be_deleted(self):
        self.assertEqual(self.bulk(section_ids=[1]).status_code, 201)
        aid = self.m.TeachingAssignment.query.first().id
        resp = self.post("/api/locked-blocks", {
            "assignment_id": aid, "day": "Mon", "start_period": 0,
            "length": 1, "room_id": 1})
        self.assertEqual(resp.status_code, 201, resp.get_json())
        resp = self.post("/api/rooms/1/delete")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "DELETE_BLOCKED")
        self.assertIsNotNone(self.m.Room.query.get(1))

    def test_purge_orphans_repairs_rows_left_by_old_versions(self):
        from backend.deletion import purge_orphans
        self._seed_schedule()
        m = self.m
        # Simulate the old bare deletes (no cascade).
        m.db.session.execute(m.db.text("DELETE FROM faculty WHERE id = 1"))
        m.db.session.execute(m.db.text("DELETE FROM enrollment WHERE id = 2"))
        m.db.session.commit()
        report = purge_orphans()
        m.db.session.commit()
        self.assertGreaterEqual(report.counts.get("assignments", 0), 2)
        self.assertEqual(report.counts.get("sections"), 1)
        self.assertEqual(m.TeachingAssignment.query.filter_by(
            faculty_id=1).count(), 0)
        self.assertNoOrphans()
        # A clean store reports nothing.
        self.assertEqual(purge_orphans().counts, {})
        m.db.session.rollback()


# --------------------------------------------------------------- generation
class TestGenerationGuards(V3Base):

    def test_concurrent_generation_is_refused(self):
        from backend import solver_runner
        self.assertEqual(self.bulk().status_code, 201)
        solver_runner.acquire_generation_slot()
        try:
            resp = self.post("/api/schedule/run")
        finally:
            solver_runner.release_generation_slot()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "GENERATION_IN_PROGRESS")
        # The slot is released afterwards.
        self.assertEqual(self.post("/api/schedule/run").status_code, 200)

    def test_impossible_hours_are_reported_not_crashed(self):
        self.assertEqual(self.bulk(section_ids=[1]).status_code, 201)
        a = self.m.TeachingAssignment.query.first()
        a.block_length = 9  # corrupt row (e.g. from an old import)
        self.m.db.session.commit()
        resp = self.post("/api/schedule/run")
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "SCHEDULING_FAILED")
        self.assertIn("not valid", resp.get_json()["error"])


class TestIsolatedSolver(V3Base):
    """Generation through the real child process (the production path)."""

    isolation = True

    def test_generates_in_a_child_process(self):
        self.assertEqual(self.bulk().status_code, 201)
        self.assertEqual(self.bulk(faculty_id=2, subject_id=2,
                                   session_type="practical",
                                   periods_per_week=2, block_length=2,
                                   section_ids=[],
                                   lab_group_ids=[11, 12, 21]).status_code, 201)
        resp = self.post("/api/schedule/run")
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200, body)
        self.assertIn(body["status"], ("OPTIMAL", "FEASIBLE"))
        # 2 sections x 4 one-hour classes + 3 lab groups x one 2-hour block
        self.assertEqual(body["placements"], 11)
        self.assertEqual(self.count(self.m.ScheduledClass), 11)

    def test_a_native_solver_crash_keeps_the_server_and_old_timetable(self):
        self.assertEqual(self.bulk().status_code, 201)
        self.assertEqual(self.post("/api/schedule/run").status_code, 200)
        before = sorted((c.assignment_id, c.day, c.start_period, c.room_id)
                        for c in self.m.ScheduledClass.query.all())
        crashed = subprocess.CompletedProcess(
            args=[], returncode=3221225477, stdout=b"", stderr=b"")
        with mock.patch("backend.solver_runner.subprocess.run",
                        return_value=crashed):
            resp = self.post("/api/schedule/run")
        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertEqual(body["code"], "SOLVER_CRASHED")
        self.assertIn("0xC0000005", body["error"])
        self.assertIn("untouched", body["error"])
        after = sorted((c.assignment_id, c.day, c.start_period, c.room_id)
                       for c in self.m.ScheduledClass.query.all())
        self.assertEqual(before, after)
        # The server keeps working and the lock was released.
        self.assertEqual(self.client.get("/api/dashboard").status_code, 200)
        self.assertEqual(self.post("/api/schedule/run").status_code, 200)

    def test_a_hung_solver_is_stopped(self):
        self.assertEqual(self.bulk().status_code, 201)
        with mock.patch("backend.solver_runner.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("x", 1)):
            resp = self.post("/api/schedule/run")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json()["code"], "SOLVER_CRASHED")

    def test_infeasible_result_still_maps_to_422(self):
        # 31 hrs/week for one section can't fit in 5 days x 6 periods.
        self.assertEqual(self.bulk(periods_per_week=31, block_length=1,
                                   section_ids=[1]).status_code, 201)
        resp = self.post("/api/schedule/run")
        self.assertEqual(resp.status_code, 422, resp.get_json())


class TestSolverPayload(unittest.TestCase):

    def test_payload_round_trip_preserves_inputs(self):
        import json
        from types import SimpleNamespace
        from backend import solver_runner as sr

        lab = SimpleNamespace(id=7, section_id=3)

        class A(SimpleNamespace):
            def group_key(self):
                return "labgroup:7"

            def group_label(self):
                return "X-G1"

            def group_size(self):
                return 25

        a = A(id=5, faculty_id=2, subject_id=9, session_type="practical",
              section_id=None, lab_group_id=7, periods_per_week=2,
              block_length=2, specialization_id=None, lab_group=lab)
        room = SimpleNamespace(id=1, name="301-C", room_type="lab",
                               capacity=40, equipment_count=30)
        payload = sr.build_payload(
            assignments=[a], rooms=[room], faculty_unavailable={2: {"Mon:0"}},
            days=["Mon"], num_periods=4, break_after=2, max_consecutive=3,
            time_limit_seconds=5, locked_placements=[],
            specialization_data={4: {"section_ids": [3], "total_students": 9}},
            preferred_theory_rooms={3: 1}, faculty_preferences=[
                {"faculty_id": 2, "kind": "TIME_WINDOW", "days": "Mon",
                 "start_period": 0, "end_period": 2, "enabled": True}])
        kwargs = sr.payload_to_kwargs(json.loads(json.dumps(payload)))
        snap = kwargs["assignments"][0]
        self.assertEqual((snap.id, snap.lab_group.section_id, snap.group_key(),
                          snap.group_label(), snap.group_size()),
                         (5, 3, "labgroup:7", "X-G1", 25))
        self.assertEqual(kwargs["faculty_unavailable"], {2: {"Mon:0"}})
        self.assertEqual(list(kwargs["specialization_data"]), [4])
        self.assertEqual(kwargs["preferred_theory_rooms"], {3: 1})
        self.assertEqual(kwargs["rooms"][0].equipment_count, 30)


# -------------------------------------------------------------------- rooms
class TestRoomsBlockAndNumber(V3Base):

    def test_block_and_number_compose_the_canonical_name(self):
        resp = self.post("/api/rooms", {"block": "d", "number": "204",
                                        "room_type": "theory", "capacity": 60})
        self.assertEqual(resp.status_code, 201, resp.get_json())
        room = resp.get_json()["room"]
        self.assertEqual((room["name"], room["block"], room["number"]),
                         ("204-D", "D", "204"))
        resp = self.post("/api/rooms", {"block": "", "number": "7",
                                        "room_type": "lab", "capacity": 30})
        self.assertEqual(resp.get_json()["room"]["block"], None)
        self.assertEqual(resp.get_json()["room"]["name"], "7")

    def test_number_must_be_digits(self):
        for number in ("10a", "A101", "12 3", "", "12345", "-5"):
            with self.subTest(number=number):
                resp = self.post("/api/rooms", {"block": "A", "number": number,
                                                "room_type": "theory",
                                                "capacity": 60})
                self.assertEqual(resp.status_code, 422)
                self.assertIn("number", resp.get_json()["field_errors"])

    def test_block_must_be_a_single_letter(self):
        for block in ("AB", "1", "é"):
            with self.subTest(block=block):
                resp = self.post("/api/rooms", {"block": block, "number": "101",
                                                "room_type": "theory",
                                                "capacity": 60})
                self.assertEqual(resp.status_code, 422)
                self.assertIn("block", resp.get_json()["field_errors"])

    def test_duplicates_type_and_capacity(self):
        resp = self.post("/api/rooms", {"block": "A", "number": "101",
                                        "room_type": "theory", "capacity": 60})
        self.assertEqual(resp.status_code, 422)
        self.assertIn("Block A, room 101 already exists", resp.get_json()["error"])
        resp = self.post("/api/rooms", {"block": "A", "number": "150",
                                        "room_type": "hall", "capacity": 60})
        self.assertIn("room_type", resp.get_json()["field_errors"])
        resp = self.post("/api/rooms", {"block": "A", "number": "150",
                                        "room_type": "theory", "capacity": 0})
        self.assertIn("capacity", resp.get_json()["field_errors"])

    def test_legacy_name_field_still_works(self):
        resp = self.post("/api/rooms", {"name": "B 503", "room_type": "theory",
                                        "capacity": 60})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["room"]["name"], "503-B")


# ------------------------------------------------------------ misc validation
class TestValidation(V3Base):

    def _cfg(self, **overrides):
        payload = {"session_name": "V3", "max_section_size": 60,
                   "max_lab_group_size": 30, "working_days": DAYS,
                   "periods": PERIODS, "break_after_periods": 3,
                   "max_consecutive_teaching": 3}
        payload.update(overrides)
        return self.post("/api/config", payload)

    def test_config_rejects_values_that_break_generation(self):
        self.assertEqual(self._cfg().status_code, 200)
        for overrides, field in (
                ({"max_section_size": 0}, "max_section_size"),
                ({"max_lab_group_size": -1}, "max_lab_group_size"),
                ({"working_days": " , "}, "working_days"),
                ({"working_days": "Mon,Mon"}, "working_days"),
                ({"periods": "|"}, "periods"),
                ({"break_after_periods": 9}, "break_after_periods"),
                ({"max_consecutive_teaching": -1}, "max_consecutive_teaching")):
            with self.subTest(field=field):
                resp = self._cfg(**overrides)
                self.assertEqual(resp.status_code, 422)
                self.assertIn(field, resp.get_json()["field_errors"])
        self.assertEqual(self.m.Config.query.first().max_section_size, 60)

    def test_changing_structure_with_a_schedule_asks_to_regenerate(self):
        self.assertEqual(self.bulk(section_ids=[1]).status_code, 201)
        self.assertEqual(self.post("/api/schedule/run").status_code, 200)
        resp = self._cfg(working_days="Mon,Tue,Wed,Thu,Fri,Sat")
        self.assertIn("generate the timetable again", resp.get_json()["message"])

    def test_creates_reject_missing_parents(self):
        self.assertEqual(self.post("/api/enrollments", {
            "program_id": 99, "year_label": "3",
            "total_students": 40}).status_code, 404)
        self.assertEqual(self.post("/api/subjects", {
            "name": "Ghost", "enrollment_id": 99}).status_code, 404)
        self.assertEqual(self.m.Enrollment.query.count(), 2)
        self.assertEqual(self.m.Subject.query.count(), 3)

    def test_csv_import_accepts_windows_encoded_files(self):
        from werkzeug.datastructures import FileStorage
        data = ("name,room_type,capacity\nB 401,theory,55\n"
                "Café 9,theory,10\n").encode("cp1252")
        resp = self.client.post(
            "/api/import/rooms",
            data={"file": FileStorage(io.BytesIO(data), filename="rooms.csv")},
            content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertEqual(body["counts"]["created"], 1)
        self.assertEqual(len(body["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
