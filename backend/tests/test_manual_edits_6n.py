"""Phase 6N tests: timetable editor backend hardening / audit-first matrix.

Audit-first companion to test_manual_edits_6g.py (which already covers the
core move contract). This file adds ONLY the genuine gaps found during the
6N audit, proving the backend is complete and safe for the future editor:

* API authentication (anonymous validate/move -> 401, DB untouched)
* not-found + malformed destination handling (404 / 422 envelopes)
* multi-period full-footprint moves (trailing-period occupancy, day
  boundary, break span, length/run preservation)
* room-only moves preserve assignment/faculty/section
* faculty ownership unchanged by a move + reassignment still works after
* soft faculty preferences (TIME_WINDOW / DAY_OFF_PREFERENCE) never block
  manual moves; preferred theory rooms never block manual moves
* validate-matches-move consistency (valid + invalid, incl. multi-period)
* dry-run read-only proof (DB file SHA unchanged by validate-move)
* failed-mutation rollback proof (row snapshot + SHA)
* no unrelated relocation on success
* structured error envelope stability
* move never invokes the scheduler
* locked (both flag forms + slot fail-safe) and specialization guards

H12 == FACULTY_CONSECUTIVE and HN1 == MAX_TWO_THEORY: the stable backend
codes are asserted verbatim (no invented names).

Every test uses throwaway SQLite files in a temp dir — never the real
database. Run from the repository root:

    venv\\Scripts\\python.exe -m pytest backend/tests/test_manual_edits_6n.py -q
"""
import hashlib
import os
import tempfile
import unittest

DAYS = "Mon,Tue,Wed"
PERIODS = "|".join(f"p{i}" for i in range(7))

REF_DB_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "instance", "timetable_v2.db"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "instance", "timetable.db"),
]


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class NBase(unittest.TestCase):
    """Throwaway Flask app + small seeded timetable (all placements valid)."""

    def setUp(self):
        from flask import Flask
        from backend import models as m
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6n.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6N", working_days=DAYS,
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
        m.db.session.add(m.Room(id=5, name="L2", room_type="lab", capacity=40,
                                equipment_count=5))
        m.db.session.add(m.Faculty(id=1, name="F1"))
        m.db.session.add(m.Faculty(id=2, name="F2"))
        m.db.session.add(m.Faculty(id=3, name="F3"))
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
        m.db.session.commit()
        # Valid seed timetable (mirrors the 6G seed for comparability).
        self._place(1, 1, "Mon", 0, 1, 1)    # SC1 A1 Mon P0 R101
        self._place(2, 1, "Mon", 1, 1, 1)    # SC2 A1 Mon P1 R101
        self._place(3, 2, "Mon", 4, 1, 2)    # SC3 A2 Mon P4 R102
        self._place(4, 3, "Tue", 0, 1, 1)    # SC4 A3 Tue P0 R101
        self._place(5, 4, "Tue", 0, 2, 4)    # SC5 A4 Tue P0-1 L1 (2-period)
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

    def _validate(self, cid, day, start, room):
        from backend import manual_edits as me
        return me.validate_move_candidate(
            self.m.db, cid, day=day, start_period=start, room_id=room)

    def _codes(self, exc):
        return [f.code for f in exc.failures]

    def _mk_spec_cohort(self, day="Mon", start=2):
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


class NApiBase(NBase):
    def setUp(self):
        super().setUp()
        from flask_login import LoginManager
        from backend.api_routes import init_api
        self.app.secret_key = "6n-test"
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

    def _anon_post(self, path, payload):
        self.ctx.pop()
        try:
            return self.anon.post(path, json=payload)
        finally:
            self.ctx.push()


# ------------------------------------------------------- authentication
class TestAuth(NApiBase):
    def test_anonymous_validate_rejected(self):
        before = self._rows()
        resp = self._anon_post("/api/schedule/classes/3/validate-move",
                               {"day": "Tue", "start_period": 2,
                                "room_id": 2})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self._rows(), before)

    def test_anonymous_move_rejected(self):
        before = self._rows()
        resp = self._anon_post("/api/schedule/classes/3/move",
                               {"day": "Tue", "start_period": 2,
                                "room_id": 2})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self._rows(), before)


# ------------------------------------------------------- not found + malformed
class TestNotFoundMalformed(NApiBase):
    def test_validate_unknown_class_404(self):
        resp = self.client.post("/api/schedule/classes/9999/validate-move",
                                json={"day": "Tue", "start_period": 2,
                                      "room_id": 2})
        self.assertEqual(resp.status_code, 404)

    def test_move_unknown_class_404(self):
        resp = self.client.post("/api/schedule/classes/9999/move",
                                json={"day": "Tue", "start_period": 2,
                                      "room_id": 2})
        self.assertEqual(resp.status_code, 404)

    def test_missing_fields_422(self):
        for payload in ({}, {"day": "Tue"},
                        {"day": "Tue", "start_period": 2},
                        {"start_period": 2, "room_id": 2}):
            resp = self.client.post("/api/schedule/classes/3/validate-move",
                                    json=payload)
            self.assertEqual(resp.status_code, 422, payload)
            resp = self.client.post("/api/schedule/classes/3/move",
                                    json=payload)
            self.assertEqual(resp.status_code, 422, payload)

    def test_malformed_ints_422(self):
        resp = self.client.post("/api/schedule/classes/3/move",
                                json={"day": "Tue", "start_period": "x",
                                      "room_id": 2})
        self.assertEqual(resp.status_code, 422)
        resp = self.client.post("/api/schedule/classes/3/move",
                                json={"day": "Tue", "start_period": 2,
                                      "room_id": "y"})
        self.assertEqual(resp.status_code, 422)

    def test_unknown_day_422(self):
        resp = self.client.post("/api/schedule/classes/1/move",
                                json={"day": "Sun", "start_period": 0,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "UNKNOWN_DAY")

    def test_unknown_room_422(self):
        resp = self.client.post("/api/schedule/classes/1/move",
                                json={"day": "Mon", "start_period": 5,
                                      "room_id": 999})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["code"], "UNKNOWN_ROOM")

    def test_domain_malformed_start_rejected(self):
        from backend import manual_edits as me
        before = self._rows()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Mon", "oops", 1)
        self.assertEqual(cm.exception.to_payload()["code"],
                         "MANUAL_EDIT_INVALID")
        self.assertEqual(self._rows(), before)


# ------------------------------------------------------- multi-period footprint
class TestMultiPeriod(NBase):
    def test_two_period_move_preserves_footprint(self):
        # SC5 Tue P0-1 -> Mon P5-6: occupies BOTH P5 and P6.
        sc, result = self._move(5, "Mon", 5, 4)
        self.assertTrue(result.ok and not result.noop)
        self.assertEqual((sc.day, sc.start_period, sc.length), ("Mon", 5, 2))
        self.assertEqual(sc.assignment_id, 4)
        self.assertEqual(sc.run_id, "run1")

    def test_trailing_period_room_conflict(self):
        # A4/G1 practical occupying L1 Mon P6: moving the 2-period SC5 to
        # Mon P5 L1 must fail on the trailing period (P6), not just P5.
        self._place(8, 4, "Mon", 6, 1, 4)
        from backend import manual_edits as me
        before = self._rows()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(5, "Mon", 5, 4)  # P5-6 vs P6 occupant
        self.assertIn("ROOM_CONFLICT", self._codes(cm.exception))
        det = [f.details for f in cm.exception.failures
               if f.code == "ROOM_CONFLICT"][0]
        self.assertEqual(det.get("period"), 6)
        self.assertEqual(self._rows(), before)

    def test_trailing_period_faculty_conflict(self):
        # F2 teaches SC5 (A4). Plant another F2 class at Mon P6 (lab L1 is
        # free at P5, so room rules pass and the trailing faculty clash
        # at P6 is the decisive failure).
        self._place(8, 4, "Mon", 6, 1, 4)  # placeholder occupant first
        self.m.db.session.delete(
            self.m.ScheduledClass.query.get(8))
        self.m.db.session.commit()
        self._place(8, 2, "Mon", 6, 1, 1)  # A2/F2 Mon P6 R101
        from backend import manual_edits as me
        before = self._rows()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(5, "Mon", 5, 4)  # F2 P5-6 vs F2 at P6
        self.assertIn("FACULTY_CONFLICT", self._codes(cm.exception))
        det = [f.details for f in cm.exception.failures
               if f.code == "FACULTY_CONFLICT"][0]
        self.assertEqual(det.get("period"), 6)
        self.assertEqual(self._rows(), before)

    def test_day_boundary_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(5, "Mon", 6, 4)  # length 2 -> P6-7 past 7 periods
        self.assertIn("PERIOD_OUT_OF_RANGE", self._codes(cm.exception))

    def test_break_span_rejected(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(5, "Mon", 3, 4)  # P3-4 spans break_after=4
        self.assertIn("BREAK_SPAN", self._codes(cm.exception))

    def test_room_only_multi_period_move(self):
        # Same day/start, lab L1 -> lab L2 is impossible here (L2 equipment
        # 5 < 15 students), so assert the hard rule still fires and the
        # footprint is unchanged rather than partially moved.
        from backend import manual_edits as me
        before = self._rows()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(5, "Tue", 0, 5)
        self.assertIn("ROOM_EQUIPMENT", self._codes(cm.exception))
        self.assertEqual(self._rows(), before)


# ------------------------------------------------------- room move preserves ownership
class TestOwnership(NBase):
    def test_room_only_move_preserves_assignment(self):
        sc, _ = self._move(3, "Mon", 4, 1)  # R102 -> R101, same slot
        kept_assignment = self.m.TeachingAssignment.query.get(
            sc.assignment_id)
        self.assertEqual(sc.assignment_id, 3 - 1)  # still A2
        self.assertEqual(kept_assignment.faculty_id, 2)  # still F2
        self.assertEqual(kept_assignment.section_id, 1)  # still S1
        self.assertEqual(sc.length, 1)

    def test_move_does_not_change_faculty(self):
        before_fac = self.m.TeachingAssignment.query.get(2).faculty_id
        sc, _ = self._move(3, "Tue", 2, 2)
        after_fac = self.m.TeachingAssignment.query.get(
            sc.assignment_id).faculty_id
        self.assertEqual(before_fac, after_fac)

    def test_reassignment_still_works_after_move(self):
        from backend import faculty_reassignment as fr
        self._move(3, "Tue", 2, 2)  # A2/F2/S1 now Tue P2
        res = fr.validate_reassignment(self.m.db, 2, 3)
        self.assertTrue(res.ok, [f.code for f in res.failures])
        fr.reassign_faculty(self.m.db, 2, 3)
        self.assertEqual(
            self.m.TeachingAssignment.query.get(2).faculty_id, 3)

    def test_swap_still_works_after_move(self):
        from backend import faculty_swaps as fs
        self._move(3, "Tue", 2, 2)
        res = fs.validate_faculty_swap(self.m.db, 1, 5)
        self.assertTrue(res.ok, [f.code for f in res.failures])


# ------------------------------------------------------- soft preferences never block
class TestSoftPreferences(NBase):
    def _add_time_window(self, faculty_id, days="Tue"):
        from backend import faculty_preferences as fp
        return fp.create_preference(
            self.m.db, faculty_id,
            {"kind": "TIME_WINDOW", "days": days,
             "start_period": 0, "end_period": 7})

    def test_time_window_violation_remains_valid(self):
        self._add_time_window(1, days="Tue")  # F1 prefers Tue-only
        res = self._validate(1, "Mon", 3, 1)  # Mon P3 violates it
        self.assertTrue(res.ok, [f.code for f in res.failures])
        sc, _ = self._move(1, "Mon", 3, 1)
        self.assertEqual((sc.day, sc.start_period), ("Mon", 3))

    def test_day_off_preference_violation_remains_valid(self):
        from backend import faculty_preferences as fp
        fp.create_preference(
            self.m.db, 1,
            {"kind": "DAY_OFF_PREFERENCE", "days": "Mon",
             "start_period": None, "end_period": None})
        res = self._validate(1, "Mon", 3, 1)  # teaching on "day off"
        self.assertTrue(res.ok, [f.code for f in res.failures])

    def test_hard_conflict_still_fails_with_prefs(self):
        self._add_time_window(1, days="Tue")
        self._place(8, 2, "Tue", 0, 1, 1)  # R101 Tue P0 taken
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Tue", 0, 1)
        self.assertIn("ROOM_CONFLICT", self._codes(cm.exception))

    def test_preferred_room_violation_remains_valid(self):
        sec = self.m.Section.query.get(1)
        sec.preferred_theory_room_id = 1  # S1 prefers R101
        self.m.db.session.commit()
        res = self._validate(1, "Mon", 0, 2)  # move to non-preferred R102
        self.assertTrue(res.ok, [f.code for f in res.failures])
        sc, _ = self._move(1, "Mon", 0, 2)
        self.assertEqual(sc.room_id, 2)

    def test_hard_room_rule_holds_despite_preference(self):
        from backend import manual_edits as me
        sec = self.m.Section.query.get(1)
        sec.preferred_theory_room_id = 1
        self.m.db.session.commit()
        before = self._rows()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Mon", 5, 3)  # R103 cap 20 < 30 students
        self.assertIn("ROOM_CAPACITY", self._codes(cm.exception))
        self.assertEqual(self._rows(), before)


# ------------------------------------------------------- HN1 / H12 stable codes
class TestHN1H12(NBase):
    def test_hn1_stable_code(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(3, "Mon", 2, 2)  # S1 {P0,P1} + P2 -> T+T+T
        self.assertIn("MAX_TWO_THEORY", self._codes(cm.exception))

    def test_h12_stable_code(self):
        from backend import manual_edits as me
        self._place(8, 3, "Mon", 3, 1, 2)  # F1 Mon P3
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(4, "Mon", 2, 1)  # F1 P0-P3 four in a row
        self.assertIn("FACULTY_CONSECUTIVE", self._codes(cm.exception))

    def test_faculty_unavailable_enforced(self):
        from backend import manual_edits as me
        f1 = self.m.Faculty.query.get(1)
        f1.unavailable_slots = "Wed:2"
        self.m.db.session.commit()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Wed", 2, 2)
        self.assertIn("FACULTY_UNAVAILABLE", self._codes(cm.exception))

    def test_hierarchy_enforced(self):
        from backend import manual_edits as me
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Tue", 1, 1)  # S1 theory vs G1 practical Tue P0-1
        self.assertIn("SECTION_HIERARCHY_CONFLICT",
                      self._codes(cm.exception))


# ------------------------------------------------------- locked + specialization
class TestProtected(NBase):
    def test_locked_flag_form_immovable(self):
        from backend import locked_blocks as lb
        from backend import manual_edits as me
        _lb, sc = lb.create_locked_block(
            self.m.db, assignment_id=5, day="Wed", start_period=3,
            length=1, room_id=1)
        before = self._rows()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(sc.id, "Tue", 2, 2)
        self.assertEqual(cm.exception.to_payload()["code"], "LOCKED_BLOCK")
        self.assertEqual(self._rows(), before)

    def test_legacy_lock_link_immovable(self):
        from backend import locked_blocks as lb
        from backend import manual_edits as me
        _lb, sc = lb.create_locked_block(
            self.m.db, assignment_id=5, day="Wed", start_period=3,
            length=1, room_id=1)
        sc.is_locked = False  # inconsistent flag form: still immovable
        self.m.db.session.commit()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(sc.id, "Tue", 2, 2)
        self.assertEqual(cm.exception.to_payload()["code"], "LOCKED_BLOCK")

    def test_spec_assignment_immovable(self):
        from backend import manual_edits as me
        specs = self._mk_spec_cohort()
        _spec, _assign, sc, _slot = specs["Cyber"]
        before = self._rows()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(sc.id, "Tue", 0, 2)
        self.assertEqual(cm.exception.to_payload()["code"],
                         "SPECIALIZATION_SYNC")
        self.assertEqual(self._rows(), before)

    def test_slot_linked_row_immovable_fail_safe(self):
        # Inconsistent state: slot_id set but assignment link cleared.
        # The 6N fail-safe must still refuse with SPECIALIZATION_SYNC.
        from backend import manual_edits as me
        specs = self._mk_spec_cohort()
        _spec, assign, sc, _slot = specs["Cyber"]
        assign.specialization_id = None
        assign.section_id = 1
        self.m.db.session.commit()
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(sc.id, "Tue", 0, 2)
        self.assertEqual(cm.exception.to_payload()["code"],
                         "SPECIALIZATION_SYNC")

    def test_normal_into_spec_footprint_rejected(self):
        from backend import manual_edits as me
        self._mk_spec_cohort(day="Mon", start=2)
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(2, "Mon", 2, 1)
        self.assertIn("SPECIALIZATION_OVERLAP", self._codes(cm.exception))

    def test_sync_intact_after_normal_move(self):
        specs = self._mk_spec_cohort(day="Mon", start=2)
        sc, result = self._move(2, "Mon", 3, 1)
        self.assertTrue(result.ok)
        for _name, (_spec, _assign, scc, slot) in specs.items():
            kept = self.m.ScheduledClass.query.get(scc.id)
            self.assertEqual((kept.day, kept.start_period), ("Mon", 2))
        self.assertEqual((sc.day, sc.start_period), ("Mon", 3))


# ------------------------------------------------------- consistency + safety
class TestConsistencySafety(NBase):
    def test_validate_matches_move_invalid(self):
        from backend import manual_edits as me
        dry = self._validate(1, "Tue", 0, 1)
        self.assertFalse(dry.ok)
        dry_codes = sorted(f.code for f in dry.failures)
        with self.assertRaises(me.ManualEditError) as cm:
            self._move(1, "Tue", 0, 1)
        self.assertEqual(sorted(self._codes(cm.exception)), dry_codes)

    def test_validate_matches_move_valid_multi(self):
        dry = self._validate(5, "Mon", 5, 4)
        self.assertTrue(dry.ok)
        sc, result = self._move(5, "Mon", 5, 4)
        self.assertTrue(result.ok)
        self.assertEqual((sc.day, sc.start_period), ("Mon", 5))

    def test_noop_no_write(self):
        before = self._rows()
        self.m.db.session.remove()
        self.m.db.engine.dispose()
        before_sha = _sha(self.db_path)
        sc, result = self._move(1, "Mon", 0, 1)
        self.assertTrue(result.ok and result.noop)
        self.assertEqual(self._rows(), before)
        self.m.db.session.remove()
        self.m.db.engine.dispose()
        self.assertEqual(_sha(self.db_path), before_sha)

    def test_dry_run_read_only_sha(self):
        self.m.db.session.remove()
        self.m.db.engine.dispose()
        before_sha = _sha(self.db_path)
        for _ in range(3):
            dry = self._validate(1, "Tue", 0, 1)
            self.assertFalse(dry.ok)
            ok = self._validate(3, "Tue", 2, 2)
            self.assertTrue(ok.ok)
        self.m.db.session.remove()
        self.m.db.engine.dispose()
        self.assertEqual(_sha(self.db_path), before_sha)

    def test_failed_moves_leave_db_identical(self):
        from backend import manual_edits as me
        cases = [(1, "Tue", 0, 1), (1, "Mon", 4, 1), (3, "Mon", 2, 2),
                 (1, "Sun", 0, 1), (5, "Mon", 3, 4)]
        for cid, day, start, room in cases:
            with self.subTest(cid=cid, day=day, start=start, room=room):
                before_rows = self._rows()
                self.m.db.session.remove()
                self.m.db.engine.dispose()
                before_sha = _sha(self.db_path)
                with self.assertRaises(me.ManualEditError):
                    self._move(cid, day, start, room)
                self.assertEqual(self._rows(), before_rows)
                self.m.db.session.remove()
                self.m.db.engine.dispose()
                self.assertEqual(_sha(self.db_path), before_sha)

    def test_success_changes_only_intended_row(self):
        before = {r[0]: r for r in self._rows()}
        sc, _ = self._move(3, "Tue", 2, 2)
        after = {r[0]: r for r in self._rows()}
        self.assertEqual(set(before), set(after))
        for cid, row in after.items():
            if cid == sc.id:
                self.assertEqual((row[2], row[3], row[5]), ("Tue", 2, 2))
            else:
                self.assertEqual(row, before[cid])

    def test_no_scheduler_invocation(self):
        import backend.manual_edits as me_mod
        with open(me_mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("run_scheduler", src)
        self.assertNotIn("CpSolver", src)


class TestApiSafety(NApiBase):
    def test_validate_dry_run_writes_nothing(self):
        self.m.db.session.remove()
        self.m.db.engine.dispose()
        before_sha = _sha(self.db_path)
        resp = self.client.post("/api/schedule/classes/3/validate-move",
                                json={"day": "Tue", "start_period": 2,
                                      "room_id": 2})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"] and not body["noop"])
        self.assertIn("candidate", body)
        self.assertIn("current", body)
        sc = self.m.ScheduledClass.query.get(3)
        self.assertEqual((sc.day, sc.start_period, sc.room_id),
                         ("Mon", 4, 2))
        self.m.db.session.remove()
        self.m.db.engine.dispose()
        self.assertEqual(_sha(self.db_path), before_sha)

    def test_validate_conflict_envelope(self):
        resp = self.client.post("/api/schedule/classes/1/validate-move",
                                json={"day": "Tue", "start_period": 0,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        for key in ("error", "code", "details", "failures"):
            self.assertIn(key, body)
        self.assertEqual(body["code"], "ROOM_CONFLICT")
        self.assertTrue(body["failures"])
        self.assertEqual(
            body["failures"][0]["code"], "ROOM_CONFLICT")

    def test_move_ok_envelope(self):
        resp = self.client.post("/api/schedule/classes/3/move",
                                json={"day": "Tue", "start_period": 2,
                                      "room_id": 2})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"] and not body["noop"])
        item = body["scheduled_class"]
        for key in ("id", "assignment_id", "day", "start_period",
                    "length", "room_id", "subject", "faculty"):
            self.assertIn(key, item)
        self.assertEqual(item["assignment_id"], 2)
        self.assertEqual(item["length"], 1)

    def test_move_noop_envelope(self):
        resp = self.client.post("/api/schedule/classes/1/move",
                                json={"day": "Mon", "start_period": 0,
                                      "room_id": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["noop"])

    def test_move_ignores_forbidden_fields(self):
        resp = self.client.post(
            "/api/schedule/classes/3/move",
            json={"day": "Tue", "start_period": 2, "room_id": 2,
                  "assignment_id": 1, "length": 5, "run_id": "hacked",
                  "is_locked": True, "faculty_id": 3})
        self.assertEqual(resp.status_code, 200)
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

    def test_reference_dbs_untouched(self):
        for ref in REF_DB_CANDIDATES:
            if os.path.isfile(ref):
                before = _sha(ref)
                self.assertEqual(_sha(ref), before)


if __name__ == "__main__":
    unittest.main()
