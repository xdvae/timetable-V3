"""Phase 6F tests: specializations.

Covers configuration, synchronization, scheduling, HN1, locked blocks,
validator, audit (read-only), migration, and API.

Every test uses throwaway SQLite files in a temp dir — never the real
`timetable_v2.db`. Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_specializations_6f -v
"""
import hashlib
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

DAYS = "Mon,Tue,Wed,Thu,Fri"
PERIODS = "|".join(f"p{i}" for i in range(7))


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class SpecTestBase(unittest.TestCase):
    """Throwaway Flask app + BCA Sem3 cohort (A/B/C) + unrelated cohort."""

    def setUp(self):
        from flask import Flask
        from backend import models as m
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "t6f.db")
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db_path
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        m.db.init_app(self.app)
        self.m = m
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(session_name="6F", working_days=DAYS,
                                  periods=PERIODS, break_after_periods=4,
                                  max_consecutive_teaching=3))
        m.db.session.add(m.Program(id=1, name="BCA"))
        m.db.session.add(m.Program(id=2, name="CSE"))
        m.db.session.add(m.Enrollment(id=1, program_id=1, year_label="Sem3",
                                      total_students=90))
        m.db.session.add(m.Enrollment(id=2, program_id=2, year_label="Sem3",
                                      total_students=40))
        # Cohort: A/B/C x30.
        m.db.session.add(m.Section(id=1, enrollment_id=1, name="BCA-3-A",
                                   student_count=30))
        m.db.session.add(m.Section(id=2, enrollment_id=1, name="BCA-3-B",
                                   student_count=30))
        m.db.session.add(m.Section(id=3, enrollment_id=1, name="BCA-3-C",
                                   student_count=30))
        # Unrelated cohort section.
        m.db.session.add(m.Section(id=9, enrollment_id=2, name="CSE-3-A",
                                   student_count=40))
        for rid, nm, rt, cap, eq in [
                (1, "101", "theory", 100, None),
                (2, "102", "theory", 100, None),
                (3, "103", "theory", 100, None),
                (4, "104", "theory", 10, None),
                (5, "L1", "lab", 40, 40),
                (6, "L2", "lab", 40, 40)]:
            m.db.session.add(m.Room(id=rid, name=nm, room_type=rt,
                                    capacity=cap, equipment_count=eq))
        for fid, nm in [(1, "F1"), (2, "F2"), (3, "F3"), (4, "F4"),
                        (5, "F5"), (6, "F6")]:
            m.db.session.add(m.Faculty(id=fid, name=nm))
        m.db.session.add(m.Subject(id=1, name="CyberSub", enrollment_id=1))
        m.db.session.add(m.Subject(id=2, name="AISub", enrollment_id=1))
        m.db.session.add(m.Subject(id=3, name="FullSub", enrollment_id=1))
        m.db.session.add(m.Subject(id=4, name="DBMS", enrollment_id=1))
        m.db.session.add(m.Subject(id=9, name="CSESub", enrollment_id=2))
        m.db.session.commit()

    def tearDown(self):
        try:
            self.m.db.session.remove()
            self.m.db.engine.dispose()
        except Exception:
            pass

    # -- helpers ------------------------------------------------------
    def _svc(self):
        from backend import specializations as s
        return s

    def _mk_spec(self, name="Cyber", enrollment_id=1, session_type="theory",
                 block_length=1, periods_per_week=2):
        return self._svc().create_specialization(
            self.m.db, name=name, enrollment_id=enrollment_id,
            session_type=session_type, block_length=block_length,
            periods_per_week=periods_per_week)

    def _mk_mem(self, spec_id, section_id, count):
        return self._svc().add_or_update_membership(
            self.m.db, spec_id, section_id, count)

    def _mk_assignment(self, faculty_id, subject_id, spec_id,
                       periods_per_week=2, block_length=1,
                       session_type="theory"):
        a = self.m.TeachingAssignment(
            faculty_id=faculty_id, subject_id=subject_id,
            session_type=session_type, section_id=None, lab_group_id=None,
            specialization_id=spec_id, periods_per_week=periods_per_week,
            block_length=block_length)
        self.m.db.session.add(a)
        self.m.db.session.commit()
        return a

    def _spec_info(self):
        return self._svc().query_spec_info(self.m.db)

    def _sched_inputs(self):
        m = self.m
        cfg = m.Config.query.first()
        return (m.TeachingAssignment.query.all(), m.Room.query.all(),
                {f.id: f.unavailable_set() for f in m.Faculty.query.all()},
                cfg.day_list(), len(cfg.period_list()),
                cfg.break_after_periods or None,
                cfg.max_consecutive_teaching)


# ------------------------------------------------------- configuration
class TestConfiguration(SpecTestBase):
    def test_create_specialization(self):
        s = self._mk_spec("Cyber Security")
        self.assertEqual(s.enrollment_id, 1)
        self.assertEqual(self.m.Specialization.query.count(), 1)

    def test_duplicate_specialization_rejected(self):
        self._mk_spec("Cyber")
        with self.assertRaises(self._svc().SpecializationError) as cm:
            self._mk_spec("Cyber")
        self.assertEqual(cm.exception.to_payload()["code"],
                         "SPECIALIZATION_MEMBERSHIP")

    def test_valid_membership(self):
        s = self._mk_spec("Cyber")
        row = self._mk_mem(s.id, 1, 12)
        self.assertEqual(row.student_count, 12)

    def test_zero_membership_rejected(self):
        s = self._mk_spec("Cyber")
        with self.assertRaises(self._svc().SpecializationError) as cm:
            self._svc().add_or_update_membership(self.m.db, s.id, 1, 0)
        codes = [f.code for f in cm.exception.failures]
        self.assertIn("SPECIALIZATION_MEMBERSHIP", codes)

    def test_negative_membership_rejected(self):
        s = self._mk_spec("Cyber")
        with self.assertRaises(self._svc().SpecializationError) as cm:
            self._svc().add_or_update_membership(self.m.db, s.id, 1, -5)
        self.assertIn("SPECIALIZATION_MEMBERSHIP",
                      [f.code for f in cm.exception.failures])

    def test_wrong_enrollment_rejected(self):
        s = self._mk_spec("Cyber", enrollment_id=1)
        with self.assertRaises(self._svc().SpecializationError) as cm:
            self._mk_mem(s.id, 9, 10)  # CSE section into BCA spec
        self.assertIn("SPECIALIZATION_ENROLLMENT",
                      [f.code for f in cm.exception.failures])

    def test_membership_exceeding_section_rejected(self):
        s = self._mk_spec("Cyber")
        with self.assertRaises(self._svc().SpecializationError) as cm:
            self._mk_mem(s.id, 1, 31)  # section has 30
        payload = cm.exception.to_payload()
        self.assertEqual(payload["code"], "SPECIALIZATION_CAPACITY")
        self.assertIn("section_capacity", payload["details"])
        self.assertIn("requested", payload["details"])

    def test_aggregate_membership_rejected(self):
        c = self._mk_spec("Cyber")
        a = self._mk_spec("AI")
        f = self._mk_spec("Full")
        self._mk_mem(c.id, 1, 15)
        self._mk_mem(a.id, 1, 15)
        # 15+15=30 full; 10 more must fail with remaining 0.
        with self.assertRaises(self._svc().SpecializationError) as cm:
            self._mk_mem(f.id, 1, 10)
        payload = cm.exception.to_payload()
        self.assertEqual(payload["code"], "SPECIALIZATION_CAPACITY")
        det = payload["details"]
        self.assertEqual(det["section_capacity"], 30)
        self.assertEqual(det["existing_allocation"], 30)
        self.assertEqual(det["remaining_capacity"], 0)

    def test_aggregate_exact_fits(self):
        c = self._mk_spec("Cyber")
        a = self._mk_spec("AI")
        f = self._mk_spec("Full")
        self._mk_mem(c.id, 1, 15)
        self._mk_mem(a.id, 1, 15 - 5)
        self._mk_mem(f.id, 1, 5)  # 15+10+5=30 exact
        self.assertEqual(self.m.SpecializationMembership.query.count(), 3)

    def test_unequal_counts_valid(self):
        s = self._mk_spec("Cyber")
        self._mk_mem(s.id, 1, 10)
        self._mk_mem(s.id, 2, 17)
        self._mk_mem(s.id, 3, 5)
        info = self._spec_info()
        self.assertEqual(info[s.id]["total_students"], 32)


# ------------------------------------------------------- synchronization
class TestSynchronization(SpecTestBase):
    def _slots(self, spec_id, pairs):
        for day, start in pairs:
            self.m.db.session.add(self.m.SpecializationSlot(
                specialization_id=spec_id, day=day,
                start_period=start, length=1))
        self.m.db.session.commit()

    def _sync(self, pairs_by_spec, enrollment_id=1):
        from backend.specializations import validate_sync_for_enrollment
        slots = {sid: pairs for sid, pairs in pairs_by_spec.items()}
        names = {sid: str(sid) for sid in slots}
        return validate_sync_for_enrollment(slots, names, enrollment_id)

    def test_two_specs_synchronize(self):
        c = self._mk_spec("Cyber")
        a = self._mk_spec("AI")
        for s in (c, a):
            self._mk_mem(s.id, 1, 10)
        self._slots(c.id, [("Mon", 2)])
        self._slots(a.id, [("Mon", 2)])
        fails = self._sync({c.id: [("Mon", 2, 1)],
                            a.id: [("Mon", 2, 1)]})
        self.assertEqual(fails, [])

    def test_three_specs_synchronize(self):
        ids = [self._mk_spec(n).id for n in ("Cyber", "AI", "Full")]
        for sid in ids:
            self._mk_mem(sid, 1, 10)
            self._slots(sid, [("Tue", 1), ("Thu", 4)])
        fails = self._sync({sid: [("Tue", 1, 1), ("Thu", 4, 1)]
                            for sid in ids})
        self.assertEqual(fails, [])

    def test_mismatched_day_rejected(self):
        c = self._mk_spec("Cyber")
        a = self._mk_spec("AI")
        fails = self._sync({c.id: [("Mon", 2, 1)], a.id: [("Tue", 2, 1)]})
        self.assertEqual([f.code for f in fails], ["SPECIALIZATION_SYNC"])

    def test_mismatched_start_rejected(self):
        c = self._mk_spec("Cyber")
        a = self._mk_spec("AI")
        fails = self._sync({c.id: [("Mon", 2, 1)], a.id: [("Mon", 3, 1)]})
        self.assertEqual(fails[0].code, "SPECIALIZATION_SYNC")

    def test_mismatched_length_rejected(self):
        c = self._mk_spec("Cyber")
        a = self._mk_spec("AI")
        fails = self._sync({c.id: [("Mon", 2, 1)], a.id: [("Mon", 2, 2)]})
        self.assertEqual(fails[0].code, "SPECIALIZATION_SYNC")

    def test_single_spec_always_syncs(self):
        c = self._mk_spec("Cyber")
        self.assertEqual(self._sync({c.id: [("Mon", 0, 1)]}), [])

    def test_scheduler_sync_equality(self):
        # Two specs must land on identical (day, start) via CP-SAT equality.
        from backend.scheduler import run_scheduler
        c = self._mk_spec("Cyber")
        a = self._mk_spec("AI")
        for s in (c, a):
            self._mk_mem(s.id, 1, 10)
            self._mk_mem(s.id, 2, 10)
        ca = self._mk_assignment(1, 1, c.id)
        aa = self._mk_assignment(2, 2, a.id)
        assigns, rooms, unav, days, n, brk, mc = self._sched_inputs()
        info = self._spec_info()
        status, places, _ = run_scheduler(
            assigns, rooms, unav, days, n, brk, mc,
            time_limit_seconds=15, specialization_data=info)
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        by_assign = {}
        for p in places:
            by_assign.setdefault(p["assignment_id"], []).append(
                (p["day"], p["start_period"], p["length"]))
        self.assertEqual(sorted(by_assign[ca.id]), sorted(by_assign[aa.id]))

    def test_scheduler_demand_mismatch_rejected(self):
        from backend.scheduler import run_scheduler
        c = self._mk_spec("Cyber", periods_per_week=2)
        a = self._mk_spec("AI", periods_per_week=4)
        for s in (c, a):
            self._mk_mem(s.id, 1, 10)
        self._mk_assignment(1, 1, c.id, periods_per_week=2)
        self._mk_assignment(2, 2, a.id, periods_per_week=4)
        assigns, rooms, unav, days, n, brk, mc = self._sched_inputs()
        status, _, msg = run_scheduler(
            assigns, rooms, unav, days, n, brk, mc,
            time_limit_seconds=10, specialization_data=self._spec_info())
        self.assertEqual(status, "INFEASIBLE")
        self.assertIn("SPECIALIZATION_SYNC", msg)


# ------------------------------------------------------- scheduling
class TestScheduling(SpecTestBase):
    def _base_specs(self, session_type="theory"):
        c = self._mk_spec("Cyber", session_type=session_type)
        a = self._mk_spec("AI", session_type=session_type)
        for s in (c, a):
            self._mk_mem(s.id, 1, 10)
            self._mk_mem(s.id, 2, 10)
        return c, a

    def _run(self):
        from backend.scheduler import run_scheduler
        assigns, rooms, unav, days, n, brk, mc = self._sched_inputs()
        return run_scheduler(
            assigns, rooms, unav, days, n, brk, mc,
            time_limit_seconds=15,
            specialization_data=self._spec_info())

    def test_receives_compatible_room(self):
        c, a = self._base_specs()
        self._mk_assignment(1, 1, c.id)
        self._mk_assignment(2, 2, a.id)
        status, places, _ = self._run()
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(len(places), 4)  # 2 specs x 2 periods
        rooms = {r.id: r for r in self.m.Room.query.all()}
        for p in places:
            self.assertEqual(rooms[p["room_id"]].room_type, "theory")
            self.assertGreaterEqual(rooms[p["room_id"]].capacity, 20)

    def test_room_capacity_enforced(self):
        c, _ = self._base_specs()
        # Total 20 but only room 104 (cap 10) if others removed.
        for r in self.m.Room.query.all():
            if r.id != 4:
                self.m.db.session.delete(r)
        self.m.db.session.commit()
        self._mk_assignment(1, 1, c.id)
        status, _, msg = self._run()
        self.assertEqual(status, "INFEASIBLE")
        self.assertIn("SPECIALIZATION_CAPACITY", msg)

    def test_different_rooms_allowed(self):
        c, a = self._base_specs()
        self._mk_assignment(1, 1, c.id)
        self._mk_assignment(2, 2, a.id)
        status, places, _ = self._run()
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        # Same synchronized slot may use different rooms: group placements
        # by (day, start) — each time bucket must contain both specs.
        from collections import Counter
        buckets = Counter((p["day"], p["start_period"]) for p in places)
        # 2 sessions per spec, synchronized => 2 buckets x2 specs each.
        self.assertTrue(all(v == 2 for v in buckets.values()))

    def test_different_faculty_allowed(self):
        c, a = self._base_specs()
        self._mk_assignment(1, 1, c.id)  # F1
        self._mk_assignment(2, 2, a.id)  # F2
        status, places, _ = self._run()
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))

    def test_same_faculty_conflicts(self):
        c, a = self._base_specs()
        self._mk_assignment(1, 1, c.id)  # both F1 -> same time impossible
        self._mk_assignment(1, 2, a.id)
        status, _, _ = self._run()
        # Same faculty cannot teach two synchronized specs at once.
        self.assertEqual(status, "INFEASIBLE")

    def test_occupies_participating_section(self):
        from backend import schedule_validator as sv
        c, _ = self._base_specs()
        ca = self._mk_assignment(1, 1, c.id)
        # Normal theory for section 1 (DBMS) + spec involving section 1.
        normal = self.m.TeachingAssignment(
            faculty_id=3, subject_id=4, session_type="theory",
            section_id=1, periods_per_week=1, block_length=1)
        self.m.db.session.add(normal)
        self.m.db.session.commit()
        # Build snapshot with one spec class at Mon P0 and validate a normal
        # candidate at the same cell: must be SPECIALIZATION_OVERLAP.
        rooms = [SimpleNamespace(id=1, name="101", room_type="theory",
                                 capacity=100, equipment_count=None)]
        fac = [SimpleNamespace(id=1, unavailable_slots=""),
               SimpleNamespace(id=3, unavailable_slots="")]
        secs = [SimpleNamespace(id=1, name="BCA-3-A", student_count=30),
                SimpleNamespace(id=2, name="BCA-3-B", student_count=30)]
        specs = [SimpleNamespace(id=c.id, enrollment_id=1,
                                 session_type="theory", name="Cyber")]
        mems = [SimpleNamespace(id=1, specialization_id=c.id, section_id=1,
                                student_count=10),
                SimpleNamespace(id=2, specialization_id=c.id, section_id=2,
                                student_count=10)]
        assigns = [SimpleNamespace(id=normal.id, faculty_id=3,
                                   session_type="theory", section_id=1,
                                   lab_group_id=None, section_name="BCA-3-A",
                                   section_size=30),
                   SimpleNamespace(id=ca.id, faculty_id=1,
                                   session_type="theory", section_id=None,
                                   lab_group_id=None,
                                   specialization_id=c.id)]
        classes = [SimpleNamespace(id=500, assignment_id=ca.id, day="Mon",
                                   start_period=0, length=1, room_id=1)]
        snap = sv.build_snapshot(["Mon", "Tue"], 7, 4, 3, rooms, fac, [],
                                 secs, assigns, classes,
                                 specializations=specs, memberships=mems)
        fails = sv.validate_candidate(
            snap, session_type="theory", group_key="section:1",
            group_label="BCA-3-A", group_size=30, faculty_id=3,
            day="Mon", start_period=0, length=1, room_id=1)
        self.assertIn("SPECIALIZATION_OVERLAP", [f.code for f in fails])

    def test_coexist_with_unrelated_section(self):
        from backend import schedule_validator as sv
        c, _ = self._base_specs()
        ca = self._mk_assignment(1, 1, c.id)
        rooms = [SimpleNamespace(id=1, name="101", room_type="theory",
                                 capacity=100, equipment_count=None)]
        fac = [SimpleNamespace(id=1, unavailable_slots=""),
               SimpleNamespace(id=4, unavailable_slots="")]
        secs = [SimpleNamespace(id=1, name="BCA-3-A", student_count=30),
                SimpleNamespace(id=9, name="CSE-3-A", student_count=40)]
        specs = [SimpleNamespace(id=c.id, enrollment_id=1,
                                 session_type="theory", name="Cyber")]
        mems = [SimpleNamespace(id=1, specialization_id=c.id, section_id=1,
                                student_count=10)]
        assigns = [SimpleNamespace(id=900, faculty_id=4,
                                   session_type="theory", section_id=9,
                                   lab_group_id=None, section_name="CSE-3-A",
                                   section_size=40),
                   SimpleNamespace(id=ca.id, faculty_id=1,
                                   session_type="theory", section_id=None,
                                   lab_group_id=None,
                                   specialization_id=c.id)]
        classes = [SimpleNamespace(id=501, assignment_id=ca.id, day="Mon",
                                   start_period=0, length=1, room_id=1)]
        snap = sv.build_snapshot(["Mon", "Tue"], 7, 4, 3, rooms, fac, [],
                                 secs, assigns, classes,
                                 specializations=specs, memberships=mems)
        fails = sv.validate_candidate(
            snap, session_type="theory", group_key="section:9",
            group_label="CSE-3-A", group_size=40, faculty_id=4,
            day="Mon", start_period=0, length=1, room_id=1)
        # Room is occupied by the spec class, so ROOM_CONFLICT is expected;
        # but there must be NO specialization overlap for unrelated sections.
        self.assertNotIn("SPECIALIZATION_OVERLAP",
                         [f.code for f in fails])

    def test_respects_break_and_working_days(self):
        from backend.scheduler import run_scheduler
        c, _ = self._base_specs()
        self._mk_mem(c.id, 3, 5)
        self._mk_assignment(1, 1, c.id, periods_per_week=1, block_length=1)
        assigns, rooms, unav, days, n, brk, mc = self._sched_inputs()
        # Break-aware: no placement may span the break; days must be known.
        status, places, _ = run_scheduler(
            assigns, rooms, unav, days, n, brk, mc,
            time_limit_seconds=10,
            specialization_data=self._spec_info())
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        for p in places:
            self.assertIn(p["day"], days)
            self.assertFalse(p["start_period"] < brk < p["start_period"] + p["length"])

    def test_respects_locked_block(self):
        from backend import locked_blocks as lb
        from backend.scheduler import run_scheduler
        c, _ = self._base_specs()
        ca = self._mk_assignment(1, 1, c.id, periods_per_week=1)
        # Normal assignment locked at Mon P0 for section 1.
        normal = self.m.TeachingAssignment(
            faculty_id=3, subject_id=4, session_type="theory",
            section_id=1, periods_per_week=2, block_length=1)
        self.m.db.session.add(normal)
        self.m.db.session.commit()
        lb.create_locked_block(self.m.db, assignment_id=normal.id,
                               day="Mon", start_period=0, length=1, room_id=1)
        assigns, rooms, unav, days, n, brk, mc = self._sched_inputs()
        status, places, _ = run_scheduler(
            assigns, rooms, unav, days, n, brk, mc,
            time_limit_seconds=15,
            locked_placements=lb.query_locked_placements(),
            specialization_data=self._spec_info())
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        for p in places:
            a = self.m.TeachingAssignment.query.get(p["assignment_id"])
            if getattr(a, "specialization_id", None) is not None:
                info = self._spec_info()[a.specialization_id]
                if 1 in info["section_ids"]:
                    self.assertFalse(
                        p["day"] == "Mon" and p["start_period"] == 0,
                        "spec must avoid locked section occupancy")

    def test_empty_spec_skipped(self):
        from backend.scheduler import run_scheduler
        c = self._mk_spec("Cyber")  # no memberships
        self._mk_assignment(1, 1, c.id, periods_per_week=2)
        assigns, rooms, unav, days, n, brk, mc = self._sched_inputs()
        status, places, _ = run_scheduler(
            assigns, rooms, unav, days, n, brk, mc,
            time_limit_seconds=10,
            specialization_data=self._spec_info())
        self.assertEqual(status, "NO_SESSIONS")
        self.assertEqual(places, [])


# ------------------------------------------------------- HN1
class TestHN1(SpecTestBase):
    def _validator_snap(self, theory_periods, spec_periods=(),
                        session_type="theory"):
        from backend import schedule_validator as sv
        c = self._mk_spec("Cyber", session_type=session_type)
        self._mk_mem(c.id, 1, 10)
        rooms = [SimpleNamespace(id=1, name="101", room_type="theory",
                                 capacity=100, equipment_count=None),
                 SimpleNamespace(id=5, name="L1", room_type="lab",
                                 capacity=40, equipment_count=40)]
        fac = [SimpleNamespace(id=1, unavailable_slots=""),
               SimpleNamespace(id=2, unavailable_slots="")]
        secs = [SimpleNamespace(id=1, name="BCA-3-A", student_count=30)]
        assigns = [SimpleNamespace(id=100, faculty_id=2,
                                   session_type="theory", section_id=1,
                                   lab_group_id=None, section_name="BCA-3-A",
                                   section_size=30),
                   SimpleNamespace(id=200, faculty_id=1,
                                   session_type=session_type, section_id=None,
                                   lab_group_id=None,
                                   specialization_id=c.id)]
        specs = [SimpleNamespace(id=c.id, enrollment_id=1,
                                 session_type=session_type, name="Cyber")]
        mems = [SimpleNamespace(id=1, specialization_id=c.id, section_id=1,
                                student_count=10)]
        classes = [SimpleNamespace(id=1000 + i, assignment_id=100,
                                   day="Mon", start_period=p, length=1,
                                   room_id=1) for i, p in
                   enumerate(sorted(theory_periods))]
        classes += [SimpleNamespace(id=2000 + i, assignment_id=200,
                                    day="Mon", start_period=p, length=1,
                                    room_id=1) for i, p in
                    enumerate(sorted(spec_periods))]
        return sv.build_snapshot(["Mon", "Tue"], 7, 4, 3, rooms, fac, [],
                                 secs, assigns, classes,
                                 specializations=specs, memberships=mems), c

    def test_theory_contributes(self):
        # Section already has T(0,1 normal) + T(2 spec) = 3 in a window.
        occupied = {0, 1, 2}
        from backend import schedule_rules as rules
        bad = rules.check_max_two_theory(occupied, 7, 4, "S", "Mon", 1)
        self.assertTrue(bad)

    def test_spec_theory_plus_two_normal_triggers(self):
        from backend import schedule_validator as sv
        snap, c = self._validator_snap([0, 1], [])
        fails = sv.validate_specialization_candidate(
            snap, specialization_id=c.id, section_ids=[1],
            total_students=10, session_type="theory", faculty_id=1,
            day="Mon", start_period=2, length=1, room_id=1,
            specialization_name="Cyber")
        self.assertIn("MAX_TWO_THEORY", [f.code for f in fails])

    def test_practical_does_not_count(self):
        from backend import schedule_validator as sv
        snap, c = self._validator_snap([0, 1], [], session_type="practical")
        # Practical spec at P2 with two normal theories: allowed for HN1
        # (overlap still checked separately; use a free cell for HN1 focus
        # by placing spec practical where no normal class sits — here P2 is
        # free of normal group occupancy? normal occupies 0,1 so P2 free).
        fails = sv.validate_specialization_candidate(
            snap, specialization_id=c.id, section_ids=[1],
            total_students=10, session_type="practical", faculty_id=1,
            day="Mon", start_period=2, length=1, room_id=5,
            specialization_name="Cyber")
        self.assertNotIn("MAX_TWO_THEORY", [f.code for f in fails])

    def test_break_resets(self):
        from backend import schedule_rules as rules
        # {3 normal} + spec {4} straddles break_after=4 -> no window covers
        # all three (windows are (0,1,2),(1,2,3),(4,5,6)).
        self.assertEqual(
            rules.check_max_two_theory([3, 4], 7, 4, "S", "Mon", 1), [])

    def test_free_period_resets(self):
        from backend import schedule_rules as rules
        self.assertEqual(
            rules.check_max_two_theory([0, 2], 7, 4, "S", "Mon", 1), [])

    def test_no_triple_count(self):
        from backend import schedule_validator as sv
        # Three synchronized specs at Mon P2: section footprint must be 1,
        # not 3, and HN1 must see a single theory period there.
        c = self._mk_spec("Cyber")
        a = self._mk_spec("AI")
        f = self._mk_spec("Full")
        for s in (c, a, f):
            self._mk_mem(s.id, 1, 10)
        rooms = [SimpleNamespace(id=1, name="101", room_type="theory",
                                 capacity=100, equipment_count=None)]
        fac = [SimpleNamespace(id=1, unavailable_slots=""),
               SimpleNamespace(id=2, unavailable_slots=""),
               SimpleNamespace(id=3, unavailable_slots="")]
        secs = [SimpleNamespace(id=1, name="BCA-3-A", student_count=30)]
        specs = [SimpleNamespace(id=c.id, enrollment_id=1,
                                 session_type="theory", name="Cyber"),
                 SimpleNamespace(id=a.id, enrollment_id=1,
                                 session_type="theory", name="AI"),
                 SimpleNamespace(id=f.id, enrollment_id=1,
                                 session_type="theory", name="Full")]
        mems = []
        for i, s in enumerate((c, a, f)):
            mems.append(SimpleNamespace(id=10 + i, specialization_id=s.id,
                                        section_id=1, student_count=10))
        assigns = [SimpleNamespace(id=300 + i, faculty_id=1 + i,
                                   session_type="theory", section_id=None,
                                   lab_group_id=None, specialization_id=s.id)
                   for i, s in enumerate((c, a, f))]
        classes = [SimpleNamespace(id=400 + i, assignment_id=300 + i,
                                   day="Mon", start_period=2, length=1,
                                   room_id=1) for i in range(3)]
        snap = sv.build_snapshot(["Mon"], 7, 4, 3, rooms, fac, [], secs,
                                 assigns, classes, specializations=specs,
                                 memberships=mems)
        self.assertEqual(snap.spec_section_occ.get((1, "Mon", 2)), 1)
        self.assertEqual(snap.spec_theory_occ.get((1, "Mon", 2)), 1)


# ------------------------------------------------------- migration
class TestMigration6F(unittest.TestCase):
    def test_upgrade_adds_column_and_downgrade_removes(self):
        import importlib
        up = importlib.import_module(
            "backend.migrations.versions.6f_specializations")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = os.path.join(tmp.name, "m.db")
        con = sqlite3.connect(db)
        try:
            con.execute("CREATE TABLE specialization (id INTEGER PRIMARY KEY)")
            con.execute("CREATE TABLE teaching_assignment (id INTEGER PRIMARY KEY)")
            up.upgrade(con)
            con.commit()
            cols = [r[1] for r in con.execute(
                'PRAGMA table_info("teaching_assignment")')]
            self.assertIn("specialization_id", cols)
            con.execute("INSERT INTO teaching_assignment (id) VALUES (1)")
            con.commit()
            up.downgrade(con)
            con.commit()
            cols = [r[1] for r in con.execute(
                'PRAGMA table_info("teaching_assignment")')]
            self.assertNotIn("specialization_id", cols)
            self.assertEqual(
                con.execute("SELECT id FROM teaching_assignment").fetchone()[0],
                1)
        finally:
            con.close()

    def test_chain_links_6e(self):
        import importlib
        up = importlib.import_module(
            "backend.migrations.versions.6f_specializations")
        self.assertEqual(up.down_revision, "6e_locked_assignment")


# ------------------------------------------------------- API
class TestApi(SpecTestBase):
    def setUp(self):
        super().setUp()
        from flask_login import LoginManager
        from backend.api_routes import init_api
        self.app.secret_key = "6f-test"
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

    def test_create_list_membership_delete(self):
        r = self.client.post("/api/specializations",
                             json={"name": "AI", "enrollment_id": 1})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        sid = r.get_json()["specialization"]["id"]
        r = self.client.get("/api/specializations")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()["specializations"]), 1)
        r = self.client.post(f"/api/specializations/{sid}/memberships",
                             json={"section_id": 1, "student_count": 14})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        # Zero rejected with structured code.
        r = self.client.post(f"/api/specializations/{sid}/memberships",
                             json={"section_id": 2, "student_count": 0})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["code"], "SPECIALIZATION_MEMBERSHIP")
        # Wrong enrollment rejected.
        r = self.client.post(f"/api/specializations/{sid}/memberships",
                             json={"section_id": 9, "student_count": 5})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["code"], "SPECIALIZATION_ENROLLMENT")
        # Delete membership (POST-style).
        r = self.client.post(
            f"/api/specializations/{sid}/memberships/delete",
            json={"section_id": 1})
        self.assertEqual(r.status_code, 200)
        # Delete specialization (POST-style).
        r = self.client.post(f"/api/specializations/{sid}/delete")
        self.assertEqual(r.status_code, 200)

    def test_duplicate_name_rejected(self):
        self.client.post("/api/specializations",
                         json={"name": "Cyber", "enrollment_id": 1})
        r = self.client.post("/api/specializations",
                             json={"name": "Cyber", "enrollment_id": 1})
        self.assertEqual(r.status_code, 422)

    def test_schedule_lists_rooms_faculty(self):
        r = self.client.post("/api/specializations",
                             json={"name": "Cyber", "enrollment_id": 1,
                                   "periods_per_week": 1})
        sid = r.get_json()["specialization"]["id"]
        self.client.post(f"/api/specializations/{sid}/memberships",
                         json={"section_id": 1, "student_count": 10})
        # Spec assignment via extended assignments endpoint.
        r = self.client.post("/api/assignments",
                             json={"faculty_id": 1, "subject_id": 1,
                                   "session_type": "theory",
                                   "specialization_id": sid,
                                   "periods_per_week": 1, "block_length": 1})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        r = self.client.post("/api/schedule/run")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        r = self.client.get(f"/api/specializations/{sid}")
        body = r.get_json()["specialization"]
        self.assertTrue(body["scheduled_classes"])
        self.assertTrue(body["slots"])
        sc = body["scheduled_classes"][0]
        self.assertIn("room", sc)
        self.assertIn("faculty", sc)


# ------------------------------------------------------- audit
class TestAudit(SpecTestBase):
    def _snapshot_via_cli(self):
        from backend.audit_schedule import load_snapshot, open_readonly
        con = open_readonly(self.db_path)
        try:
            return load_snapshot(con)
        finally:
            con.close()

    def test_sync_violation_detected(self):
        from backend.audit_schedule import audit_snapshot
        c = self._mk_spec("Cyber")
        a = self._mk_spec("AI")
        for s in (c, a):
            self._mk_mem(s.id, 1, 10)
            self.m.db.session.add(self.m.SpecializationSlot(
                specialization_id=s.id, day="Mon",
                start_period=(0 if s.id == c.id else 1), length=1))
        self.m.db.session.commit()
        snap = self._snapshot_via_cli()
        problems, _ = audit_snapshot(snap)
        self.assertTrue(any("SPECIALIZATION_SYNC" in p for p in problems))

    def test_overlap_detected(self):
        from backend.audit_schedule import audit_snapshot
        c = self._mk_spec("Cyber", periods_per_week=1)
        self._mk_mem(c.id, 1, 10)
        ca = self._mk_assignment(1, 1, c.id, periods_per_week=1)
        normal = self.m.TeachingAssignment(
            faculty_id=2, subject_id=4, session_type="theory",
            section_id=1, periods_per_week=1, block_length=1)
        self.m.db.session.add(normal)
        self.m.db.session.commit()
        # Both at Mon P0: normal section class + spec class.
        self.m.db.session.add(self.m.ScheduledClass(
            assignment_id=normal.id, day="Mon", start_period=0,
            length=1, room_id=1, run_id="t"))
        self.m.db.session.add(self.m.ScheduledClass(
            assignment_id=ca.id, day="Mon", start_period=0,
            length=1, room_id=2, run_id="t"))
        self.m.db.session.commit()
        snap = self._snapshot_via_cli()
        problems, _ = audit_snapshot(snap)
        self.assertTrue(any("SPECIALIZATION_OVERLAP" in p for p in problems))

    def test_capacity_detected(self):
        from backend.audit_schedule import audit_snapshot
        c = self._mk_spec("Cyber")
        # Directly insert over-allocated membership bypassing validation.
        self.m.db.session.add(self.m.SpecializationMembership(
            specialization_id=c.id, section_id=1, student_count=30))
        other = self._mk_spec("AI")
        self.m.db.session.add(self.m.SpecializationMembership(
            specialization_id=other.id, section_id=1, student_count=30))
        # 30+30=60 > 30 capacity.
        self.m.db.session.commit()
        snap = self._snapshot_via_cli()
        problems, _ = audit_snapshot(snap)
        self.assertTrue(any("SPECIALIZATION_CAPACITY" in p for p in problems))

    def test_enrollment_detected(self):
        from backend.audit_schedule import audit_snapshot
        c = self._mk_spec("Cyber")
        self.m.db.session.add(self.m.SpecializationMembership(
            specialization_id=c.id, section_id=9, student_count=5))
        self.m.db.session.commit()
        snap = self._snapshot_via_cli()
        problems, _ = audit_snapshot(snap)
        self.assertTrue(any("SPECIALIZATION_ENROLLMENT" in p for p in problems))

    def test_audit_read_only(self):
        from backend.audit_schedule import run_audit
        c = self._mk_spec("Cyber")
        self._mk_mem(c.id, 1, 10)
        self.m.db.session.remove()
        self.m.db.engine.dispose()
        before = _sha(self.db_path)
        code, _ = run_audit(self.db_path)
        self.assertEqual(_sha(self.db_path), before)
        self.assertIn(code, (0, 1))


if __name__ == "__main__":
    unittest.main()
