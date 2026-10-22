"""Phase 6I.3 tests: preferred-room validator / manual-edit integration.

Proves the soft-preference semantics through existing behavior-level
interfaces (`manual_edits.validate_move_candidate` /
`move_scheduled_class`): compatible moves to/from/beside a preferred
room stay valid, every hard room rule still rejects non-preferred
targets, an unusable preference invalidates nothing, locked and
specialization semantics are unchanged, and configuring a preference
never relocates classes. No preference scoring exists in the validator
by design (the scheduler owns desirability).

Every test uses throwaway SQLite files in a temp dir — never the real
database. Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_preferred_room_validator_6i -v
"""
import os
import tempfile
import unittest

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))


class PreferredValidatorBase(unittest.TestCase):
    """Throwaway Flask app + seeded timetable.

    S1 (30 students) prefers R101; S2 has no preference. Seed timetable
    is valid under the hard rules (verified by the passing move tests
    below, which re-validate every placement through the shared layer).
    """

    def setUp(self):
        from flask import Flask
        from backend import models as m
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6i3.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6I3", working_days=DAYS,
                                  periods=PERIODS, break_after_periods=4,
                                  max_consecutive_teaching=3))
        m.db.session.add(m.Program(id=1, name="BCA"))
        m.db.session.add(m.Enrollment(id=1, program_id=1, year_label="Y1",
                                      total_students=60))
        m.db.session.add(m.Section(id=1, enrollment_id=1, name="BCA-1-A",
                                   student_count=30,
                                   preferred_theory_room_id=1))
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
        m.db.session.add(m.Room(id=5, name="L2", room_type="lab", capacity=40,
                                equipment_count=5))
        m.db.session.add(m.Faculty(id=1, name="F1", weekly_max_hours=24))
        m.db.session.add(m.Faculty(id=2, name="F2", weekly_max_hours=24))
        m.db.session.add(m.Faculty(id=3, name="F3", weekly_max_hours=24))
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
        m.db.session.commit()
        # Valid seed timetable (S1 prefers R101).
        self._place(1, 1, "Mon", 0, 1, 1)    # SC1 A1 Mon P0 R101 (preferred)
        self._place(2, 1, "Mon", 1, 1, 1)    # SC2 A1 Mon P1 R101 (preferred)
        self._place(3, 2, "Mon", 4, 1, 2)    # SC3 A2 Mon P4 R102
        self._place(4, 3, "Tue", 0, 1, 1)    # SC4 A3 Tue P0 R101
        self._place(5, 4, "Tue", 0, 2, 4)    # SC5 A4 Tue P0-1 L1

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

    def _codes(self, exc):
        return [f.code for f in exc.failures]

    def _validate(self, cid, day, start, room):
        from backend import manual_edits as me
        return me.validate_move_candidate(
            self.m.db, cid, day=day, start_period=start, room_id=room)

    def _move(self, cid, day, start, room):
        from backend import manual_edits as me
        return me.move_scheduled_class(
            self.m.db, cid, day=day, start_period=start, room_id=room)

    def _lock_sc1(self):
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

    def _mk_spec_cohort(self, day="Tue", start=2):
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
        for spec, assign, room in ((cyber, ca, 2), (ai, aa, 1)):
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


# ------------------------------------------------------- preference moves
class TestPreferredMoves(PreferredValidatorBase):
    def test_move_away_from_preferred_valid(self):
        # S1 prefers R101; R102 is compatible and free at Mon P0.
        result = self._validate(1, "Mon", 0, 2)
        self.assertTrue(result.ok, result.failures)
        sc, _ = self._move(1, "Mon", 0, 2)
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Mon", 0, 2))

    def test_move_into_preferred_valid(self):
        # SC3 sits in R102; R101 (S1's preference) is free at Mon P4.
        result = self._validate(3, "Mon", 4, 1)
        self.assertTrue(result.ok, result.failures)
        sc, _ = self._move(3, "Mon", 4, 1)
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Mon", 4, 1))

    def test_configuring_preference_relocates_nothing(self):
        before = self._rows()
        sec = self.m.Section.query.get(1)
        sec.preferred_theory_room_id = 2
        self.m.db.session.commit()
        # Preference changed; every placement byte-identical, no moves.
        self.assertEqual(self._rows(), before)
        self.assertEqual(
            self.m.Section.query.get(1).preferred_theory_room_id, 2)


# ------------------------------------------------------- hard rules hold
class TestHardRulesHold(PreferredValidatorBase):
    def test_capacity_still_rejects(self):
        from backend import manual_edits as me
        before = self._rows()
        # R103 holds 20 < 30 students, preferred room notwithstanding.
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Mon", 0, 3)
        self.assertIn("ROOM_CAPACITY", self._codes(cm.exception))
        self.assertEqual(self._rows(), before)

    def test_room_type_still_rejects(self):
        from backend import manual_edits as me
        before = self._rows()
        # Theory class into lab L1.
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Mon", 0, 4)
        self.assertIn("ROOM_TYPE_MISMATCH", self._codes(cm.exception))
        self.assertEqual(self._rows(), before)

    def test_equipment_still_rejects(self):
        from backend import manual_edits as me
        before = self._rows()
        # Practical (15 students) into L2 with only 5 equipment.
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(5, "Tue", 0, 5)
        self.assertIn("ROOM_EQUIPMENT", self._codes(cm.exception))
        self.assertEqual(self._rows(), before)

    def test_occupancy_still_rejects(self):
        from backend import manual_edits as me
        before = self._rows()
        # R102 Mon P4 is taken by SC3.
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Mon", 4, 2)
        self.assertIn("ROOM_CONFLICT", self._codes(cm.exception))
        det = cm.exception.failures[0].details
        self.assertEqual(det.get("conflicting_class_id"), 3)
        self.assertEqual(self._rows(), before)

    def test_locked_room_conflict_unchanged(self):
        from backend import manual_edits as me
        self._lock_sc1()  # SC1 pins R101 Mon P0 as a hard fact.
        before = self._rows()
        # Unlocked SC3 cannot take the locked room: ordinary occupancy.
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(3, "Mon", 0, 1)
        self.assertIn("ROOM_CONFLICT", self._codes(cm.exception))
        self.assertEqual(
            cm.exception.failures[0].details.get("conflicting_class_id"), 1)
        self.assertEqual(self._rows(), before)


# ------------------------------------------------------- unusable preference
class TestUnusablePreference(PreferredValidatorBase):
    def test_dangling_preference_invalidates_nothing(self):
        sec = self.m.Section.query.get(1)
        sec.preferred_theory_room_id = 999  # deleted/nonexistent room
        self.m.db.session.commit()
        # Ordinary moves validate exactly as before; no auto-repair.
        result = self._validate(2, "Mon", 2, 1)
        self.assertTrue(result.ok, result.failures)
        noop = self._validate(1, "Mon", 0, 1)
        self.assertTrue(noop.ok and noop.noop)
        self.assertEqual(
            self.m.Section.query.get(1).preferred_theory_room_id, 999)

    def test_preferred_status_never_bypasses_hard_rules(self):
        from backend import manual_edits as me
        sec = self.m.Section.query.get(1)
        sec.preferred_theory_room_id = 4  # lab L1: incompatible w/ theory
        self.m.db.session.commit()
        before = self._rows()
        # Explicitly targeting the (incompatible) preferred room still fails.
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Mon", 0, 4)
        self.assertIn("ROOM_TYPE_MISMATCH", self._codes(cm.exception))
        self.assertEqual(self._rows(), before)


# ------------------------------------------------------- locks and specs
class TestLocksAndSpecs(PreferredValidatorBase):
    def test_locked_nonpreferred_class_stays_locked(self):
        from backend import manual_edits as me
        # S1 prefers R102 now, but SC1 is locked in R101: the lock (a hard
        # fact) dominates; the class is neither invalidated nor moved.
        sec = self.m.Section.query.get(1)
        sec.preferred_theory_room_id = 2
        self.m.db.session.commit()
        lb = self._lock_sc1()
        before = self._rows()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Mon", 0, 2)
        self.assertIn("LOCKED_BLOCK", self._codes(cm.exception))
        self.assertEqual(self._rows(), before)
        kept = self.m.ScheduledClass.query.get(1)
        self.assertTrue(kept.is_locked)
        self.assertEqual(kept.locked_block_id, lb.id)
        self.assertEqual((kept.day, kept.start_period, kept.room_id),
                         ("Mon", 0, 1))

    def test_specialization_move_still_refused(self):
        from backend import manual_edits as me
        specs = self._mk_spec_cohort()
        _spec, _assign, sc, _slot = specs["Cyber"]
        slots_before = sorted(
            (s.specialization_id, s.day, s.start_period, s.length)
            for s in self.m.SpecializationSlot.query.all())
        before = self._rows()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(sc.id, "Tue", 3, 2)
        self.assertIn("SPECIALIZATION_SYNC", self._codes(cm.exception))
        self.assertEqual(self._rows(), before)
        self.assertEqual(slots_before, sorted(
            (s.specialization_id, s.day, s.start_period, s.length)
            for s in self.m.SpecializationSlot.query.all()))

    def test_normal_move_beside_specialization_slots(self):
        # Cohort occupies Tue P2; an ordinary Mon move is unaffected.
        self._mk_spec_cohort()
        result = self._validate(2, "Mon", 2, 1)
        self.assertTrue(result.ok, result.failures)


if __name__ == "__main__":
    unittest.main()
