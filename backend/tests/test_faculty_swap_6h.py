"""Phase 6H.3 tests: faculty swap domain service.

Covers valid normal<->normal swaps, noop/invalid identity, availability
(H9) per side, double-booking (H6 + conflicting context) per side,
consecutive teaching (H12) per side, locked-block rejection on either
side, specialization<->specialization swaps (slots unchanged),
normal<->specialization rejection, weekly-load math + soft warnings,
multi-class all-or-nothing, unscheduled sides, same-period A/B overlap
(no false conflict), atomicity (failed swap = no persistent change), and
post-flush verification rollback.

Every test uses throwaway SQLite files in a temp dir — never the real
database. Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_faculty_swap_6h -v
"""
import os
import tempfile
import unittest
from unittest import mock

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))


class SwapTestBase(unittest.TestCase):
    """Throwaway Flask app + small seeded timetable (all placements valid).

    Seed mirrors Phase 6H.2: A1 F1/S1 (Mon P0+P1), A2 F2/S1 (Mon P4,
    Wed P1), A3 F1/S2 (Tue P0), A4 F2 practical G1 (Tue P0-1), A5 F3/S2
    (Wed P0), A6 F4/S1 (Wed P2, load probe, F4 max 3).
    """

    def setUp(self):
        from flask import Flask
        from backend import models as m
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6h3.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6H3", working_days=DAYS,
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

    def _assignment_map(self):
        return {a.id: a.faculty_id
                for a in self.m.TeachingAssignment.query.all()}

    def _faculty_rows(self):
        return sorted((f.id, f.name, f.unavailable_slots,
                       f.weekly_max_hours)
                      for f in self.m.Faculty.query.all())

    def _lock_rows(self):
        return sorted((lb.id, lb.assignment_id, lb.faculty_id, lb.day,
                       lb.start_period, lb.length, lb.room_id)
                      for lb in self.m.LockedBlock.query.all())

    def _slot_rows(self):
        return sorted((s.id, s.specialization_id, s.day, s.start_period,
                       s.length)
                      for s in self.m.SpecializationSlot.query.all())

    def _state(self):
        return (self._assignment_map(), self._rows(), self._faculty_rows(),
                self._lock_rows(), self._slot_rows())

    def _codes(self, exc):
        return [f.code for f in exc.failures]

    def _sides(self, exc):
        return {f.details.get("swap_side") for f in exc.failures}

    def _validate(self, aid, bid):
        from backend import faculty_swaps as fs
        return fs.validate_faculty_swap(self.m.db, aid, bid)

    def _swap(self, aid, bid):
        from backend import faculty_swaps as fs
        return fs.swap_faculty(self.m.db, aid, bid)

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


# ------------------------------------------------------- basic swaps
class TestBasicSwaps(SwapTestBase):
    def test_valid_normal_swap(self):
        # A1 (F1: Mon P0+P1 S1) <-> A5 (F3: Wed P0 S2).
        result = self._validate(1, 5)
        self.assertTrue(result.ok)
        self.assertFalse(result.noop)
        self.assertEqual(
            (result.assignment_a_id, result.assignment_b_id,
             result.faculty_a_id, result.faculty_b_id), (1, 5, 1, 3))

    def test_faculty_ids_exchanged(self):
        a, b, result = self._swap(1, 5)
        self.assertTrue(result.ok)
        self.assertEqual((a.faculty_id, b.faculty_id), (3, 1))
        self.assertEqual(self._faculty_of(1), 3)
        self.assertEqual(self._faculty_of(5), 1)

    def test_placements_unchanged_no_regeneration(self):
        before = self._rows()
        self._swap(1, 5)
        self.assertEqual(self._rows(), before)
        # run_ids preserved: no schedule regeneration occurred.
        self.assertTrue(all(r[6] == "run1" for r in self._rows()))

    def test_no_faculty_column_on_scheduled_class(self):
        self._swap(1, 5)
        sc = self.m.ScheduledClass.query.get(1)
        self.assertFalse(hasattr(sc, "faculty_id"))
        # Faculty resolves through the swapped assignment.
        self.assertEqual(sc.assignment.faculty.name, "F3")


# ------------------------------------------------------- noop / identity
class TestNoopInvalidIdentity(SwapTestBase):
    def test_same_faculty_noop(self):
        # A1 and A3 both teach F1: nothing would change.
        result = self._validate(1, 3)
        self.assertTrue(result.ok)
        self.assertTrue(result.noop)

    def test_same_faculty_writes_nothing(self):
        before = self._state()
        a, b, result = self._swap(1, 3)
        self.assertTrue(result.noop)
        self.assertEqual((a.faculty_id, b.faculty_id), (1, 1))
        self.assertEqual(self._state(), before)

    def test_same_assignment_rejected(self):
        from backend import faculty_swaps as fs
        before = self._state()
        with self.assertRaises(fs.FacultySwapError) as cm:
            self._validate(1, 1)
        self.assertIn("INVALID_SWAP", self._codes(cm.exception))
        with self.assertRaises(fs.FacultySwapError):
            self._swap(1, 1)
        self.assertEqual(self._state(), before)

    def test_missing_assignment_a(self):
        from backend import faculty_swaps as fs
        with self.assertRaises(fs.FacultySwapError) as cm:
            self._validate(999, 1)
        self.assertIn("UNKNOWN_ASSIGNMENT", self._codes(cm.exception))
        self.assertEqual(cm.exception.failures[0].details.get("swap_side"),
                         "A")

    def test_missing_assignment_b(self):
        from backend import faculty_swaps as fs
        before = self._state()
        with self.assertRaises(fs.FacultySwapError) as cm:
            self._swap(1, 999)
        self.assertIn("UNKNOWN_ASSIGNMENT", self._codes(cm.exception))
        self.assertEqual(cm.exception.failures[0].details.get("swap_side"),
                         "B")
        self.assertEqual(self._state(), before)


# ------------------------------------------------------- availability H9
class TestAvailability(SwapTestBase):
    def test_side_a_unavailable_rejects(self):
        from backend import faculty_swaps as fs
        f2 = self.m.Faculty.query.get(2)
        f2.unavailable_slots = "Mon:0"
        self.m.db.session.commit()
        # Side A: A1 (Mon P0+P1) under F2 hits Mon P0.
        result = self._validate(1, 2)
        self.assertFalse(result.ok)
        self.assertIn("FACULTY_UNAVAILABLE",
                      [f.code for f in result.failures])
        self.assertIn("A", {f.details.get("swap_side")
                            for f in result.failures})

    def test_side_a_failure_leaves_both_unchanged(self):
        from backend import faculty_swaps as fs
        f2 = self.m.Faculty.query.get(2)
        f2.unavailable_slots = "Mon:0"
        self.m.db.session.commit()
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(1, 2)
        self.assertEqual(self._state(), before)

    def test_side_b_unavailable_rejects(self):
        from backend import faculty_swaps as fs
        f1 = self.m.Faculty.query.get(1)
        f1.unavailable_slots = "Wed:0"
        self.m.db.session.commit()
        # Side B: A5 (Wed P0) under F1 hits Wed P0; side A stays valid.
        result = self._validate(1, 5)
        self.assertFalse(result.ok)
        codes = [(f.code, f.details.get("swap_side"))
                 for f in result.failures]
        self.assertIn(("FACULTY_UNAVAILABLE", "B"), codes)
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(1, 5)
        self.assertEqual(self._state(), before)


# ------------------------------------------------------- conflict H6
class TestFacultyConflict(SwapTestBase):
    def _seed_a7(self):
        # A7 (F2, S2) Mon P0: overlaps A1 in time, not faculty/group.
        self.m.db.session.add(self.m.TeachingAssignment(
            id=7, faculty_id=2, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        self._place(9, 7, "Mon", 0, 1, 2)

    def _seed_a9b(self):
        # A9 (F3, S2) Wed P1 R102: valid seed (S2 Wed P0+P1 run 2).
        self.m.db.session.add(self.m.TeachingAssignment(
            id=9, faculty_id=3, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        self._place(9, 9, "Wed", 1, 1, 2)

    def test_side_a_conflict_rejects(self):
        from backend import faculty_swaps as fs
        self._seed_a7()
        result = self._validate(1, 2)
        self.assertFalse(result.ok)
        conflicts = [f for f in result.failures
                     if f.code == "FACULTY_CONFLICT"]
        self.assertTrue(conflicts)
        self.assertEqual(conflicts[0].details.get("swap_side"), "A")
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(1, 2)
        self.assertEqual(self._state(), before)

    def test_side_b_conflict_carries_context(self):
        from backend import faculty_swaps as fs
        self._seed_a9b()
        # swap(5, 2): side B = A2 (Mon P4, Wed P1) under F3 hits A9 Wed P1.
        result = self._validate(5, 2)
        self.assertFalse(result.ok)
        conflicts = [f for f in result.failures
                     if f.code == "FACULTY_CONFLICT"]
        self.assertTrue(conflicts)
        det = conflicts[0].details
        self.assertEqual(det.get("swap_side"), "B")
        self.assertIn("conflicting_class_id", det)
        self.assertIn("conflicting_assignment_id", det)
        self.assertEqual(det.get("target_faculty_id"), 3)
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(5, 2)
        self.assertEqual(self._state(), before)


# ------------------------------------------------------- consecutive H12
class TestConsecutive(SwapTestBase):
    def _seed_f3_run(self):
        # F3 Mon P2+P3 (S2): A1 Mon P0+P1 incoming gives a run of 4.
        self.m.db.session.add(self.m.TeachingAssignment(
            id=12, faculty_id=3, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=2, block_length=1))
        self.m.db.session.commit()
        self._place(10, 12, "Mon", 2, 1, 2)
        self._place(11, 12, "Mon", 3, 1, 2)

    def _seed_f1_run(self):
        # F1 Tue P2+P3 (S1): A4 Tue P0-1 incoming gives a run of 4.
        self.m.db.session.add(self.m.TeachingAssignment(
            id=14, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=2, block_length=1))
        self.m.db.session.commit()
        self._place(10, 14, "Tue", 2, 1, 1)
        self._place(11, 14, "Tue", 3, 1, 1)

    def test_consecutive_side_a_rolls_back(self):
        from backend import faculty_swaps as fs
        self._seed_f3_run()
        result = self._validate(1, 5)
        self.assertFalse(result.ok)
        consec = [f for f in result.failures
                  if f.code == "FACULTY_CONSECUTIVE"]
        self.assertTrue(consec)
        self.assertEqual(consec[0].details.get("swap_side"), "A")
        before = self._state()
        with self.assertRaises(fs.FacultySwapError) as cm:
            self._swap(1, 5)
        self.assertIn("FACULTY_CONSECUTIVE", self._codes(cm.exception))
        self.assertEqual(self._state(), before)

    def test_consecutive_side_b_rolls_back(self):
        from backend import faculty_swaps as fs
        self._seed_f1_run()
        # swap(3, 4): side B = A4 (Tue P0-1) under F1 joins Tue P2+P3.
        result = self._validate(3, 4)
        self.assertFalse(result.ok)
        consec = [f for f in result.failures
                  if f.code == "FACULTY_CONSECUTIVE"]
        self.assertTrue(consec)
        self.assertEqual(consec[0].details.get("swap_side"), "B")
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(3, 4)
        self.assertEqual(self._state(), before)


# ------------------------------------------------------- locked
class TestLocked(SwapTestBase):
    def test_a_locked_rejects(self):
        from backend import faculty_swaps as fs
        self._lock_assignment_1()
        with self.assertRaises(fs.FacultySwapError) as cm:
            self._validate(1, 5)
        self.assertIn("LOCKED_BLOCK", self._codes(cm.exception))

    def test_a_locked_leaves_both_unchanged(self):
        from backend import faculty_swaps as fs
        self._lock_assignment_1()
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(1, 5)
        self.assertEqual(self._state(), before)
        self.assertEqual(self._faculty_of(5), 3)

    def test_b_locked_rejects(self):
        from backend import faculty_swaps as fs
        self._lock_assignment_1()
        before = self._state()
        # A1 is now side B.
        with self.assertRaises(fs.FacultySwapError) as cm:
            self._swap(5, 1)
        self.assertIn("LOCKED_BLOCK", self._codes(cm.exception))
        self.assertEqual(cm.exception.failures[0].details.get("swap_side"),
                         "B")
        self.assertEqual(self._state(), before)

    def test_b_locked_block_without_class_flag_rejects(self):
        from backend import faculty_swaps as fs
        lb = self.m.LockedBlock(
            kind="interdepartment", assignment_id=5, subject_id=1,
            faculty_id=3, section_id=2, day="Wed", start_period=0,
            length=1, room_id=2, room_locked=True)
        self.m.db.session.add(lb)
        self.m.db.session.commit()
        before = self._state()
        with self.assertRaises(fs.FacultySwapError) as cm:
            self._swap(1, 5)
        self.assertIn("LOCKED_BLOCK", self._codes(cm.exception))
        self.assertEqual(self._state(), before)


# ------------------------------------------------------- specializations
class TestSpecialization(SwapTestBase):
    def test_valid_spec_swap_slots_unchanged(self):
        specs = self._mk_spec_cohort()  # Cyber(F3)+AI(F2) Tue P2
        cyber_assign = specs["Cyber"][1]
        ai_assign = specs["AI"][1]
        before_slots = self._slot_rows()
        a, b, result = self._swap(cyber_assign.id, ai_assign.id)
        self.assertTrue(result.ok)
        self.assertEqual((a.faculty_id, b.faculty_id), (2, 3))
        self.assertEqual(self._slot_rows(), before_slots)

    def test_spec_unavailable_rejects(self):
        from backend import faculty_swaps as fs
        specs = self._mk_spec_cohort()
        cyber_id = specs["Cyber"][1].id
        ai_id = specs["AI"][1].id
        f2 = self.m.Faculty.query.get(2)
        f2.unavailable_slots = "Tue:2"
        self.m.db.session.commit()
        result = self._validate(cyber_id, ai_id)
        self.assertFalse(result.ok)
        self.assertIn("FACULTY_UNAVAILABLE",
                      [f.code for f in result.failures])
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(cyber_id, ai_id)
        self.assertEqual(self._state(), before)

    def test_spec_conflict_rejects(self):
        from backend import faculty_swaps as fs
        specs = self._mk_spec_cohort()
        cyber_id = specs["Cyber"][1].id
        ai_id = specs["AI"][1].id
        # F2 busy Tue P2 (S2, valid: S2 Tue has A3 P0 only).
        self.m.db.session.add(self.m.TeachingAssignment(
            id=16, faculty_id=2, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        self._place(20, 16, "Tue", 2, 1, 2)
        result = self._validate(cyber_id, ai_id)
        self.assertFalse(result.ok)
        self.assertIn("FACULTY_CONFLICT",
                      [f.code for f in result.failures])
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(cyber_id, ai_id)
        self.assertEqual(self._state(), before)
        self.assertEqual(self._slot_rows(),
                         sorted((s.id, s.specialization_id, s.day,
                                 s.start_period, s.length)
                                for s in
                                self.m.SpecializationSlot.query.all()))

    def test_spec_consecutive_rejects(self):
        from backend import faculty_swaps as fs
        specs = self._mk_spec_cohort()
        cyber_id = specs["Cyber"][1].id
        ai_id = specs["AI"][1].id
        # F2 Tue P3 (S1): A4 P0-1 + P3 run ok pre-swap; +Tue P2 => run 4.
        # S1 Tue P3 theory: P2 is spec theory -> P2,P3 only 2 consec: valid.
        self.m.db.session.add(self.m.TeachingAssignment(
            id=15, faculty_id=2, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        self._place(21, 15, "Tue", 3, 1, 1)
        result = self._validate(cyber_id, ai_id)
        self.assertFalse(result.ok)
        self.assertIn("FACULTY_CONSECUTIVE",
                      [f.code for f in result.failures])
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(cyber_id, ai_id)
        self.assertEqual(self._state(), before)

    def test_normal_spec_swap_rejected(self):
        from backend import faculty_swaps as fs
        specs = self._mk_spec_cohort()
        cyber_id = specs["Cyber"][1].id
        before = self._state()
        with self.assertRaises(fs.FacultySwapError) as cm:
            self._validate(1, cyber_id)
        self.assertIn("SPECIALIZATION_SWAP", self._codes(cm.exception))
        with self.assertRaises(fs.FacultySwapError):
            self._swap(1, cyber_id)
        with self.assertRaises(fs.FacultySwapError):
            self._swap(cyber_id, 1)
        self.assertEqual(self._state(), before)
        self.assertEqual(self._faculty_of(1), 1)


# ------------------------------------------------------- weekly load
class TestWeeklyLoad(SwapTestBase):
    def test_load_math_no_warnings(self):
        # F1: 8 (A1=5 + A3=3); F3: 3 (A5=3).
        # After swap(1, 5): F1 = 8-5+3 = 6; F3 = 3-3+5 = 5.
        _a, _b, result = self._swap(1, 5)
        self.assertTrue(result.ok)
        self.assertEqual(result.warnings, [])

    def test_overload_warns_but_succeeds(self):
        # swap(1, 6): F4 (max 3, load 2) gains A1 (5): 2-2+5 = 5 > 3.
        # F1: 8-5+2 = 5 <= 24 (no warning).
        a, b, result = self._swap(1, 6)
        self.assertTrue(result.ok)
        self.assertEqual((a.faculty_id, b.faculty_id), (4, 1))
        self.assertEqual(len(result.warnings), 1)
        warn = result.warnings[0]
        self.assertTrue(warn.get("exceeded"))
        self.assertEqual(warn.get("faculty_id"), 4)
        self.assertEqual(warn.get("previous_load"), 2)
        self.assertEqual(warn.get("assignment_load_out"), 2)
        self.assertEqual(warn.get("assignment_load_in"), 5)
        self.assertEqual(warn.get("resulting_load"), 5)
        self.assertEqual(warn.get("max_hours"), 3)


# ------------------------------------------------------- multiple classes
class TestMultipleClasses(SwapTestBase):
    def test_final_placement_failure_rolls_back(self):
        from backend import faculty_swaps as fs
        f1 = self.m.Faculty.query.get(1)
        f1.unavailable_slots = "Wed:1"
        self.m.db.session.commit()
        # Side B = A2 (Mon P4, Wed P1) under F1: fails on the LAST class.
        result = self._validate(1, 2)
        self.assertFalse(result.ok)
        sc_ids = {f.details.get("scheduled_class_id")
                  for f in result.failures}
        self.assertIn(7, sc_ids)
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(1, 2)
        self.assertEqual(self._state(), before)

    def test_both_sides_cover_all_classes(self):
        result = self._validate(1, 2)
        self.assertTrue(result.ok)
        self.assertEqual(sorted(result.scheduled_class_ids_a), [1, 2])
        self.assertEqual(sorted(result.scheduled_class_ids_b), [3, 7])


# ------------------------------------------------------- unscheduled
class TestUnscheduled(SwapTestBase):
    def _mk_pair(self):
        self.m.db.session.add(self.m.TeachingAssignment(
            id=7, faculty_id=1, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.add(self.m.TeachingAssignment(
            id=8, faculty_id=2, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=1, block_length=1))
        self.m.db.session.commit()

    def test_both_unscheduled_valid(self):
        self._mk_pair()
        a, b, result = self._swap(7, 8)
        self.assertTrue(result.ok)
        self.assertFalse(result.noop)
        self.assertEqual((a.faculty_id, b.faculty_id), (2, 1))

    def test_scheduled_unscheduled_valid(self):
        self._mk_pair()
        # Side A = A5 (Wed P0) under F1: valid; side B has no classes.
        a, b, result = self._swap(5, 7)
        self.assertTrue(result.ok)
        self.assertEqual((a.faculty_id, b.faculty_id), (1, 3))

    def test_unscheduled_scheduled_valid(self):
        self._mk_pair()
        a, b, result = self._swap(7, 5)
        self.assertTrue(result.ok)
        self.assertEqual((a.faculty_id, b.faculty_id), (3, 1))


# ------------------------------------------------------- same-period A/B
class TestSamePeriodOverlap(SwapTestBase):
    def test_overlapping_ab_no_false_conflict(self):
        # A9 (F2, S2) Mon P0 overlaps A1 (F1, S1) Mon P0 in time.
        # Different target faculties post-swap: must NOT conflict.
        self.m.db.session.add(self.m.TeachingAssignment(
            id=9, faculty_id=2, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        self.m.db.session.commit()
        self._place(9, 9, "Mon", 0, 1, 2)
        result = self._validate(1, 9)
        self.assertTrue(result.ok, result.failures)
        a, b, _ = self._swap(1, 9)
        self.assertEqual((a.faculty_id, b.faculty_id), (2, 1))


# ------------------------------------------------------- atomicity
class TestAtomicity(SwapTestBase):
    def test_invalid_a_side_both_unchanged(self):
        from backend import faculty_swaps as fs
        f2 = self.m.Faculty.query.get(2)
        f2.unavailable_slots = "Mon:0"
        self.m.db.session.commit()
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(1, 2)
        self.assertEqual(self._state(), before)

    def test_invalid_b_side_both_unchanged(self):
        from backend import faculty_swaps as fs
        f1 = self.m.Faculty.query.get(1)
        f1.unavailable_slots = "Wed:0"
        self.m.db.session.commit()
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(1, 5)
        # B still Bob's... i.e. A=1 still F1, B=5 still F3: never A=Bob/B=Bob.
        self.assertEqual((self._faculty_of(1), self._faculty_of(5)), (1, 3))
        self.assertEqual(self._state(), before)

    def test_exception_during_mutation_rolls_back(self):
        from backend import faculty_swaps as fs
        before = self._state()
        with mock.patch.object(self.m.db.session, "flush",
                               side_effect=RuntimeError("boom")):
            with self.assertRaises(fs.FacultySwapError):
                self._swap(1, 5)
        self.assertEqual(self._state(), before)

    def test_post_flush_failure_rolls_back(self):
        from backend import faculty_swaps as fs
        from backend import schedule_rules as rules
        before = self._state()
        forced = [rules.RuleResult(ok=False, code="FACULTY_CONFLICT",
                                   message="forced post-flush failure",
                                   details={})]
        with mock.patch.object(fs, "_verify_post_swap",
                               return_value=forced):
            with self.assertRaises(fs.FacultySwapError):
                self._swap(1, 5)
        self.assertEqual(self._state(), before)


# ------------------------------------------------------- integrity
class TestDatabaseIntegrity(SwapTestBase):
    def test_failed_swap_changes_nothing_anywhere(self):
        from backend import faculty_swaps as fs
        self._mk_spec_cohort()
        self._lock_assignment_1()
        before = self._state()
        with self.assertRaises(fs.FacultySwapError):
            self._swap(1, 5)
        after = self._state()
        self.assertEqual(before, after)
        # No unrelated assignment/faculty/slot drift.
        self.assertEqual(self._faculty_of(2), 2)
        self.assertEqual(self._faculty_of(3), 1)
        self.assertEqual(self._faculty_of(5), 3)


if __name__ == "__main__":
    unittest.main()
