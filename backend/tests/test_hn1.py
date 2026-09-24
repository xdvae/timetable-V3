"""Phase 6D tests: HN1 — max two consecutive theory periods per section/day.

Covers the pure shared rule, validator integration, scheduler (CP-SAT)
integration, and the read-only audit script.

Run from the repository root:
    venv\\Scripts\\python.exe -m unittest discover -s backend\\tests -t .
"""
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

from backend import schedule_rules as rules
from backend import schedule_validator as sv
from backend.scheduler import run_scheduler

N7 = 7
BRK = 4  # break sits between periods 3 and 4 (matches H10 semantics)


def hn1(periods, n=N7, brk=BRK):
    return rules.check_max_two_theory(periods, n, brk, "BCA-5-A", "Monday", 1)


class TestHn1Windows(unittest.TestCase):
    def test_windows_no_break(self):
        self.assertEqual(rules.hn1_windows(5, None),
                         [(0, 1, 2), (1, 2, 3), (2, 3, 4)])

    def test_windows_respect_break(self):
        # break_after=4 -> segments [0..3] and [4..6]; no window spans it.
        self.assertEqual(rules.hn1_windows(7, 4),
                         [(0, 1, 2), (1, 2, 3), (4, 5, 6)])

    def test_windows_short_segment(self):
        # break_after=2 -> segments [0,1] and [2,3]; neither holds 3 periods.
        self.assertEqual(rules.hn1_windows(4, 2), [])
        self.assertEqual(rules.hn1_windows(5, 2), [(2, 3, 4)])

    def test_windows_out_of_range_break(self):
        self.assertEqual(rules.hn1_windows(3, 99), [(0, 1, 2)])
        self.assertEqual(rules.hn1_windows(3, 0), [(0, 1, 2)])

    def test_overlap_count(self):
        self.assertEqual(rules.overlap_count(2, 2, (1, 2, 3)), 2)
        self.assertEqual(rules.overlap_count(0, 3, (0, 1, 2)), 3)
        self.assertEqual(rules.overlap_count(1, 1, (1, 2, 3)), 1)
        self.assertEqual(rules.overlap_count(5, 1, (1, 2, 3)), 0)
        self.assertEqual(rules.overlap_count(2, 2, (3, 4, 5)), 1)


class TestHn1PureRule(unittest.TestCase):
    def test_three_theory_invalid(self):
        res = hn1([0, 1, 2])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].code, "MAX_TWO_THEORY")
        self.assertIn("BCA-5-A", res[0].message)
        self.assertEqual(res[0].details["periods"], [0, 1, 2])
        self.assertEqual(res[0].details["day"], "Monday")

    def test_two_theory_valid(self):
        self.assertEqual(hn1([0, 1]), [])

    def test_theory_gap_theory_valid(self):
        # Theory + Free + Theory
        self.assertEqual(hn1([0, 2]), [])

    def test_scattered_theory_valid(self):
        self.assertEqual(hn1([0, 2, 4]), [])

    def test_two_then_break_then_theory_valid(self):
        # {2,3} morning + {4} afternoon: no in-segment window is covered.
        self.assertEqual(hn1([2, 3, 4]), [])

    def test_across_break_not_a_streak(self):
        self.assertEqual(hn1([3, 4, 5]), [])

    def test_end_of_day_streak_invalid(self):
        res = hn1([4, 5, 6])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].code, "MAX_TWO_THEORY")

    def test_four_theory_two_windows(self):
        res = hn1([0, 1, 2, 3])
        self.assertEqual([r.details["periods"] for r in res],
                         [[0, 1, 2], [1, 2, 3]])

    def test_length_two_block_plus_theory_invalid(self):
        # length-2 block {1,2} + theory {0} == three consecutive periods.
        self.assertEqual(len(hn1([0, 1, 2])), 1)

    def test_standalone_length_two_valid(self):
        self.assertEqual(hn1([4, 5]), [])

    def test_length_three_block_invalid(self):
        self.assertEqual(len(hn1([0, 1, 2])), 1)

    def test_section_isolation(self):
        # The rule only sees the periods it is given: section B's theory
        # never affects section A's verdict.
        self.assertEqual(hn1([0, 1]), [])
        bad = rules.check_max_two_theory([0, 1, 2], 7, 4, "BCA-5-B", "Monday", 2)
        self.assertEqual(bad[0].details["section_id"], 2)

    def test_faculty_rule_independent(self):
        # Same occupied periods: faculty may teach 3 in a row (H12 limit 3)
        # while the section violates HN1.
        self.assertTrue(rules.check_faculty_consecutive([0, 1, 2], 3).ok)
        self.assertFalse(hn1([0, 1, 2])[0].ok)


class _FakeAssignment:
    def __init__(self, aid, faculty_id, session_type, section_id=None,
                 lab_group_id=None, ppw=1, block=1, size=30):
        self.id = aid
        self.faculty_id = faculty_id
        self.subject_id = 900 + aid
        self.session_type = session_type
        self.section_id = section_id
        self.lab_group_id = lab_group_id
        self.periods_per_week = ppw
        self.block_length = block
        self._size = size
        self.lab_group = (SimpleNamespace(section_id=section_id)
                          if session_type == "practical" else None)

    def group_key(self):
        if self.session_type == "practical":
            return f"labgroup:{self.lab_group_id}"
        return f"section:{self.section_id}"

    def group_label(self):
        return self.group_key()

    def group_size(self):
        return self._size


def _rooms():
    return [SimpleNamespace(id=1, name="T1", room_type="theory",
                            capacity=100, equipment_count=None),
            SimpleNamespace(id=2, name="L1", room_type="lab",
                            capacity=40, equipment_count=40)]


class TestHn1Scheduler(unittest.TestCase):
    def test_forced_triple_is_infeasible(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1, ppw=3, block=1)]
        status, placements, _ = run_scheduler(
            a, _rooms(), {}, ["Mon"], 3, None, None, time_limit_seconds=10)
        self.assertEqual(status, "INFEASIBLE")
        self.assertEqual(placements, [])

    def test_two_theory_feasible(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1, ppw=2, block=1)]
        status, placements, _ = run_scheduler(
            a, _rooms(), {}, ["Mon"], 3, None, None, time_limit_seconds=10)
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(len(placements), 2)

    def test_length_three_block_infeasible(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1, ppw=3, block=3)]
        status, placements, _ = run_scheduler(
            a, _rooms(), {}, ["Mon"], 3, None, None, time_limit_seconds=10)
        self.assertEqual(status, "INFEASIBLE")
        self.assertEqual(placements, [])

    def test_lab_breaks_streak_feasible(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1, ppw=2, block=1),
             _FakeAssignment(2, 2, "practical", section_id=1,
                             lab_group_id=7, ppw=1, block=1)]
        status, placements, _ = run_scheduler(
            a, _rooms(), {}, ["Mon"], 3, None, None, time_limit_seconds=10)
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(len(placements), 3)

    def test_spread_across_days_feasible_and_valid(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1, ppw=3, block=1)]
        status, placements, _ = run_scheduler(
            a, _rooms(), {}, ["Mon", "Tue"], 3, None, None, time_limit_seconds=10)
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(len(placements), 3)
        # Every section-day of the produced schedule satisfies HN1.
        by_day = {}
        for p in placements:
            by_day.setdefault(p["day"], set()).update(
                range(p["start_period"], p["start_period"] + p["length"]))
        for day, occ in by_day.items():
            self.assertEqual(
                rules.check_max_two_theory(occ, 3, None, "S1", day, 1), [])

    def test_gap_inserted_when_room_allows(self):
        # 3 theory periods in a 4-period day: feasible only with a gap
        # (e.g. periods {0,1,3}); the solver must insert one.
        a = [_FakeAssignment(1, 1, "theory", section_id=1, ppw=3, block=1)]
        status, placements, _ = run_scheduler(
            a, _rooms(), {}, ["Mon"], 4, None, None, time_limit_seconds=10)
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        occ = set()
        for p in placements:
            occ.update(range(p["start_period"],
                             p["start_period"] + p["length"]))
        self.assertEqual(len(occ), 3)
        self.assertEqual(
            rules.check_max_two_theory(occ, 4, None, "S1", "Mon", 1), [])

    def test_length_two_coefficient_counts(self):
        # A length-2 block plus one more theory in the same window is
        # refused even though only two *blocks* are involved.
        a = [_FakeAssignment(1, 1, "theory", section_id=1, ppw=2, block=2),
             _FakeAssignment(2, 2, "theory", section_id=1, ppw=1, block=1)]
        status, placements, _ = run_scheduler(
            a, _rooms(), {}, ["Mon"], 3, None, None, time_limit_seconds=10)
        # Mon has one 3-window (0,1,2): 2+1=3 > 2, so single-day is refused;
        # the solver must fail here (no second day to spread onto).
        self.assertEqual(status, "INFEASIBLE")


def _snap_with_theory(mon_periods, day="Mon"):
    rooms = [SimpleNamespace(id=1, name="201", room_type="theory",
                             capacity=80, equipment_count=None),
             SimpleNamespace(id=2, name="401-A", room_type="lab",
                             capacity=35, equipment_count=35)]
    faculty = [SimpleNamespace(id=1, unavailable_slots=""),
               SimpleNamespace(id=2, unavailable_slots="")]
    sections = [SimpleNamespace(id=1, name="BCA-5-A", student_count=60),
                SimpleNamespace(id=2, name="BCA-5-B", student_count=60)]
    lab_groups = [SimpleNamespace(id=10, section_id=1)]
    assignments = [
        SimpleNamespace(id=100, faculty_id=1, session_type="theory",
                        section_id=1, lab_group_id=None,
                        section_name="BCA-5-A", section_size=60),
        SimpleNamespace(id=101, faculty_id=2, session_type="practical",
                        section_id=None, lab_group_id=10,
                        lab_group_name="BCA-5-A-G1", lab_group_size=30,
                        lab_group_section_id=1),
        SimpleNamespace(id=102, faculty_id=2, session_type="theory",
                        section_id=2, lab_group_id=None,
                        section_name="BCA-5-B", section_size=60),
    ]
    classes = [SimpleNamespace(id=1000 + i, assignment_id=100, day=day,
                               start_period=p, length=1, room_id=1)
               for i, p in enumerate(sorted(mon_periods))]
    return sv.build_snapshot(["Mon", "Tue"], 7, 4, 3, rooms, faculty,
                             lab_groups, sections, assignments, classes)


def _theory_candidate(snap, **kw):
    args = dict(session_type="theory", group_key="section:1",
                group_label="BCA-5-A", group_size=60, faculty_id=2,
                day="Mon", start_period=2, length=1, room_id=1)
    args.update(kw)
    return sv.validate_candidate(snap, **args)


class TestHn1Validator(unittest.TestCase):
    def test_third_consecutive_rejected(self):
        snap = _snap_with_theory([0, 1])
        fails = _theory_candidate(snap)
        codes = [f.code for f in fails if f.code == "MAX_TWO_THEORY"]
        self.assertEqual(len(codes), 1)
        det = [f.details for f in fails if f.code == "MAX_TWO_THEORY"][0]
        self.assertEqual(det["section_id"], 1)
        self.assertEqual(det["day"], "Mon")
        self.assertEqual(det["periods"], [0, 1, 2])

    def test_second_theory_allowed(self):
        snap = _snap_with_theory([0])
        self.assertEqual(
            [f for f in _theory_candidate(snap) if f.code == "MAX_TWO_THEORY"], [])

    def test_lab_candidate_ignores_hn1(self):
        snap = _snap_with_theory([0, 1])
        fails = sv.validate_candidate(
            snap, session_type="practical", group_key="labgroup:10",
            group_label="BCA-5-A-G1", group_size=30, faculty_id=2,
            day="Mon", start_period=2, length=1, room_id=2,
            parent_section_key="section:1")
        self.assertEqual(
            [f for f in fails if f.code == "MAX_TWO_THEORY"], [])

    def test_other_section_unaffected(self):
        snap = _snap_with_theory([0, 1])
        fails = _theory_candidate(snap, group_key="section:2",
                                  group_label="BCA-5-B")
        self.assertEqual(
            [f for f in fails if f.code == "MAX_TWO_THEORY"], [])

    def test_break_resets_streak(self):
        snap = _snap_with_theory([3])
        fails = _theory_candidate(snap, start_period=4)
        self.assertEqual(
            [f for f in fails if f.code == "MAX_TWO_THEORY"], [])

    def test_length_two_candidate_creates_streak(self):
        snap = _snap_with_theory([1])
        fails = _theory_candidate(snap, start_period=2, length=2)
        self.assertTrue(
            any(f.code == "MAX_TWO_THEORY" for f in fails))

    def test_move_revalidation_after_removal(self):
        snap = _snap_with_theory([0, 1, 2])
        slim = sv.snapshot_without(snap, 1002)  # drop period-2 theory
        # Re-placing at the same spot would recreate the streak...
        self.assertTrue(any(
            f.code == "MAX_TWO_THEORY" for f in _theory_candidate(slim)))
        # ...but the freed snapshot validates a clean placement elsewhere.
        fails = _theory_candidate(slim, day="Tue", start_period=0)
        self.assertEqual(
            [f for f in fails if f.code == "MAX_TWO_THEORY"], [])

    def test_theory_occ_recorded_and_removed(self):
        snap = _snap_with_theory([0, 1])
        self.assertEqual(snap.theory_occ.get(("section:1", "Mon", 0)), 1)
        slim = sv.snapshot_without(snap, 1000)
        self.assertNotIn(("section:1", "Mon", 0), slim.theory_occ)
        self.assertIn(("section:1", "Mon", 1), slim.theory_occ)


class TestHn1AuditScript(unittest.TestCase):
    """End-to-end: planted T+T+T schedule is flagged by the CLI audit."""

    def test_audit_flags_planted_streak(self):
        from flask import Flask
        from backend import models as m
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = os.path.join(tmp.name, "hn1.db")
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + db_path
        m.db.init_app(app)
        with app.app_context():
            m.db.create_all()
            m.db.session.add(m.Config(
                session_name="HN1", working_days="Mon,Tue",
                periods="|".join(f"p{i}" for i in range(7)),
                break_after_periods=4, max_consecutive_teaching=3))
            m.db.session.add(m.Program(id=1, name="BCA"))
            m.db.session.add(m.Enrollment(id=1, program_id=1,
                                          year_label="Y", total_students=60))
            m.db.session.add(m.Section(id=1, enrollment_id=1,
                                       name="BCA-5-A", student_count=60))
            m.db.session.add(m.Room(id=1, name="201", room_type="theory",
                                    capacity=80))
            m.db.session.add(m.Faculty(id=1, name="F1"))
            m.db.session.add(m.Subject(id=1, name="DSA", enrollment_id=1))
            m.db.session.add(m.TeachingAssignment(
                id=1, faculty_id=1, subject_id=1, session_type="theory",
                section_id=1, periods_per_week=3, block_length=1))
            for i, p in enumerate((0, 1, 2)):
                m.db.session.add(m.ScheduledClass(
                    id=10 + i, assignment_id=1, day="Mon",
                    start_period=p, length=1, room_id=1, run_id="t"))
            m.db.session.commit()
            m.db.session.remove()
            m.db.engine.dispose()
        env = dict(os.environ)
        repo = os.path.dirname(
            os.path.dirname(os.path.abspath(m.__file__)))
        proc = subprocess.run(
            [sys.executable, "-m", "backend.audit_schedule",
             "--db", db_path],
            capture_output=True, text=True, cwd=repo, env=env,
            timeout=120)
        self.assertIn("MAX_TWO_THEORY", proc.stdout)
        self.assertIn("[FAIL]", proc.stdout)


if __name__ == "__main__":
    unittest.main()
