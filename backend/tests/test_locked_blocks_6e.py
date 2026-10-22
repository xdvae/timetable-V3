"""Phase 6E tests: locked interdepartment blocks.

Covers model/persistence + atomicity, pre-lock validation (all shared-rule
codes), scheduler immovability + avoidance + HN1 + infeasibility, audit
detection + read-only, the 6E migration, and the backend API foundation.

Every test uses throwaway SQLite files in a temp dir — never the real
`timetable_v2.db`. Run from the repository root:

    venv\\Scripts\\python.exe -m unittest discover -s backend\\tests -t .
"""
import hashlib
import os
import sqlite3
import tempfile
import unittest

DAYS = "Mon,Tue,Wed,Thu,Fri"
PERIODS = "|".join(f"p{i}" for i in range(7))


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class LockedTestBase(unittest.TestCase):
    """Throwaway Flask app + seeded school (ORM create_all has 6C+6E cols)."""

    def setUp(self):
        from flask import Flask
        from backend import models as m
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6e.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6E", working_days=DAYS,
                                  periods=PERIODS, break_after_periods=4,
                                  max_consecutive_teaching=3))
        m.db.session.add(m.Program(id=1, name="BCA"))
        m.db.session.add(m.Enrollment(id=1, program_id=1, year_label="Y1",
                                      total_students=60))
        m.db.session.add(m.Section(id=1, enrollment_id=1, name="BCA-1-A",
                                   student_count=30))
        m.db.session.add(m.Section(id=2, enrollment_id=1, name="BCA-1-B",
                                   student_count=30))
        m.db.session.add(m.Room(id=1, name="101", room_type="theory",
                                capacity=100))
        m.db.session.add(m.Room(id=2, name="102", room_type="theory",
                                capacity=100))
        m.db.session.add(m.Room(id=3, name="201", room_type="lab", capacity=40,
                                equipment_count=40))
        m.db.session.add(m.Room(id=4, name="202", room_type="lab", capacity=5,
                                equipment_count=2))
        m.db.session.add(m.Faculty(id=1, name="F1"))
        m.db.session.add(m.Faculty(id=2, name="F2"))
        m.db.session.add(m.Subject(id=1, name="DSA", enrollment_id=1))
        m.db.session.add(m.LabGroup(id=10, section_id=1, name="BCA-1-A-G1",
                                    student_count=15))
        # A1: F1 theory S1, 3 periods/week (room for 1 locked + 2 free).
        m.db.session.add(m.TeachingAssignment(
            id=1, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=3, block_length=1))
        # A2: F2 theory S1, 1 period/week (same section, other faculty).
        m.db.session.add(m.TeachingAssignment(
            id=2, faculty_id=2, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=1, block_length=1))
        # A3: F2 lab G1, 2 periods/week in one block.
        m.db.session.add(m.TeachingAssignment(
            id=3, faculty_id=2, subject_id=1, session_type="practical",
            lab_group_id=10, periods_per_week=2, block_length=2))
        m.db.session.commit()

    def tearDown(self):
        try:
            self.m.db.session.remove()
            self.m.db.engine.dispose()
        except Exception:
            pass

    # -- helpers ------------------------------------------------------
    def _svc(self):
        from backend import locked_blocks as lb
        return lb

    def _lock(self, **kw):
        lb = self._svc()
        args = dict(assignment_id=1, day="Mon", start_period=0, length=1,
                    room_id=1)
        args.update(kw)
        return lb.create_locked_block(self.m.db, **args)

    def _sched_inputs(self):
        m = self.m
        cfg = m.Config.query.first()
        return (m.TeachingAssignment.query.all(), m.Room.query.all(),
                {f.id: f.unavailable_set() for f in m.Faculty.query.all()},
                cfg.day_list(), len(cfg.period_list()),
                cfg.break_after_periods or None,
                cfg.max_consecutive_teaching)


# ------------------------------------------------------- model / persist
class TestModelPersistence(LockedTestBase):
    def test_1_create_interdepartment_block(self):
        lb, _ = self._lock()
        self.assertEqual(lb.kind, "interdepartment")
        self.assertEqual(self.m.LockedBlock.query.count(), 1)

    def test_2_scheduled_class_created(self):
        _, sc = self._lock()
        self.assertIsNotNone(sc.id)
        self.assertEqual(sc.day, "Mon")
        self.assertEqual(sc.start_period, 0)
        self.assertEqual(sc.length, 1)
        self.assertEqual(sc.room_id, 1)

    def test_3_is_locked_true(self):
        _, sc = self._lock()
        self.assertTrue(sc.is_locked)

    def test_4_locked_block_id_points(self):
        lb, sc = self._lock()
        self.assertEqual(sc.locked_block_id, lb.id)

    def test_5_failed_creation_leaves_neither_row(self):
        lb = self._svc()
        before_lb = self.m.LockedBlock.query.count()
        before_sc = self.m.ScheduledClass.query.count()
        with self.assertRaises(lb.LockedBlockError):
            lb.create_locked_block(self.m.db, assignment_id=1, day="Sun",
                                   start_period=0, length=1, room_id=1)
        self.assertEqual(self.m.LockedBlock.query.count(), before_lb)
        self.assertEqual(self.m.ScheduledClass.query.count(), before_sc)
        # A conflicting second block also persists nothing new.
        self._lock()
        with self.assertRaises(lb.LockedBlockError):
            lb.create_locked_block(self.m.db, assignment_id=2, day="Mon",
                                   start_period=0, length=1, room_id=1)
        self.assertEqual(self.m.LockedBlock.query.count(), before_lb + 1)
        self.assertEqual(self.m.ScheduledClass.query.count(), before_sc + 1)


# ------------------------------------------------------------ validation
class TestLockedValidation(LockedTestBase):
    def _codes(self, exc):
        return [f.code for f in exc.failures]

    def _expect(self, code, **kw):
        lb = self._svc()
        args = dict(assignment_id=1, day="Mon", start_period=1, length=1,
                    room_id=1)
        args.update(kw)
        with self.assertRaises(lb.LockedBlockError) as cm:
            lb.create_locked_block(self.m.db, **args)
        self.assertIn(code, self._codes(cm.exception))
        return cm.exception

    def test_06_invalid_day_rejected(self):
        self._expect("UNKNOWN_DAY", day="Sun")

    def test_07_invalid_period_rejected(self):
        self._expect("PERIOD_OUT_OF_RANGE", start_period=6, length=2)
        # Zero-length geometry is a BLOCK_GEOMETRY failure.
        self._expect("BLOCK_GEOMETRY", start_period=0, length=0)

    def test_08_break_span_rejected(self):
        exc = self._expect("BREAK_SPAN", start_period=3, length=2)
        det = exc.failures[0].details
        self.assertEqual(det["day"], "Mon")

    def test_09_room_conflict_rejected(self):
        self._lock()  # Mon P0 room 101
        exc = self._expect("ROOM_CONFLICT", assignment_id=2, day="Mon",
                           start_period=0, length=1, room_id=1)
        det = [f.details for f in exc.failures
               if f.code == "ROOM_CONFLICT"][0]
        self.assertEqual(det["room_id"], 1)
        self.assertEqual(det["day"], "Mon")
        self.assertEqual(det["periods"], [0])
        self.assertIn("conflicting_class_id", det)

    def test_10_faculty_conflict_rejected(self):
        self._lock()  # F1 busy Mon P0
        # A4: same faculty F1, other section -> faculty clash at Mon P0.
        self.m.db.session.add(self.m.TeachingAssignment(
            id=9, faculty_id=1, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        exc = self._expect("FACULTY_CONFLICT", assignment_id=9, day="Mon",
                           start_period=0, length=1, room_id=2)
        det = [f.details for f in exc.failures
               if f.code == "FACULTY_CONFLICT"][0]
        self.assertEqual(det["faculty_id"], 1)
        self.assertIn("conflicting_assignment_id", det)

    def test_11_faculty_unavailable_rejected(self):
        f1 = self.m.Faculty.query.get(1)
        f1.unavailable_slots = "Mon:2"
        self.m.db.session.commit()
        self._expect("FACULTY_UNAVAILABLE", day="Mon", start_period=2,
                     length=1)

    def test_12_section_conflict_rejected(self):
        self._lock()  # section:1 busy Mon P0
        self._expect("SECTION_CONFLICT", assignment_id=2, day="Mon",
                     start_period=0, length=1, room_id=2)

    def test_13_hierarchy_conflict_rejected(self):
        self._lock()  # whole-section S1 theory Mon P0
        self._expect("SECTION_HIERARCHY_CONFLICT", assignment_id=3,
                     day="Mon", start_period=0, length=2, room_id=3)

    def test_14_hn1_violation_rejected(self):
        self._lock()  # S1 theory Mon P0
        lb = self._svc()
        lb.create_locked_block(self.m.db, assignment_id=1, day="Mon",
                               start_period=1, length=1, room_id=2)
        # A third consecutive theory period would complete Mon P0..P2.
        self._expect("MAX_TWO_THEORY", assignment_id=2, day="Mon",
                     start_period=2, length=1, room_id=1)

    def test_15_room_capacity_type_equipment_rejected(self):
        # 202-lab holds 5 students with 2 equipment: too small for G1 (15).
        self._expect("ROOM_CAPACITY", assignment_id=3, day="Tue",
                     start_period=0, length=2, room_id=4)
        # Theory session in a lab room.
        self._expect("ROOM_TYPE_MISMATCH", day="Tue", start_period=0,
                     length=1, room_id=3)
        # Lab session in a theory room.
        self._expect("ROOM_TYPE_MISMATCH", assignment_id=3, day="Tue",
                     start_period=0, length=2, room_id=1)

    def test_assignment_mismatch_rejected(self):
        lb = self._svc()
        with self.assertRaises(lb.LockedBlockError) as cm:
            lb.create_locked_block(self.m.db, assignment_id=1, day="Tue",
                                   start_period=0, length=1, room_id=1,
                                   faculty_id=2)
        self.assertIn("ASSIGNMENT_MISMATCH",
                      [f.code for f in cm.exception.failures])


# ------------------------------------------------------------- scheduler
class TestLockedScheduler(LockedTestBase):
    def _run(self, locked):
        from backend.scheduler import run_scheduler
        a, r, un, days, n, brk, mc = self._sched_inputs()
        return run_scheduler(a, r, un, days, n, brk, mc,
                             time_limit_seconds=15,
                             locked_placements=locked)

    def _persist_remaining(self, placements):
        import uuid
        run_id = uuid.uuid4().hex[:6]
        for p in placements:
            self.m.db.session.add(self.m.ScheduledClass(
                assignment_id=p["assignment_id"], day=p["day"],
                start_period=p["start_period"], length=p["length"],
                room_id=p["room_id"], run_id=run_id))
        self.m.db.session.commit()

    def test_16_locked_stays_exact(self):
        lb, sc = self._lock(day="Tue", start_period=2)
        status, places, _ = self._run(self._svc().query_locked_placements())
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        kept = self.m.ScheduledClass.query.get(sc.id)
        self.assertEqual((kept.day, kept.start_period, kept.length), ("Tue", 2, 1))

    def test_17_locked_room_unchanged(self):
        lb, sc = self._lock(room_id=2)
        # Room 102 (id 2) must remain the locked room after scheduling.
        self._run(self._svc().query_locked_placements())
        self.assertEqual(self.m.ScheduledClass.query.get(sc.id).room_id, 2)

    def test_18_locked_faculty_unchanged(self):
        lb, sc = self._lock()
        self._run(self._svc().query_locked_placements())
        kept = self.m.ScheduledClass.query.get(sc.id)
        self.assertEqual(
            self.m.TeachingAssignment.query.get(kept.assignment_id).faculty_id, 1)

    def test_19_normal_avoids_locked_room(self):
        lb, sc = self._lock(day="Mon", start_period=0, room_id=1)
        status, places, _ = self._run(self._svc().query_locked_placements())
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        for p in places:
            if p["day"] == "Mon" and p["start_period"] == 0:
                self.assertNotEqual(p["room_id"], 1)

    def test_20_normal_avoids_locked_faculty_periods(self):
        self._lock(day="Mon", start_period=0)  # F1 busy Mon P0
        _, places, _ = self._run(self._svc().query_locked_placements())
        fac_of = {a.id: a.faculty_id
                  for a in self.m.TeachingAssignment.query.all()}
        for p in places:
            if fac_of[p["assignment_id"]] == 1:
                self.assertFalse(
                    p["day"] == "Mon"
                    and p["start_period"] <= 0 < p["start_period"] + p["length"])

    def test_21_section_avoids_locked_occupancy(self):
        self._lock(day="Mon", start_period=0)  # section:1 busy Mon P0
        _, places, _ = self._run(self._svc().query_locked_placements())
        sec_of = {}
        for a in self.m.TeachingAssignment.query.all():
            sec_of[a.id] = (a.section_id, a.lab_group_id)
        for p in places:
            s, lg = sec_of[p["assignment_id"]]
            same_section = (s == 1) or (lg == 10)
            if same_section and p["day"] == "Mon":
                self.assertFalse(
                    p["start_period"] <= 0 < p["start_period"] + p["length"])

    def test_22_hn1_still_applies_with_locked_theory(self):
        from backend import schedule_rules as rules
        lb = self._svc()
        lb.create_locked_block(self.m.db, assignment_id=1, day="Mon",
                               start_period=0, length=1, room_id=1)
        lb.create_locked_block(self.m.db, assignment_id=1, day="Mon",
                               start_period=1, length=1, room_id=2)
        status, places, _ = self._run(lb.query_locked_placements())
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        # No remaining S1 theory may sit at Mon P2 (would be T+T+T).
        for p in places:
            a = self.m.TeachingAssignment.query.get(p["assignment_id"])
            if a.session_type == "theory" and a.section_id == 1 \
                    and p["day"] == "Mon":
                self.assertFalse(
                    p["start_period"] <= 2 < p["start_period"] + p["length"])
        # Full picture (locked + new) satisfies HN1.
        occ = {0, 1}
        for p in places:
            a = self.m.TeachingAssignment.query.get(p["assignment_id"])
            if a.session_type == "theory" and a.section_id == 1 \
                    and p["day"] == "Mon":
                occ.update(range(p["start_period"],
                                 p["start_period"] + p["length"]))
        self.assertEqual(rules.check_max_two_theory(occ, 7, 4, "S1", "Mon", 1), [])

    def test_23_locked_can_make_infeasible(self):
        from flask import Flask
        from backend import models as m
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
            tmp.name, "tiny.db")
        m.db.init_app(app)
        with app.app_context():
            m.db.create_all()
            m.db.session.add(m.Config(session_name="tiny", working_days="Mon",
                                      periods="p0", break_after_periods=0,
                                      max_consecutive_teaching=0))
            m.db.session.add(m.Program(id=1, name="BCA"))
            m.db.session.add(m.Enrollment(id=1, program_id=1, year_label="Y",
                                          total_students=20))
            m.db.session.add(m.Section(id=1, enrollment_id=1, name="S1",
                                       student_count=20))
            m.db.session.add(m.Room(id=1, name="101", room_type="theory",
                                    capacity=50))
            m.db.session.add(m.Faculty(id=1, name="F1"))
            m.db.session.add(m.Faculty(id=2, name="F2"))
            m.db.session.add(m.Subject(id=1, name="M", enrollment_id=1))
            m.db.session.add(m.TeachingAssignment(
                id=1, faculty_id=1, subject_id=1, session_type="theory",
                section_id=1, periods_per_week=1, block_length=1))
            m.db.session.add(m.TeachingAssignment(
                id=2, faculty_id=2, subject_id=1, session_type="theory",
                section_id=1, periods_per_week=1, block_length=1))
            m.db.session.commit()
            from backend import locked_blocks as svc
            svc.create_locked_block(m.db, assignment_id=1, day="Mon",
                                    start_period=0, length=1, room_id=1)
            from backend.scheduler import run_scheduler
            status, places, msg = run_scheduler(
                m.TeachingAssignment.query.all(), m.Room.query.all(),
                {1: set(), 2: set()}, ["Mon"], 1, None, None,
                time_limit_seconds=10,
                locked_placements=svc.query_locked_placements())
            self.assertEqual(status, "INFEASIBLE")
            self.assertEqual(places, [])
            self.assertIn("Locked block", msg)
            m.db.session.remove()
            m.db.engine.dispose()

    def test_25_multiple_compatible_locks_coexist(self):
        lb = self._svc()
        lb.create_locked_block(self.m.db, assignment_id=1, day="Mon",
                               start_period=0, length=1, room_id=1)
        lb.create_locked_block(self.m.db, assignment_id=1, day="Tue",
                               start_period=0, length=1, room_id=1)
        self.assertEqual(self.m.LockedBlock.query.count(), 2)
        status, _, _ = self._run(lb.query_locked_placements())
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))

    def test_26_conflicting_locks_rejected_before_generation(self):
        self._lock(day="Mon", start_period=0, room_id=1)
        lb = self._svc()
        with self.assertRaises(lb.LockedBlockError) as cm:
            lb.create_locked_block(self.m.db, assignment_id=2, day="Mon",
                                   start_period=0, length=1, room_id=1)
        codes = [f.code for f in cm.exception.failures]
        self.assertTrue(any(c in ("ROOM_CONFLICT", "SECTION_CONFLICT",
                                  "FACULTY_CONFLICT") for c in codes))
        self.assertEqual(self.m.LockedBlock.query.count(), 1)


# ------------------------------------------------------------- validator
class TestLockedValidator(LockedTestBase):
    """Part 15: candidate edits cannot move a locked block (6H foundation)."""

    def _snap(self):
        from backend import schedule_validator as sv
        from types import SimpleNamespace
        rooms = [SimpleNamespace(id=1, name="101", room_type="theory",
                                 capacity=100, equipment_count=None)]
        fac = [SimpleNamespace(id=1, unavailable_slots=""),
               SimpleNamespace(id=2, unavailable_slots="")]
        secs = [SimpleNamespace(id=1, name="BCA-1-A", student_count=30)]
        assign = [SimpleNamespace(
            id=1, faculty_id=1, session_type="theory", section_id=1,
            lab_group_id=None, section_name="BCA-1-A", section_size=30)]
        _, sc = self._lock()
        classes = [SimpleNamespace(id=sc.id, assignment_id=1, day="Mon",
                                   start_period=0, length=1, room_id=1,
                                   is_locked=True, locked_block_id=sc.locked_block_id)]
        return sv.build_snapshot(["Mon", "Tue"], 7, 4, 3, rooms, fac, [],
                                 secs, assign, classes), sc

    def _cand(self, **kw):
        args = dict(session_type="theory", group_key="section:1",
                    group_label="BCA-1-A", group_size=30, faculty_id=1,
                    day="Tue", start_period=0, length=1, room_id=1)
        args.update(kw)
        return args

    def test_move_of_locked_refused_with_details(self):
        from backend import schedule_validator as sv
        snap, sc = self._snap()
        fails = sv.validate_move(snap, sc.id, **self._cand())
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0].code, "LOCKED_BLOCK")
        self.assertEqual(fails[0].details["scheduled_class_id"], sc.id)
        self.assertEqual(fails[0].details["locked_block_id"],
                         sc.locked_block_id)
        self.assertIn("attempted_change", fails[0].details)

    def test_candidate_with_editing_id_refused(self):
        from backend import schedule_validator as sv
        snap, sc = self._snap()
        fails = sv.validate_candidate(snap, editing_class_id=sc.id,
                                      **self._cand())
        self.assertEqual([f.code for f in fails], ["LOCKED_BLOCK"])

    def test_identical_placement_is_not_a_move(self):
        from backend import schedule_validator as sv
        snap, sc = self._snap()
        # Identical placement: no LOCKED_BLOCK refusal (residual
        # self-occupancy failures are the caller's to exclude via
        # snapshot_without, exactly as validate_move does).
        fails = sv.validate_candidate(
            snap, editing_class_id=sc.id,
            **self._cand(day="Mon", start_period=0))
        self.assertNotIn("LOCKED_BLOCK", [f.code for f in fails])
        slim = sv.snapshot_without(snap, sc.id)
        fails = sv.validate_candidate(
            slim, editing_class_id=None,
            **self._cand(day="Mon", start_period=0))
        self.assertEqual(fails, [])

    def test_unlocked_class_moves_normally(self):
        from backend import schedule_validator as sv
        from types import SimpleNamespace
        snap, sc = self._snap()
        slim = sv.snapshot_without(snap, sc.id)
        # An unlocked class at the same spot validates like any candidate.
        plain = [SimpleNamespace(id=sc.id, assignment_id=1, day="Mon",
                                 start_period=0, length=1, room_id=1)]
        snap2 = sv.build_snapshot(["Mon", "Tue"], 7, 4, 3,
                                  [SimpleNamespace(id=1, name="101",
                                                   room_type="theory",
                                                   capacity=100,
                                                   equipment_count=None)],
                                  [SimpleNamespace(id=1, unavailable_slots="")],
                                  [], [SimpleNamespace(id=1, name="BCA-1-A",
                                                       student_count=30)],
                                  [SimpleNamespace(
                                      id=1, faculty_id=1, session_type="theory",
                                      section_id=1, lab_group_id=None,
                                      section_name="BCA-1-A", section_size=30)],
                                  plain)
        fails = sv.validate_move(snap2, sc.id, **self._cand())
        self.assertEqual(fails, [])
        self.assertNotIn(sc.id, slim.locked_class_ids)


# ----------------------------------------------------------------- audit
class TestLockedAudit(LockedTestBase):
    def _snapshot_via_cli(self):
        from backend.audit_schedule import load_snapshot, open_readonly
        con = open_readonly(self.db_path)
        try:
            return load_snapshot(con)
        finally:
            con.close()

    def test_27_valid_block_no_audit_error(self):
        from backend.audit_schedule import audit_snapshot
        self._lock()
        snap = self._snapshot_via_cli()
        problems, _ = audit_snapshot(snap)
        locked = [p for p in problems if "LOCKED" in p]
        self.assertEqual(locked, [])

    def test_28_corrupted_placement_detected(self):
        from backend.audit_schedule import audit_snapshot
        _, sc = self._lock()
        sc.day = "Tue"  # tamper: ScheduledClass drifts from the block
        self.m.db.session.commit()
        snap = self._snapshot_via_cli()
        problems, _ = audit_snapshot(snap)
        self.assertTrue(any("LOCKED_BLOCK_MISMATCH" in p for p in problems))

    def test_29_missing_class_detected(self):
        from backend.audit_schedule import audit_snapshot
        lb, sc = self._lock()
        self.m.db.session.delete(sc)  # block left without its class
        self.m.db.session.commit()
        snap = self._snapshot_via_cli()
        problems, _ = audit_snapshot(snap)
        self.assertTrue(any("LOCKED_BLOCK_ORPHAN" in p for p in problems))

    def test_30_audit_byte_for_byte_read_only(self):
        from backend.audit_schedule import run_audit
        self._lock()
        self.m.db.session.remove()
        self.m.db.engine.dispose()
        before = _sha(self.db_path)
        code, _ = run_audit(self.db_path)
        self.assertEqual(code, 0)
        self.assertEqual(_sha(self.db_path), before)


# ------------------------------------------------------------------- API
class TestLockedApi(LockedTestBase):
    """Backend API foundation: create / read / delete + failure shape."""

    def setUp(self):
        super().setUp()
        from flask_login import LoginManager
        from backend.api_routes import init_api
        # Host the /api/* blueprint on the SAME throwaway app (a second
        # Flask app on the same sqlite file would lock it on Windows).
        # backend.app itself is never imported: it would touch the live DB.
        self.app.secret_key = "6e-test"
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

    def test_31_create_endpoint_works(self):
        resp = self.client.post("/api/locked-blocks", json={
            "assignment_id": 1, "day": "Mon", "start_period": 0,
            "length": 1, "room_id": 1})
        self.assertEqual(resp.status_code, 201, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["locked_block"]["day"], "Mon")
        self.assertEqual(body["scheduled_class"]["locked_block_id"],
                         body["locked_block"]["id"])
        row = self.m.ScheduledClass.query.get(
            body["scheduled_class"]["id"])
        self.assertTrue(row.is_locked)

    def test_32_read_endpoint_works(self):
        self._lock()
        resp = self.client.get("/api/locked-blocks")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(len(body["locked_blocks"]), 1)
        self.assertEqual(body["locked_blocks"][0]["kind"], "interdepartment")
        self.assertIsNotNone(
            body["locked_blocks"][0]["scheduled_class_id"])

    def test_33_delete_endpoint_removes_both_rows(self):
        lb, sc = self._lock()
        resp = self.client.post(f"/api/locked-blocks/{lb.id}/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(self.m.LockedBlock.query.get(lb.id))
        self.assertIsNone(self.m.ScheduledClass.query.get(sc.id))

    def test_34_invalid_returns_structured_error(self):
        resp = self.client.post("/api/locked-blocks", json={
            "assignment_id": 1, "day": "Sun", "start_period": 0,
            "length": 1, "room_id": 1})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "UNKNOWN_DAY")
        self.assertIn("details", body)
        self.assertTrue(body["failures"])
        self.assertEqual(self.m.LockedBlock.query.count(), 0)
        self.assertEqual(self.m.ScheduledClass.query.count(), 0)

    def test_24_infeasible_generation_preserves_schedule(self):
        # Tiny single-slot world: the locked block leaves assignment 2
        # (same section) with no feasible placement.
        m = self.m
        for a in m.TeachingAssignment.query.all():
            m.db.session.delete(a)
        m.db.session.add(m.TeachingAssignment(
            id=11, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=1, block_length=1))
        m.db.session.add(m.TeachingAssignment(
            id=12, faculty_id=2, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=1, block_length=1))
        cfg = m.Config.query.first()
        cfg.working_days = "Mon"
        cfg.periods = "p0"
        cfg.break_after_periods = 0
        cfg.max_consecutive_teaching = 0
        m.db.session.commit()
        resp = self.client.post("/api/locked-blocks", json={
            "assignment_id": 11, "day": "Mon", "start_period": 0,
            "length": 1, "room_id": 1})
        self.assertEqual(resp.status_code, 201)
        before = sorted(
            (c.id, c.assignment_id, c.day, c.start_period, c.length,
             c.room_id) for c in m.ScheduledClass.query.all())
        resp = self.client.post("/api/schedule/run")
        self.assertEqual(resp.status_code, 422, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertEqual(body["code"], "SCHEDULING_INFEASIBLE")
        self.assertIn("locked_block_ids", body["details"])
        after = sorted(
            (c.id, c.assignment_id, c.day, c.start_period, c.length,
             c.room_id) for c in m.ScheduledClass.query.all())
        self.assertEqual(before, after)


# -------------------------------------------------------------- migration
class TestMigration6E(unittest.TestCase):
    def test_upgrade_adds_assignment_id_and_downgrade_removes(self):
        import importlib
        up6c = importlib.import_module(
            "backend.migrations.versions.6c_additive_schema")
        up6e = importlib.import_module(
            "backend.migrations.versions.6e_locked_assignment")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = os.path.join(tmp.name, "m.db")
        con = sqlite3.connect(db)
        try:
            con.execute("CREATE TABLE teaching_assignment (id INTEGER PRIMARY KEY)")
            con.execute("CREATE TABLE subject (id INTEGER PRIMARY KEY)")
            con.execute("CREATE TABLE faculty (id INTEGER PRIMARY KEY)")
            con.execute("CREATE TABLE section (id INTEGER PRIMARY KEY)")
            con.execute("CREATE TABLE lab_group (id INTEGER PRIMARY KEY)")
            con.execute("CREATE TABLE room (id INTEGER PRIMARY KEY)")
            con.execute("CREATE TABLE locked_block (id INTEGER PRIMARY KEY, "
                        "kind VARCHAR(30), subject_id INTEGER, faculty_id INTEGER, "
                        "section_id INTEGER, lab_group_id INTEGER, day VARCHAR(10), "
                        "start_period INTEGER, length INTEGER, room_id INTEGER, "
                        "room_locked BOOLEAN, department VARCHAR(120), "
                        "is_external BOOLEAN, note TEXT)")
            up6e.upgrade(con)
            con.commit()
            cols = [r[1] for r in con.execute('PRAGMA table_info("locked_block")')]
            self.assertIn("assignment_id", cols)
            # Nullable: legacy rows without the link stay valid.
            con.execute("INSERT INTO locked_block "
                        "(kind, subject_id, faculty_id, day, start_period, length) "
                        "VALUES ('interdepartment', 1, 1, 'Mon', 0, 1)")
            con.commit()
            up6e.downgrade(con)
            con.commit()
            cols = [r[1] for r in con.execute('PRAGMA table_info("locked_block")')]
            self.assertNotIn("assignment_id", cols)
            self.assertEqual(
                con.execute("SELECT day FROM locked_block").fetchone()[0], "Mon")
        finally:
            con.close()

    def test_revision_chain_links_6c(self):
        import importlib
        up6e = importlib.import_module(
            "backend.migrations.versions.6e_locked_assignment")
        self.assertEqual(up6e.down_revision, "6c_additive_schema")
