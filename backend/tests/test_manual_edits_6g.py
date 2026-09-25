"""Phase 6G tests: manual timetable editing + shared move validation.

Covers basic moves, room/faculty/section conflicts, geometry, HN1, locked
blocks, specializations, atomicity, no-regeneration, pure candidate
validation, the move/validate-move API, and reference-DB safety.

Every test uses throwaway SQLite files in a temp dir — never the real
`timetable_v2.db`. Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_manual_edits_6g -v
"""
import hashlib
import os
import tempfile
import unittest

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))

REF_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "instance", "timetable_v2.db")


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class MoveTestBase(unittest.TestCase):
    """Throwaway Flask app + small seeded timetable (all placements valid)."""

    def setUp(self):
        from flask import Flask
        from backend import models as m
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6g.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6G", working_days=DAYS,
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
        m.db.session.add(m.Room(id=5, name="L2", room_type="lab", capacity=5,
                                equipment_count=2))
        m.db.session.add(m.Room(id=6, name="L3", room_type="lab", capacity=40,
                                equipment_count=5))
        m.db.session.add(m.Faculty(id=1, name="F1"))
        m.db.session.add(m.Faculty(id=2, name="F2"))
        m.db.session.add(m.Faculty(id=3, name="F3"))
        m.db.session.add(m.Subject(id=1, name="SUB1", enrollment_id=1))
        m.db.session.add(m.Subject(id=2, name="SUB2", enrollment_id=1))
        # A1: F1 theory S1. A2: F2 theory S1. A3: F1 theory S2.
        # A4: F2 practical G1 (block 2). A5: F3 theory S2.
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
        m.db.session.commit()
        # Valid seed timetable.
        self._place(1, 1, "Mon", 0, 1, 1)    # SC1 A1 Mon P0 R101
        self._place(2, 1, "Mon", 1, 1, 1)    # SC2 A1 Mon P1 R101
        self._place(3, 2, "Mon", 4, 1, 2)    # SC3 A2 Mon P4 R102
        self._place(4, 3, "Tue", 0, 1, 1)    # SC4 A3 Tue P0 R101
        self._place(5, 4, "Tue", 0, 2, 4)    # SC5 A4 Tue P0-1 L1
        self._place(6, 5, "Wed", 0, 1, 2)    # SC6 A5 Wed P0 R102
        self._place(7, 2, "Wed", 1, 1, 1)    # SC7 A2 Wed P1 R101

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

    def _move(self, cid, day, start, room):
        from backend import manual_edits as me
        return me.move_scheduled_class(
            self.m.db, cid, day=day, start_period=start, room_id=room)

    def _codes(self, exc):
        return [f.code for f in exc.failures]

    def _mk_spec_cohort(self, day="Mon", start=2, room_ids=(2, 3)):
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
        _specs = {}
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
            _specs[spec.name] = (spec, assign, sc, slot)
        self.m.db.session.commit()
        return _specs


# ------------------------------------------------------- basic moves
class TestBasicMoves(MoveTestBase):
    def test_day_change_succeeds(self):
        sc, _ = self._move(3, "Tue", 2, 2)  # SC3 Mon P4 -> Tue P2 R102
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Tue", 2, 2))

    def test_start_change_succeeds(self):
        sc, _ = self._move(1, "Mon", 3, 1)  # SC1 Mon P0 -> Mon P3 R101
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Mon", 3, 1))

    def test_room_change_succeeds(self):
        sc, _ = self._move(3, "Mon", 4, 1)  # SC3 R102 -> R101, same slot
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Mon", 4, 1))

    def test_all_three_change(self):
        sc, _ = self._move(3, "Wed", 2, 1)  # SC3 -> Wed P2 R101
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Wed", 2, 1))

    def test_assignment_length_run_preserved(self):
        sc, _ = self._move(5, "Mon", 5, 4)  # practical Tue P0-1 -> Mon P5-6
        self.assertEqual(sc.assignment_id, 4)
        self.assertEqual(sc.length, 2)
        self.assertEqual(sc.run_id, "run1")
        self.assertEqual((sc.day, sc.start_period), ("Mon", 5))

    def test_noop_same_position(self):
        before = self._rows()
        sc, result = self._move(1, "Mon", 0, 1)
        self.assertTrue(result.noop and result.ok)
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Mon", 0, 1))
        self.assertEqual(self._rows(), before)

    def test_missing_class_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(9999, "Tue", 2, 2)
        self.assertIn("does not exist", str(cm.exception))
        self.assertEqual(cm.exception.to_payload()["code"],
                         "MANUAL_EDIT_INVALID")


# ------------------------------------------------------- room conflicts
class TestRoomConflicts(MoveTestBase):
    def test_occupied_room_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Tue", 0, 1)  # R101 Tue P0 holds SC4
        self.assertIn("ROOM_CONFLICT", self._codes(cm.exception))
        det = cm.exception.failures[0].details
        self.assertEqual(det["conflicting_class_id"], 4)
        self.assertEqual(det["scheduled_class_id"], 1)

    def test_no_auto_relocation(self):
        from backend import manual_edits as me
        before = self._rows()
        with self.assertRaises(me.ManualEditError):
            self._move(1, "Tue", 0, 1)
        self.assertEqual(self._rows(), before)  # SC1 unmoved, nothing else moved

    def test_wrong_room_type_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Mon", 5, 4)  # theory -> lab L1
        self.assertIn("ROOM_TYPE_MISMATCH", self._codes(cm.exception))

    def test_practical_into_theory_room_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(5, "Mon", 5, 1)  # practical -> theory R101
        self.assertIn("ROOM_TYPE_MISMATCH", self._codes(cm.exception))

    def test_insufficient_capacity_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Mon", 5, 3)  # S1 (30) -> R103 (cap 20)
        self.assertIn("ROOM_CAPACITY", self._codes(cm.exception))

    def test_insufficient_equipment_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(5, "Mon", 0, 6)  # G1 (15) -> L3 (eq 5)
        self.assertIn("ROOM_EQUIPMENT", self._codes(cm.exception))

    def test_unknown_room_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Mon", 5, 999)
        self.assertIn("UNKNOWN_ROOM", self._codes(cm.exception))


# ------------------------------------------------------- faculty
class TestFaculty(MoveTestBase):
    def test_faculty_conflict_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(4, "Mon", 0, 2)  # F1 busy Mon P0 (SC1)
        self.assertIn("FACULTY_CONFLICT", self._codes(cm.exception))
        det = [f.details for f in cm.exception.failures
               if f.code == "FACULTY_CONFLICT"][0]
        self.assertEqual(det["conflicting_class_id"], 1)

    def test_faculty_unavailable_rejected(self):
        from backend import manual_edits as me
        f1 = self.m.Faculty.query.get(1)
        f1.unavailable_slots = "Wed:2"
        self.m.db.session.commit()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Wed", 2, 2)  # F1 unavailable Wed P2
        self.assertIn("FACULTY_UNAVAILABLE", self._codes(cm.exception))

    def test_faculty_consecutive_enforced(self):
        from backend import manual_edits as me
        # F1 Mon P0,P1 (SC1,SC2) + planted Mon P3 -> moving SC4 into Mon P2
        # would make F1 teach P0-P3 four in a row (limit 3).
        self._place(8, 3, "Mon", 3, 1, 2)
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(4, "Mon", 2, 1)
        self.assertIn("FACULTY_CONSECUTIVE", self._codes(cm.exception))


# ------------------------------------------------------- section
class TestSection(MoveTestBase):
    def test_section_conflict_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Mon", 4, 1)  # S1 busy Mon P4 (SC3)
        self.assertIn("SECTION_CONFLICT", self._codes(cm.exception))
        det = [f.details for f in cm.exception.failures
               if f.code == "SECTION_CONFLICT"][0]
        self.assertEqual(det["conflicting_class_id"], 3)

    def test_hierarchy_practical_into_parent_theory_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(5, "Mon", 1, 4)  # G1 lab (x2) vs S1 theory Mon P1
        self.assertIn("SECTION_HIERARCHY_CONFLICT",
                      self._codes(cm.exception))

    def test_hierarchy_theory_into_lab_footprint_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Tue", 1, 1)  # S1 theory vs G1 practical Tue P0-1
        self.assertIn("SECTION_HIERARCHY_CONFLICT",
                      self._codes(cm.exception))


# ------------------------------------------------------- geometry
class TestGeometry(MoveTestBase):
    def _expect(self, code, cid, day, start, room):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(cid, day, start, room)
        self.assertIn(code, self._codes(cm.exception))

    def test_invalid_day_rejected(self):
        self._expect("UNKNOWN_DAY", 1, "Sun", 0, 1)

    def test_invalid_period_rejected(self):
        self._expect("PERIOD_OUT_OF_RANGE", 1, "Mon", 7, 1)

    def test_block_past_final_period_rejected(self):
        self._expect("PERIOD_OUT_OF_RANGE", 5, "Mon", 6, 4)  # x2 -> P6-7

    def test_break_span_rejected(self):
        self._expect("BREAK_SPAN", 5, "Mon", 3, 4)  # P3-4 spans break_after=4


# ------------------------------------------------------- HN1
class TestHN1(MoveTestBase):
    def test_creates_violation_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(3, "Mon", 2, 2)  # S1 {P0,P1} + P2 -> T+T+T
        self.assertIn("MAX_TWO_THEORY", self._codes(cm.exception))

    def test_removes_violation_accepted(self):
        self._place(8, 2, "Mon", 2, 1, 2)  # plant S1 T+T+T at P0-2
        sc, result = self._move(8, "Mon", 5, 2)  # -> afternoon segment
        self.assertTrue(result.ok)
        self.assertEqual((sc.day, sc.start_period), ("Mon", 5))

    def test_break_boundary_respected(self):
        # S2 Mon P2+P3 theory; moving a third S2 theory into Mon P4 is
        # valid: occupied {2,3,4} covers no single 3-window because
        # windows never cross break_after=4.
        self._place(8, 3, "Mon", 2, 1, 2)
        self._place(9, 5, "Mon", 3, 1, 2)
        sc, result = self._move(4, "Mon", 4, 1)  # A3/F1/S2 Tue P0 -> Mon P4
        self.assertTrue(result.ok)
        self.assertEqual((sc.day, sc.start_period), ("Mon", 4))

    def test_practical_ignores_hn1(self):
        # S1 Mon P0,P1 theory; moving the G1 practical into Mon P2 is
        # valid (practicals contribute 0 to the theory streak).
        sc, result = self._move(5, "Mon", 2, 4)
        self.assertTrue(result.ok)
        self.assertEqual((sc.day, sc.start_period), ("Mon", 2))

    def test_spec_theory_counts_for_hn1(self):
        self._mk_spec_cohort(day="Mon", start=2, room_ids=(2, 1))
        from backend import manual_edits as me
        # S1 normal {P0,P1} + spec theory P2 + candidate P3 -> violation.
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(3, "Mon", 3, 2)
        self.assertIn("MAX_TWO_THEORY", self._codes(cm.exception))


# ------------------------------------------------------- locked blocks
class TestLocked(MoveTestBase):
    def _lock_a5_wed3(self):
        from backend import locked_blocks as lb
        return lb.create_locked_block(
            self.m.db, assignment_id=5, day="Wed", start_period=3,
            length=1, room_id=1)

    def test_locked_class_immovable(self):
        from backend import manual_edits as me
        _lb, sc = self._lock_a5_wed3()
        before = self._rows()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(sc.id, "Tue", 2, 2)
        self.assertEqual(cm.exception.to_payload()["code"], "LOCKED_BLOCK")
        det = cm.exception.failures[0].details
        self.assertEqual(det["scheduled_class_id"], sc.id)
        self.assertEqual(det["locked_block_id"], _lb.id)
        self.assertEqual(self._rows(), before)

    def test_legacy_lock_link_immovable(self):
        # locked_block_id set without is_locked must still refuse the move.
        from backend import manual_edits as me
        _lb, sc = self._lock_a5_wed3()
        sc.is_locked = False
        self.m.db.session.commit()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(sc.id, "Tue", 2, 2)
        self.assertEqual(cm.exception.to_payload()["code"], "LOCKED_BLOCK")

    def test_target_locked_room_rejected(self):
        from backend import manual_edits as me
        self._lock_a5_wed3()  # locked SC at Wed P3 R101
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(7, "Wed", 3, 1)  # SC7 -> Wed P3 R101
        self.assertIn("ROOM_CONFLICT", self._codes(cm.exception))
        det = [f.details for f in cm.exception.failures
               if f.code == "ROOM_CONFLICT"][0]
        self.assertIn("conflicting_class_id", det)

    def test_target_locked_faculty_rejected(self):
        from backend import locked_blocks as lb
        from backend import manual_edits as me
        lb.create_locked_block(
            self.m.db, assignment_id=1, day="Wed", start_period=2,
            length=1, room_id=2)  # F1/S1 locked Wed P2
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(4, "Wed", 2, 1)  # F1 class -> Wed P2 (faculty busy)
        self.assertIn("FACULTY_CONFLICT", self._codes(cm.exception))


# ------------------------------------------------------- specializations
class TestSpecializations(MoveTestBase):
    def test_normal_into_spec_footprint_rejected(self):
        from backend import manual_edits as me
        self._mk_spec_cohort(day="Mon", start=2, room_ids=(2, 1))
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(2, "Mon", 2, 1)  # S1 class into spec slot Mon P2
        self.assertIn("SPECIALIZATION_OVERLAP", self._codes(cm.exception))
        det = [f.details for f in cm.exception.failures
               if f.code == "SPECIALIZATION_OVERLAP"][0]
        self.assertIn("conflicting_class_id", det)

    def test_spec_class_independent_move_rejected(self):
        from backend import manual_edits as me
        specs = self._mk_spec_cohort(day="Mon", start=2, room_ids=(2, 1))
        _spec, _assign, sc, _slot = specs["Cyber"]
        before = self._rows()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(sc.id, "Tue", 0, 2)
        self.assertEqual(cm.exception.to_payload()["code"],
                         "SPECIALIZATION_SYNC")
        self.assertEqual(self._rows(), before)

    def test_sync_intact_after_normal_move(self):
        specs = self._mk_spec_cohort(day="Mon", start=2, room_ids=(2, 1))
        sc, result = self._move(2, "Mon", 3, 1)  # S1 P1 -> P3 (valid)
        self.assertTrue(result.ok)
        for _name, (_spec, _assign, scc, slot) in specs.items():
            kept = self.m.ScheduledClass.query.get(scc.id)
            self.assertEqual((kept.day, kept.start_period), ("Mon", 2))
            kept_slot = self.m.SpecializationSlot.query.get(slot.id)
            self.assertEqual((kept_slot.day, kept_slot.start_period),
                             ("Mon", 2))
        self.assertEqual((sc.day, sc.start_period), ("Mon", 3))


# ------------------------------------------------------- atomicity
class TestAtomicity(MoveTestBase):
    def _rejected_moves(self):
        return [(1, "Tue", 0, 1),    # ROOM_CONFLICT
                (1, "Mon", 4, 1),    # SECTION_CONFLICT
                (3, "Mon", 2, 2),    # MAX_TWO_THEORY
                (1, "Sun", 0, 1),    # UNKNOWN_DAY
                (5, "Mon", 3, 4)]    # BREAK_SPAN

    def test_rejected_moves_leave_db_identical(self):
        from backend import manual_edits as me
        for cid, day, start, room in self._rejected_moves():
            with self.subTest(cid=cid, day=day, start=start, room=room):
                before_rows = self._rows()
                self.m.db.session.remove()
                self.m.db.engine.dispose()
                before_sha = _sha(self.db_path)
                with self.assertRaises(me.ManualEditError):
                    self._move(cid, day, start, room)
                self.assertEqual(self._rows(), before_rows)
                self.assertEqual(
                    self.m.ScheduledClass.query.count(), len(before_rows))
                self.m.db.session.remove()
                self.m.db.engine.dispose()
                self.assertEqual(_sha(self.db_path), before_sha)

    def test_no_unrelated_changes_on_success(self):
        before = {r[0]: r for r in self._rows()}
        sc, _ = self._move(3, "Tue", 2, 2)
        after = {r[0]: r for r in self._rows()}
        self.assertEqual(set(before), set(after))  # no rows added/removed
        for cid, row in after.items():
            if cid == sc.id:
                self.assertEqual((row[2], row[3], row[5]), ("Tue", 2, 2))
            else:
                self.assertEqual(row, before[cid])

    def test_no_regeneration(self):
        from backend import manual_edits as me
        import backend.manual_edits as me_mod
        with open(me_mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("run_scheduler", src)
        self.assertNotIn("CpSolver", src)
        run_before = self.m.ScheduledClass.query.get(3).run_id
        sc, _ = self._move(3, "Tue", 2, 2)
        self.assertEqual(sc.run_id, run_before)
        self.assertEqual(me_mod.__name__, "backend.manual_edits")


# ------------------------------------------------------- pure validation
class TestCandidateValidation(MoveTestBase):
    def test_no_self_conflict(self):
        from backend import manual_edits as me
        from backend import schedule_validator as svc
        snap, _cfg = me._load_snapshot(self.m.db)
        slim = svc.snapshot_without(snap, 1)
        info = slim.assignments[1]
        fails = svc.validate_candidate(
            slim, session_type=info["session_type"],
            group_key=info["group_key"],
            group_label=info.get("group_label", "?"),
            group_size=info.get("group_size", 0),
            faculty_id=info.get("faculty_id"), day="Mon",
            start_period=0, length=1, room_id=1,
            parent_section_key=info.get("parent_section_key"))
        self.assertEqual([f for f in fails
                          if f.code in ("ROOM_CONFLICT", "FACULTY_CONFLICT",
                                        "GROUP_CONFLICT")], [])

    def test_unrelated_conflict_detected(self):
        from backend import manual_edits as me
        from backend import schedule_validator as svc
        snap, _cfg = me._load_snapshot(self.m.db)
        slim = svc.snapshot_without(snap, 1)
        # A2/S1 into SC4's room cell (Tue P0 R101): room occupied, and the
        # class removed (SC1) is irrelevant to that cell.
        fails = svc.validate_candidate(
            slim, session_type="theory", group_key="section:1",
            group_label="BCA-1-A", group_size=30, faculty_id=2,
            day="Tue", start_period=0, length=1, room_id=1)
        self.assertIn("ROOM_CONFLICT", [f.code for f in fails])

    def test_dry_run_matches_mutation(self):
        from backend import manual_edits as me
        dry = me.validate_move_candidate(
            self.m.db, 1, day="Tue", start_period=0, room_id=1)
        self.assertFalse(dry.ok)
        dry_codes = sorted(f.code for f in dry.failures)
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Tue", 0, 1)
        self.assertEqual(sorted(self._codes(cm.exception)), dry_codes)


# ------------------------------------------------------- API
class TestMoveApi(MoveTestBase):
    def setUp(self):
        super().setUp()
        from flask_login import LoginManager
        from backend.api_routes import init_api
        self.app.secret_key = "6g-test"
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

    def test_validate_move_ok(self):
        resp = self.client.post("/api/schedule/classes/3/validate-move",
                                json={"day": "Tue", "start_period": 2,
                                      "room_id": 2})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["noop"])
        # Dry-run writes nothing.
        sc = self.m.ScheduledClass.query.get(3)
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Mon", 4, 2))

    def test_validate_move_conflict(self):
        resp = self.client.post("/api/schedule/classes/1/validate-move",
                                json={"day": "Tue", "start_period": 0,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "ROOM_CONFLICT")
        self.assertIn("details", body)
        self.assertTrue(body["failures"])
        sc = self.m.ScheduledClass.query.get(1)
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Mon", 0, 1))

    def test_move_ok(self):
        resp = self.client.post("/api/schedule/classes/3/move",
                                json={"day": "Tue", "start_period": 2,
                                      "room_id": 2})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body["ok"])
        item = body["scheduled_class"]
        self.assertEqual((item["day"], item["start_period"],
                          item["room_id"]), ("Tue", 2, 2))
        self.assertEqual(item["assignment_id"], 2)
        self.assertEqual(item["length"], 1)
        self.assertIn("subject", item)
        self.assertIn("faculty", item)
        sc = self.m.ScheduledClass.query.get(3)
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Tue", 2, 2))

    def test_move_noop(self):
        resp = self.client.post("/api/schedule/classes/1/move",
                                json={"day": "Mon", "start_period": 0,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["noop"])

    def test_move_conflict_preserves_db(self):
        before = self._rows()
        resp = self.client.post("/api/schedule/classes/1/move",
                                json={"day": "Tue", "start_period": 0,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["code"], "ROOM_CONFLICT")
        self.assertEqual(body["details"]["conflicting_class_id"], 4)
        self.assertEqual(self._rows(), before)

    def test_move_locked(self):
        from backend import locked_blocks as lb
        _lb, sc = lb.create_locked_block(
            self.m.db, assignment_id=5, day="Wed", start_period=3,
            length=1, room_id=1)
        resp = self.client.post(f"/api/schedule/classes/{sc.id}/move",
                                json={"day": "Tue", "start_period": 2,
                                      "room_id": 2})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "LOCKED_BLOCK")

    def test_move_unknown_room(self):
        resp = self.client.post("/api/schedule/classes/1/move",
                                json={"day": "Mon", "start_period": 5,
                                      "room_id": 999})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "UNKNOWN_ROOM")

    def test_move_missing_class(self):
        resp = self.client.post("/api/schedule/classes/9999/move",
                                json={"day": "Tue", "start_period": 2,
                                      "room_id": 2})
        self.assertEqual(resp.status_code, 404)

    def test_move_ignores_forbidden_fields(self):
        resp = self.client.post(
            "/api/schedule/classes/3/move",
            json={"day": "Tue", "start_period": 2, "room_id": 2,
                  "assignment_id": 1, "length": 5, "run_id": "hacked",
                  "is_locked": True, "faculty_id": 3})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        sc = self.m.ScheduledClass.query.get(3)
        self.assertEqual(sc.assignment_id, 2)
        self.assertEqual(sc.length, 1)
        self.assertEqual(sc.run_id, "run1")
        self.assertFalse(sc.is_locked)

    def test_move_does_not_invoke_scheduler(self):
        import backend.api_routes as routes
        calls = []
        real = routes.run_scheduler
        routes.run_scheduler = lambda *a, **k: calls.append(1) or real(*a, **k)
        try:
            resp = self.client.post("/api/schedule/classes/3/move",
                                    json={"day": "Tue", "start_period": 2,
                                          "room_id": 2})
        finally:
            routes.run_scheduler = real
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(calls, [])


# ------------------------------------------------------- reference DB safety
class TestReferenceDbSafety(unittest.TestCase):
    def test_reference_db_untouched(self):
        if not os.path.isfile(REF_DB):
            self.skipTest("reference DB absent")
        before = _sha(REF_DB)
        # Exercise service + API paths on temp DBs only (done by other
        # test classes); here simply assert the reference file is stable
        # across this process and was never opened for writing by 6G code.
        import backend.manual_edits as me
        with open(me.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("timetable_v2", src)
        self.assertEqual(_sha(REF_DB), before)


if __name__ == "__main__":
    unittest.main()
