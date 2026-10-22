"""Phase 6H.2 tests: faculty reassignment domain service.

Covers valid reassignment, noop, missing resources, availability (H9),
double-booking (H6 + conflicting context), consecutive teaching (H12),
locked-block rejection, specialization per-slot validation, weekly-load
soft warning, multi-class all-or-nothing, atomicity (DB byte-identical on
failure), and post-flush verification rollback.

Every test uses throwaway SQLite files in a temp dir — never the real
database. Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_faculty_reassignment_6h -v
"""
import os
import tempfile
import unittest
from unittest import mock

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))


class ReassignTestBase(unittest.TestCase):
    """Throwaway Flask app + small seeded timetable (all placements valid)."""

    def setUp(self):
        from flask import Flask
        from backend import models as m
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6h2.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6H2", working_days=DAYS,
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
        # A1: F1 theory S1 (2 classes). A2: F2 theory S1.
        # A3: F1 theory S2. A4: F2 practical G1 (block 2). A5: F3 theory S2.
        # A6: F4 theory S1 (load probe).
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
        # Valid seed timetable.
        self._place(1, 1, "Mon", 0, 1, 1)    # SC1 A1 Mon P0 R101 (F1)
        self._place(2, 1, "Mon", 1, 1, 1)    # SC2 A1 Mon P1 R101 (F1)
        self._place(3, 2, "Mon", 4, 1, 2)    # SC3 A2 Mon P4 R102 (F2)
        self._place(4, 3, "Tue", 0, 1, 1)    # SC4 A3 Tue P0 R101 (F1)
        self._place(5, 4, "Tue", 0, 2, 4)    # SC5 A4 Tue P0-1 L1  (F2)
        self._place(6, 5, "Wed", 0, 1, 2)    # SC6 A5 Wed P0 R102 (F3)
        self._place(7, 2, "Wed", 1, 1, 1)    # SC7 A2 Wed P1 R101 (F2)
        self._place(8, 6, "Wed", 2, 1, 2)    # SC8 A6 Wed P2 R102 (F4)

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

    def _faculty_of(self, aid):
        return self.m.TeachingAssignment.query.get(aid).faculty_id

    def _codes(self, exc):
        return [f.code for f in exc.failures]

    def _validate(self, aid, fid):
        from backend import faculty_reassignment as fr
        return fr.validate_reassignment(self.m.db, aid, fid)

    def _reassign(self, aid, fid):
        from backend import faculty_reassignment as fr
        return fr.reassign_faculty(self.m.db, aid, fid)

    def _mk_spec_cohort(self, day="Mon", start=2, room_ids=(2, 1)):
        """Two synchronized theory specs (Cyber/AI) sharing one slot."""
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


# ------------------------------------------------------- basic + noop
class TestBasicReassignment(ReassignTestBase):
    def test_valid_reassignment_persists(self):
        # A5 (F3, Wed P0) -> F1 (free Wed P0; F1 has no Wed classes).
        assignment, result = self._reassign(5, 1)
        self.assertTrue(result.ok)
        self.assertFalse(result.noop)
        self.assertEqual(assignment.faculty_id, 1)
        self.assertEqual(self._faculty_of(5), 1)

    def test_placements_unchanged(self):
        before = self._rows()
        self._reassign(5, 1)
        after = self._rows()
        # Same ids/days/starts/lengths/rooms/runs/locks; only the
        # assignment's faculty (not a class column) changed.
        self.assertEqual(before, after)

    def test_faculty_resolves_through_assignment(self):
        self._reassign(5, 1)
        sc = self.m.ScheduledClass.query.get(6)
        self.assertEqual(sc.assignment.faculty_id, 1)
        self.assertEqual(sc.assignment.faculty.name, "F1")

    def test_validate_ok_shape(self):
        result = self._validate(5, 1)
        self.assertTrue(result.ok)
        self.assertFalse(result.noop)
        self.assertEqual(result.assignment_id, 5)
        self.assertEqual(result.current_faculty_id, 3)
        self.assertEqual(result.new_faculty_id, 1)
        self.assertEqual(result.scheduled_class_ids, [6])


class TestNoop(ReassignTestBase):
    def test_same_faculty_noop(self):
        result = self._validate(1, 1)
        self.assertTrue(result.ok)
        self.assertTrue(result.noop)

    def test_noop_mutation_writes_nothing(self):
        before_rows = self._rows()
        before_fac = self._faculty_of(1)
        assignment, result = self._reassign(1, 1)
        self.assertTrue(result.ok)
        self.assertTrue(result.noop)
        self.assertEqual(assignment.faculty_id, before_fac)
        self.assertEqual(self._rows(), before_rows)


# ------------------------------------------------------- missing
class TestMissingResources(ReassignTestBase):
    def test_missing_assignment(self):
        from backend import faculty_reassignment as fr
        with self.assertRaises(fr.FacultyReassignmentError) as cm:
            self._validate(999, 1)
        self.assertIn("UNKNOWN_ASSIGNMENT", self._codes(cm.exception))

    def test_missing_faculty(self):
        from backend import faculty_reassignment as fr
        with self.assertRaises(fr.FacultyReassignmentError) as cm:
            self._validate(1, 999)
        self.assertIn("UNKNOWN_FACULTY", self._codes(cm.exception))

    def test_missing_assignment_mutation_changes_nothing(self):
        from backend import faculty_reassignment as fr
        before_rows = self._rows()
        with self.assertRaises(fr.FacultyReassignmentError):
            self._reassign(999, 1)
        self.assertEqual(self._rows(), before_rows)
        self.assertEqual(self._faculty_of(1), 1)


# ------------------------------------------------------- availability H9
class TestAvailability(ReassignTestBase):
    def test_unavailable_single_period(self):
        from backend import faculty_reassignment as fr
        f2 = self.m.Faculty.query.get(2)
        f2.unavailable_slots = "Mon:0"
        self.m.db.session.commit()
        # A1 has Mon P0+P1; F2 unavailable Mon P0.
        result = self._validate(1, 2)
        self.assertFalse(result.ok)
        self.assertIn("FACULTY_UNAVAILABLE", [f.code for f in result.failures])
        with self.assertRaises(fr.FacultyReassignmentError) as cm:
            self._reassign(1, 2)
        self.assertIn("FACULTY_UNAVAILABLE", self._codes(cm.exception))

    def test_unavailable_one_of_several_rolls_back(self):
        from backend import faculty_reassignment as fr
        f2 = self.m.Faculty.query.get(2)
        f2.unavailable_slots = "Mon:1"  # second of A1's two classes
        self.m.db.session.commit()
        before_rows = self._rows()
        result = self._validate(1, 2)
        self.assertFalse(result.ok)
        with self.assertRaises(fr.FacultyReassignmentError):
            self._reassign(1, 2)
        self.assertEqual(self._faculty_of(1), 1)
        self.assertEqual(self._rows(), before_rows)

    def test_unavailable_details(self):
        f2 = self.m.Faculty.query.get(2)
        f2.unavailable_slots = "Mon:0"
        self.m.db.session.commit()
        result = self._validate(1, 2)
        unavail = [f for f in result.failures
                   if f.code == "FACULTY_UNAVAILABLE"]
        self.assertTrue(unavail)
        det = unavail[0].details
        self.assertEqual(det.get("faculty_id"), 2)
        self.assertEqual(det.get("assignment_id"), 1)
        self.assertIn("scheduled_class_id", det)


# ------------------------------------------------------- conflict H6
class TestFacultyConflict(ReassignTestBase):
    def _seed_overlap(self):
        # A7 (F2, S2) Mon P0 overlaps A1 (S1) Mon P0 in time but not
        # faculty/group pre-reassign — valid seed, conflict post-reassign.
        self.m.db.session.add(self.m.TeachingAssignment(
            id=7, faculty_id=2, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        self._place(9, 7, "Mon", 0, 1, 2)

    def test_conflict_rejected(self):
        from backend import faculty_reassignment as fr
        self._seed_overlap()
        result = self._validate(1, 2)
        self.assertFalse(result.ok)
        self.assertIn("FACULTY_CONFLICT", [f.code for f in result.failures])
        with self.assertRaises(fr.FacultyReassignmentError):
            self._reassign(1, 2)

    def test_conflict_carries_context_and_rolls_back(self):
        from backend import faculty_reassignment as fr
        self._seed_overlap()
        before_rows = self._rows()
        result = self._validate(1, 2)
        conflicts = [f for f in result.failures
                     if f.code == "FACULTY_CONFLICT"]
        self.assertTrue(conflicts)
        det = conflicts[0].details
        self.assertIn("conflicting_class_id", det)
        self.assertIn("conflicting_assignment_id", det)
        self.assertEqual(det.get("faculty_id"), 2)
        with self.assertRaises(fr.FacultyReassignmentError):
            self._reassign(1, 2)
        self.assertEqual(self._faculty_of(1), 1)
        self.assertEqual(self._faculty_of(7), 2)
        self.assertEqual(self._rows(), before_rows)


# ------------------------------------------------------- consecutive H12
class TestConsecutive(ReassignTestBase):
    def _seed_run(self):
        # F2 Tue P1+P2+P3 (run 3, valid). A3 (S2) Tue P0 -> F2 gives P0-3.
        self.m.db.session.add(self.m.TeachingAssignment(
            id=8, faculty_id=2, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=3, block_length=1))
        self.m.db.session.commit()
        self._place(10, 8, "Tue", 1, 1, 2)
        self._place(11, 8, "Tue", 2, 1, 2)
        self._place(12, 8, "Tue", 3, 1, 2)

    def test_consecutive_violation(self):
        from backend import faculty_reassignment as fr
        self._seed_run()
        result = self._validate(3, 2)  # A3 Tue P0 -> F2
        self.assertFalse(result.ok)
        self.assertIn("FACULTY_CONSECUTIVE", [f.code for f in result.failures])

    def test_consecutive_rolls_back(self):
        from backend import faculty_reassignment as fr
        self._seed_run()
        before_rows = self._rows()
        with self.assertRaises(fr.FacultyReassignmentError) as cm:
            self._reassign(3, 2)
        self.assertIn("FACULTY_CONSECUTIVE", self._codes(cm.exception))
        self.assertEqual(self._faculty_of(3), 1)
        self.assertEqual(self._rows(), before_rows)


# ------------------------------------------------------- locked
class TestLocked(ReassignTestBase):
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

    def test_locked_class_rejected(self):
        from backend import faculty_reassignment as fr
        self._lock_assignment_1()
        with self.assertRaises(fr.FacultyReassignmentError) as cm:
            self._validate(1, 2)
        self.assertIn("LOCKED_BLOCK", self._codes(cm.exception))

    def test_locked_reassignment_changes_nothing(self):
        from backend import faculty_reassignment as fr
        lb = self._lock_assignment_1()
        before_rows = self._rows()
        before_lb = (lb.id, lb.assignment_id, lb.faculty_id, lb.day,
                     lb.start_period, lb.length, lb.room_id)
        with self.assertRaises(fr.FacultyReassignmentError):
            self._reassign(1, 2)
        self.assertEqual(self._faculty_of(1), 1)
        self.assertEqual(self._rows(), before_rows)
        after = self.m.LockedBlock.query.get(lb.id)
        self.assertEqual((after.id, after.assignment_id, after.faculty_id,
                          after.day, after.start_period, after.length,
                          after.room_id), before_lb)

    def test_locked_block_without_class_flag_rejected(self):
        from backend import faculty_reassignment as fr
        lb = self.m.LockedBlock(
            kind="interdepartment", assignment_id=3, subject_id=1,
            faculty_id=1, section_id=2, day="Tue", start_period=0,
            length=1, room_id=1, room_locked=True)
        self.m.db.session.add(lb)
        self.m.db.session.commit()
        with self.assertRaises(fr.FacultyReassignmentError) as cm:
            self._reassign(3, 2)
        self.assertIn("LOCKED_BLOCK", self._codes(cm.exception))
        self.assertEqual(self._faculty_of(3), 1)


# ------------------------------------------------------- specializations
class TestSpecialization(ReassignTestBase):
    def test_valid_spec_reassignment(self):
        # Tue P2 avoids the Mon P0/P1 normal-theory streak for section 1
        # (HN1 is section-based, so a Mon P2 spec slot would already
        # complete a P0/P1/P2 streak regardless of faculty).
        specs = self._mk_spec_cohort(day="Tue", start=2)
        _spec, assign, _sc, _slot = specs["Cyber"]
        before_slots = sorted(
            (s.specialization_id, s.day, s.start_period, s.length)
            for s in self.m.SpecializationSlot.query.all())
        new_id, result = self._reassign(assign.id, 1), None
        assignment, result = new_id
        self.assertTrue(result.ok)
        self.assertEqual(assignment.faculty_id, 1)
        after_slots = sorted(
            (s.specialization_id, s.day, s.start_period, s.length)
            for s in self.m.SpecializationSlot.query.all())
        self.assertEqual(before_slots, after_slots)

    def test_spec_conflict_on_synced_slot(self):
        from backend import faculty_reassignment as fr
        specs = self._mk_spec_cohort()
        _spec, assign, _sc, _slot = specs["Cyber"]
        # F1 busy Mon P2 in R101/S1 — overlaps Cyber Mon P2 faculty-wise.
        self.m.db.session.add(self.m.TeachingAssignment(
            id=20, faculty_id=1, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        self._place(20, 20, "Mon", 2, 1, 1)
        result = self._validate(assign.id, 1)
        self.assertFalse(result.ok)
        self.assertIn("FACULTY_CONFLICT", [f.code for f in result.failures])
        with self.assertRaises(fr.FacultyReassignmentError):
            self._reassign(assign.id, 1)

    def test_spec_unavailable(self):
        from backend import faculty_reassignment as fr
        specs = self._mk_spec_cohort()
        _spec, assign, _sc, _slot = specs["Cyber"]
        f1 = self.m.Faculty.query.get(1)
        f1.unavailable_slots = "Mon:2"
        self.m.db.session.commit()
        result = self._validate(assign.id, 1)
        self.assertFalse(result.ok)
        self.assertIn("FACULTY_UNAVAILABLE", [f.code for f in result.failures])
        with self.assertRaises(fr.FacultyReassignmentError):
            self._reassign(assign.id, 1)
        self.assertEqual(
            self.m.TeachingAssignment.query.get(assign.id).faculty_id, 3)


# ------------------------------------------------------- weekly load
class TestWeeklyLoad(ReassignTestBase):
    def test_overload_warns_but_succeeds(self):
        # F4 (max 3) already carries A6 (2 hrs). A5 adds 3 -> 5 > 3.
        assignment, result = self._reassign(5, 4)
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.warning)
        self.assertTrue(result.warning.get("exceeded"))
        self.assertEqual(result.warning.get("resulting_load"), 5)
        self.assertEqual(result.warning.get("max_hours"), 3)
        self.assertEqual(assignment.faculty_id, 4)

    def test_within_max_no_warning(self):
        _assignment, result = self._reassign(5, 1)
        # F1: A1(5)+A3(3)=8, +A5(3)=11 <= 24.
        self.assertTrue(result.ok)
        self.assertIsNone(result.warning)


# ------------------------------------------------------- multiple classes
class TestMultipleClasses(ReassignTestBase):
    def test_all_classes_validated_last_failure_rolls_back(self):
        from backend import faculty_reassignment as fr
        f2 = self.m.Faculty.query.get(2)
        f2.unavailable_slots = "Mon:1"  # A1's second class only
        self.m.db.session.commit()
        before_rows = self._rows()
        result = self._validate(1, 2)
        self.assertFalse(result.ok)
        # Both of A1's classes were examined (failure names SC2).
        sc_ids = {f.details.get("scheduled_class_id") for f in result.failures}
        self.assertIn(2, sc_ids)
        with self.assertRaises(fr.FacultyReassignmentError):
            self._reassign(1, 2)
        self.assertEqual(self._faculty_of(1), 1)
        self.assertEqual(self._rows(), before_rows)

    def test_assignment_class_ids_cover_all(self):
        result = self._validate(1, 3)  # F3 free Mon P0/P1
        self.assertTrue(result.ok)
        self.assertEqual(sorted(result.scheduled_class_ids), [1, 2])


# ------------------------------------------------------- atomicity
class TestAtomicity(ReassignTestBase):
    def test_invalid_leaves_everything_unchanged(self):
        from backend import faculty_reassignment as fr
        f2 = self.m.Faculty.query.get(2)
        f2.unavailable_slots = "Mon:0"
        self.m.db.session.commit()
        before_rows = self._rows()
        before_fac = {a.id: a.faculty_id
                      for a in self.m.TeachingAssignment.query.all()}
        before_faculty = [(f.id, f.name, f.unavailable_slots)
                          for f in self.m.Faculty.query.all()]
        before_locks = [ (lb.id, lb.assignment_id, lb.faculty_id)
                         for lb in self.m.LockedBlock.query.all()]
        with self.assertRaises(fr.FacultyReassignmentError):
            self._reassign(1, 2)
        self.assertEqual(self._rows(), before_rows)
        self.assertEqual({a.id: a.faculty_id
                          for a in self.m.TeachingAssignment.query.all()},
                         before_fac)
        self.assertEqual([(f.id, f.name, f.unavailable_slots)
                          for f in self.m.Faculty.query.all()],
                         before_faculty)
        self.assertEqual([(lb.id, lb.assignment_id, lb.faculty_id)
                          for lb in self.m.LockedBlock.query.all()],
                         before_locks)
        # Unrelated assignments untouched.
        self.assertEqual(self._faculty_of(2), 2)
        self.assertEqual(self._faculty_of(5), 3)


# ------------------------------------------------------- post-flush
class TestPostFlushVerification(ReassignTestBase):
    def test_post_flush_failure_rolls_back(self):
        from backend import faculty_reassignment as fr
        from backend import schedule_rules as rules
        before_rows = self._rows()
        forced = [rules.RuleResult(ok=False, code="FACULTY_CONFLICT",
                                   message="forced post-flush failure",
                                   details={})]
        with mock.patch.object(fr, "_verify_post_flush",
                               return_value=forced):
            with self.assertRaises(fr.FacultyReassignmentError):
                self._reassign(5, 1)
        self.assertEqual(self._faculty_of(5), 3)
        self.assertEqual(self._rows(), before_rows)


if __name__ == "__main__":
    unittest.main()
