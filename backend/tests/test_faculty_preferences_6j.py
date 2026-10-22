"""Phase 6J tests: faculty custom preferences (domain + scheduler + neutrality).

Covers the pure preference helpers (normalize/penalty/scale/validation),
the ORM service (create/update/delete/defaults/relationships), scheduler
integration (backward compat, satisfaction when feasible, violation when
necessary, hard-constraint dominance, locked blocks, specialization sync,
preferred-room coexistence, malformed-data safety), and proof that soft
preferences never leak into hard validation (manual moves, reassignment,
swaps stay governed by hard rules only).

Every DB-backed test uses throwaway SQLite files in a temp dir — never
the real database. Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_faculty_preferences_6j -v
"""
import os
import tempfile
import unittest
from types import SimpleNamespace

from backend.faculty_preferences import (
    SUPPORTED_KINDS,
    CleanPreference,
    PreferenceError,
    faculty_time_penalty,
    normalize_faculty_preferences,
    parse_days,
    validate_preference_payload,
)
from backend.scheduler import (
    faculty_time_scale,
    preferred_time_scale,
    run_scheduler,
)


DAYS = ["Mon", "Tue", "Wed"]
N_PERIODS = 7


def _pref(fid=1, kind="TIME_WINDOW", days="Mon,Tue", start=0, end=3,
          enabled=True, weight=5, is_hard=False):
    return SimpleNamespace(faculty_id=fid, kind=kind, days=days,
                           start_period=start, end_period=end,
                           weight=weight, is_hard=is_hard, enabled=enabled)


def _theory_rooms():
    return [SimpleNamespace(id=1, name="R101", room_type="theory",
                            capacity=100, equipment_count=None),
            SimpleNamespace(id=2, name="R102", room_type="theory",
                            capacity=100, equipment_count=None)]


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


class _FakeSpecAssignment:
    def __init__(self, aid, faculty_id, spec_id):
        self.id = aid
        self.faculty_id = faculty_id
        self.subject_id = 900 + aid
        self.session_type = "theory"
        self.specialization_id = spec_id
        self.periods_per_week = 1
        self.block_length = 1

    def group_label(self):
        return f"SPEC:{self.specialization_id}"


def _ok(status):
    return status in ("OPTIMAL", "FEASIBLE")


# ------------------------------------------------------- pure: parse_days
class TestParseDays(unittest.TestCase):
    def test_splits_and_cleans(self):
        self.assertEqual(parse_days("Mon, Tue,,Mon"), ["Mon", "Tue"])
        self.assertEqual(parse_days(""), [])
        self.assertEqual(parse_days(None), [])
        self.assertEqual(parse_days(123), [])


# ------------------------------------------------------- pure: normalize
class TestNormalize(unittest.TestCase):
    def test_keeps_valid_rows(self):
        rows = [_pref(1, "TIME_WINDOW", "Mon,Tue", 0, 3),
                _pref(2, "DAY_OFF_PREFERENCE", "Wed", None, None)]
        got = normalize_faculty_preferences(rows, DAYS, N_PERIODS)
        self.assertEqual(got[1], [{"kind": "TIME_WINDOW",
                                   "days": ["Mon", "Tue"],
                                   "start_period": 0, "end_period": 3}])
        self.assertEqual(got[2], [{"kind": "DAY_OFF_PREFERENCE",
                                   "days": ["Wed"],
                                   "start_period": None,
                                   "end_period": None}])

    def test_blank_days_means_all_working_days(self):
        got = normalize_faculty_preferences(
            [_pref(1, "TIME_WINDOW", "", 1, 4)], DAYS, N_PERIODS)
        self.assertEqual(got[1][0]["days"], DAYS)

    def test_drops_disabled_variants(self):
        for off in (False, 0, "false", "0", "no"):
            rows = [_pref(1, "TIME_WINDOW", "Mon", 0, 3, enabled=off)]
            self.assertEqual(
                normalize_faculty_preferences(rows, DAYS, N_PERIODS), {},
                f"enabled={off!r} should disable")
        for on in (True, 1, "true", None):
            rows = [_pref(1, "TIME_WINDOW", "Mon", 0, 3, enabled=on)]
            self.assertIn(
                1, normalize_faculty_preferences(rows, DAYS, N_PERIODS),
                f"enabled={on!r} should stay enabled")

    def test_drops_unknown_and_deferred_kinds(self):
        rows = [_pref(1, "SUBJECT_AFFINITY", "Mon", 0, 3),
                _pref(1, "NOPE", "Mon", 0, 3),
                _pref(1, None, "Mon", 0, 3)]
        self.assertEqual(
            normalize_faculty_preferences(rows, DAYS, N_PERIODS), {})

    def test_drops_bad_faculty_ids(self):
        rows = [_pref("x"), SimpleNamespace(kind="TIME_WINDOW")]
        self.assertEqual(
            normalize_faculty_preferences(rows, DAYS, N_PERIODS), {})

    def test_drops_bad_days(self):
        # Days given but none are working days.
        rows = [_pref(1, "TIME_WINDOW", "Sat,Sun", 0, 3)]
        self.assertEqual(
            normalize_faculty_preferences(rows, DAYS, N_PERIODS), {})
        # Unknown tokens filtered, known ones kept.
        rows = [_pref(1, "TIME_WINDOW", "Mon,Funday", 0, 3)]
        got = normalize_faculty_preferences(rows, DAYS, N_PERIODS)
        self.assertEqual(got[1][0]["days"], ["Mon"])
        # Day-off with no usable days is meaningless.
        rows = [_pref(1, "DAY_OFF_PREFERENCE", "", None, None)]
        self.assertEqual(
            normalize_faculty_preferences(rows, DAYS, N_PERIODS), {})

    def test_drops_impossible_ranges(self):
        bad = [(2, 2), (3, 2), (-1, 3), (0, 8), ("a", 3), (0, None),
               (None, None)]
        for start, end in bad:
            rows = [_pref(1, "TIME_WINDOW", "Mon", start, end)]
            self.assertEqual(
                normalize_faculty_preferences(rows, DAYS, N_PERIODS), {},
                f"range [{start}, {end}) should be dropped")
        # Boundary-valid ranges survive.
        for start, end in [(0, 1), (0, 7), (6, 7)]:
            rows = [_pref(1, "TIME_WINDOW", "Mon", start, end)]
            self.assertIn(
                1, normalize_faculty_preferences(rows, DAYS, N_PERIODS),
                f"range [{start}, {end}) should survive")

    def test_empty_and_junk_inputs(self):
        self.assertEqual(normalize_faculty_preferences(None, DAYS, N_PERIODS), {})
        self.assertEqual(normalize_faculty_preferences([], DAYS, N_PERIODS), {})
        self.assertEqual(normalize_faculty_preferences(
            [None, 42, "junk", object()], DAYS, N_PERIODS), {})

    def test_is_hard_and_weight_ignored_by_normalizer(self):
        # Soft-only phase: even a legacy is_hard row scores as soft.
        rows = [_pref(1, "TIME_WINDOW", "Mon", 0, 3, is_hard=True, weight=10)]
        got = normalize_faculty_preferences(rows, DAYS, N_PERIODS)
        self.assertIn(1, got)


# ------------------------------------------------------- pure: penalty
class TestPenalty(unittest.TestCase):
    def test_missing_prefs_neutral(self):
        self.assertEqual(faculty_time_penalty(1, "Mon", 0, 1, {}), 0)
        self.assertEqual(faculty_time_penalty(1, "Mon", 0, 1, None), 0)
        self.assertEqual(faculty_time_penalty(99, "Mon", 0, 1,
                                              {1: [{"kind": "TIME_WINDOW",
                                                    "days": ["Mon"],
                                                    "start_period": 0,
                                                    "end_period": 3}]}), 0)
        self.assertEqual(faculty_time_penalty(None, "Mon", 0, 1, {1: []}), 0)

    def test_time_window(self):
        prefs = normalize_faculty_preferences(
            [_pref(1, "TIME_WINDOW", "Mon,Tue", 1, 4)], DAYS, N_PERIODS)
        self.assertEqual(faculty_time_penalty(1, "Mon", 1, 2, prefs), 0)
        self.assertEqual(faculty_time_penalty(1, "Tue", 3, 1, prefs), 0)
        # Partial overlap still violates (any covered period outside).
        self.assertEqual(faculty_time_penalty(1, "Mon", 0, 2, prefs), 1)
        self.assertEqual(faculty_time_penalty(1, "Mon", 3, 2, prefs), 1)
        # Listed days only.
        self.assertEqual(faculty_time_penalty(1, "Wed", 2, 1, prefs), 1)

    def test_day_off(self):
        prefs = normalize_faculty_preferences(
            [_pref(1, "DAY_OFF_PREFERENCE", "Wed", None, None)],
            DAYS, N_PERIODS)
        self.assertEqual(faculty_time_penalty(1, "Wed", 0, 1, prefs), 1)
        self.assertEqual(faculty_time_penalty(1, "Wed", 5, 2, prefs), 1)
        self.assertEqual(faculty_time_penalty(1, "Mon", 0, 1, prefs), 0)

    def test_binary_cap_over_many_prefs(self):
        prefs = normalize_faculty_preferences(
            [_pref(1, "TIME_WINDOW", "Mon", 0, 1),
             _pref(1, "DAY_OFF_PREFERENCE", "Mon", None, None)],
            DAYS, N_PERIODS)
        for day, start in [("Mon", 0), ("Mon", 5), ("Tue", 0)]:
            self.assertIn(faculty_time_penalty(1, day, start, 1, prefs),
                          (0, 1))

    def test_malformed_placement_neutral(self):
        prefs = normalize_faculty_preferences(
            [_pref(1, "TIME_WINDOW", "Mon", 0, 3)], DAYS, N_PERIODS)
        self.assertEqual(faculty_time_penalty(1, "Mon", "x", 1, prefs), 0)


# ------------------------------------------------------- pure: scale
class TestFacultyTimeScale(unittest.TestCase):
    def test_scale_is_two_n_plus_one(self):
        self.assertEqual(faculty_time_scale(0), 1)
        self.assertEqual(faculty_time_scale(1), 3)
        self.assertEqual(faculty_time_scale(5), 11)

    def test_dominance_invariant(self):
        # Max combined secondary (room N x 1 + faculty N x 1 = 2N) is
        # always less than one start-period unit (K = 2N + 1).
        for n in (0, 1, 2, 7, 40):
            self.assertLess(2 * n, faculty_time_scale(n))

    def test_room_scale_unchanged(self):
        self.assertEqual(preferred_time_scale(5), 6)


# ------------------------------------------------------- pure: validation
class TestValidatePayload(unittest.TestCase):
    def test_valid_time_window_defaults(self):
        clean = validate_preference_payload(
            {"kind": "TIME_WINDOW", "days": "Mon,Tue",
             "start_period": 0, "end_period": 3}, DAYS, N_PERIODS)
        self.assertIsInstance(clean, CleanPreference)
        self.assertEqual((clean.kind, clean.days, clean.start_period,
                          clean.end_period, clean.weight, clean.enabled),
                         ("TIME_WINDOW", ["Mon", "Tue"], 0, 3, 5, True))

    def test_valid_day_off(self):
        clean = validate_preference_payload(
            {"kind": "DAY_OFF_PREFERENCE", "days": ["Wed"]}, DAYS, N_PERIODS)
        self.assertEqual((clean.days, clean.start_period, clean.end_period),
                         (["Wed"], None, None))

    def test_weight_boundaries(self):
        for w in (1, 10):
            clean = validate_preference_payload(
                {"kind": "DAY_OFF_PREFERENCE", "days": "Mon",
                 "weight": w}, DAYS, N_PERIODS)
            self.assertEqual(clean.weight, w)

    def _code(self, payload):
        with self.assertRaises(PreferenceError) as ctx:
            validate_preference_payload(payload, DAYS, N_PERIODS)
        return ctx.exception.to_payload()["code"]

    def test_unknown_kind(self):
        self.assertEqual(self._code({"kind": "NOPE"}), "PREF_INVALID_KIND")
        self.assertEqual(self._code({}), "PREF_INVALID_KIND")

    def test_deferred_kind_rejected_explicitly(self):
        code = self._code({"kind": "SUBJECT_AFFINITY"})
        self.assertEqual(code, "PREF_INVALID_KIND")

    def test_hard_rejected(self):
        self.assertEqual(self._code(
            {"kind": "DAY_OFF_PREFERENCE", "days": "Mon",
             "is_hard": True}), "PREF_HARD_UNSUPPORTED")

    def test_unknown_day(self):
        self.assertEqual(self._code(
            {"kind": "DAY_OFF_PREFERENCE",
             "days": "Mon,Funday"}), "PREF_INVALID_DAYS")

    def test_day_off_needs_days(self):
        self.assertEqual(self._code(
            {"kind": "DAY_OFF_PREFERENCE", "days": ""}), "PREF_INVALID_DAYS")

    def test_day_off_rejects_periods(self):
        self.assertEqual(self._code(
            {"kind": "DAY_OFF_PREFERENCE", "days": "Mon",
             "start_period": 0}), "PREF_INVALID_PERIOD")

    def test_window_needs_range(self):
        self.assertEqual(self._code(
            {"kind": "TIME_WINDOW", "days": "Mon"}), "PREF_INVALID_PERIOD")

    def test_window_impossible_range(self):
        self.assertEqual(self._code(
            {"kind": "TIME_WINDOW", "days": "Mon", "start_period": 3,
             "end_period": 3}), "PREF_INVALID_PERIOD")
        self.assertEqual(self._code(
            {"kind": "TIME_WINDOW", "days": "Mon", "start_period": 0,
             "end_period": 99}), "PREF_INVALID_PERIOD")

    def test_bad_weight(self):
        self.assertEqual(self._code(
            {"kind": "DAY_OFF_PREFERENCE", "days": "Mon",
             "weight": 99}), "PREF_INVALID_WEIGHT")
        self.assertEqual(self._code(
            {"kind": "DAY_OFF_PREFERENCE", "days": "Mon",
             "weight": 0}), "PREF_INVALID_WEIGHT")


# ------------------------------------------------------- ORM service
class ServiceBase(unittest.TestCase):
    """Throwaway Flask app + school (temp SQLite, never the real DB)."""

    def setUp(self):
        from flask import Flask
        from backend import models as m
        from backend import faculty_preferences as fp
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = (
            "sqlite:///" + os.path.join(self.tmp.name, "t6j.db"))
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.secret_key = "6j-test"
        m.db.init_app(self.app)
        self.m = m
        self.fp = fp
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        m.db.create_all()
        m.db.session.add(m.Config(
            session_name="6J", working_days="Mon,Tue,Wed",
            periods="|".join(f"p{i}" for i in range(7)),
            break_after_periods=4, max_consecutive_teaching=3))
        m.db.session.add(m.Program(id=1, name="BCA"))
        m.db.session.add(m.Enrollment(id=1, program_id=1, year_label="Y1",
                                      total_students=60))
        m.db.session.add(m.Section(id=1, enrollment_id=1, name="BCA-1-A",
                                   student_count=30))
        m.db.session.add(m.Section(id=2, enrollment_id=1, name="BCA-1-B",
                                   student_count=30))
        m.db.session.add(m.Room(id=1, name="R101", room_type="theory",
                                capacity=100))
        m.db.session.add(m.Room(id=2, name="R102", room_type="theory",
                                capacity=100))
        m.db.session.add(m.Faculty(id=1, name="F1", weekly_max_hours=24))
        m.db.session.add(m.Faculty(id=2, name="F2", weekly_max_hours=24))
        m.db.session.add(m.Subject(id=1, name="SUB1", enrollment_id=1))
        m.db.session.add(m.TeachingAssignment(
            id=1, faculty_id=1, subject_id=1, session_type="theory",
            section_id=1, periods_per_week=1, block_length=1))
        m.db.session.add(m.TeachingAssignment(
            id=2, faculty_id=2, subject_id=1, session_type="theory",
            section_id=2, periods_per_week=1, block_length=1))
        m.db.session.commit()

    def tearDown(self):
        try:
            self.m.db.session.remove()
            self.m.db.engine.dispose()
        except Exception:
            pass


class TestOrmService(ServiceBase):
    def test_create_list_update_delete(self):
        row = self.fp.create_preference(
            self.m.db, 1, {"kind": "TIME_WINDOW", "days": "Mon,Tue",
                           "start_period": 0, "end_period": 3})
        self.assertIsNotNone(row.id)
        self.assertEqual(row.faculty_id, 1)
        self.assertFalse(row.is_hard)
        self.assertTrue(row.enabled)

        rows = self.fp.list_for_faculty(self.m.db, 1)
        self.assertEqual([r.id for r in rows], [row.id])
        self.assertEqual(self.fp.list_for_faculty(self.m.db, 2), [])

        # Relationship resolves (faculty ownership for messages/audit).
        self.assertEqual(row.faculty.name, "F1")

        updated = self.fp.update_preference(
            self.m.db, row.id, {"days": "Wed"})
        self.assertEqual(updated.days, "Wed")
        self.assertEqual(updated.kind, "TIME_WINDOW")

        # Kind morph with explicit nulls clears the old range.
        morphed = self.fp.update_preference(
            self.m.db, row.id,
            {"kind": "DAY_OFF_PREFERENCE", "days": "Wed",
             "start_period": None, "end_period": None})
        self.assertEqual(morphed.kind, "DAY_OFF_PREFERENCE")
        self.assertIsNone(morphed.start_period)

        self.fp.delete_preference(self.m.db, row.id)
        self.assertEqual(self.fp.list_for_faculty(self.m.db, 1), [])

    def test_orm_defaults_match_model(self):
        row = self.m.FacultyPreference(faculty_id=1, kind="TIME_WINDOW")
        self.m.db.session.add(row)
        self.m.db.session.flush()
        self.assertEqual(row.weight, 5)
        self.assertFalse(row.is_hard)
        self.assertTrue(row.enabled)
        self.m.db.session.rollback()

    def test_unknown_faculty_and_preference(self):
        with self.assertRaises(PreferenceError) as ctx:
            self.fp.create_preference(
                self.m.db, 999, {"kind": "DAY_OFF_PREFERENCE",
                                 "days": "Mon"})
        self.assertEqual(ctx.exception.to_payload()["code"],
                         "UNKNOWN_FACULTY")
        with self.assertRaises(PreferenceError) as ctx:
            self.fp.update_preference(self.m.db, 999, {"days": "Mon"})
        self.assertEqual(ctx.exception.to_payload()["code"],
                         "UNKNOWN_PREFERENCE")
        with self.assertRaises(PreferenceError) as ctx:
            self.fp.delete_preference(self.m.db, 999)
        self.assertEqual(ctx.exception.to_payload()["code"],
                         "UNKNOWN_PREFERENCE")

    def test_create_validates(self):
        with self.assertRaises(PreferenceError) as ctx:
            self.fp.create_preference(
                self.m.db, 1, {"kind": "TIME_WINDOW", "days": "Mon",
                               "start_period": 5, "end_period": 5})
        self.assertEqual(ctx.exception.to_payload()["code"],
                         "PREF_INVALID_PERIOD")
        # Failed create persists nothing.
        self.assertEqual(self.fp.list_for_faculty(self.m.db, 1), [])

    def test_legacy_malformed_rows_survive_list_but_not_scheduler(self):
        # Hand-inserted junk the API would never accept (no kind CHECK in
        # the 6C table): list still returns it (authoritative data), the
        # scheduler normalizer drops it (neutral, no crash).
        self.m.db.session.add(self.m.FacultyPreference(
            faculty_id=1, kind="SUBJECT_AFFINITY", days="Mon",
            start_period=0, end_period=3))
        self.m.db.session.add(self.m.FacultyPreference(
            faculty_id=1, kind="TIME_WINDOW", days="Funday",
            start_period=0, end_period=99))
        self.m.db.session.commit()
        rows = self.fp.list_for_faculty(self.m.db, 1)
        self.assertEqual(len(rows), 2)
        sched = self.fp.query_scheduler_rows(self.m.db)
        self.assertEqual(
            normalize_faculty_preferences(sched, DAYS, N_PERIODS), {})


# ------------------------------------------------------- scheduler
class TestSchedulerBackwardCompat(unittest.TestCase):
    def test_no_prefs_identical(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        rooms = [SimpleNamespace(id=1, name="R101", room_type="theory",
                                 capacity=100, equipment_count=None)]
        expected = [{"assignment_id": 1, "day": "Mon", "start_period": 0,
                     "length": 1, "room_id": 1}]
        kw = dict(rooms=rooms, faculty_unavailable={}, days=["Mon"],
                  num_periods=1, break_after=None, max_consecutive=None,
                  time_limit_seconds=10)
        base = run_scheduler(a, **kw)
        none = run_scheduler(a, faculty_preferences=None, **kw)
        empty = run_scheduler(a, faculty_preferences=[], **kw)
        for status, placements, _ in (base, none, empty):
            self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
            self.assertEqual(placements, expected)


class TestPreferenceSatisfied(unittest.TestCase):
    def test_day_tie_broken_by_preference(self):
        # Mon P0 and Tue P0 tie on start cost; the Tue day-off... i.e. a
        # TIME_WINDOW for Tue only must pull the session to Tue.
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        prefs = [_pref(1, "TIME_WINDOW", "Tue", 0, 2)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon", "Tue"], 2, None, None,
            time_limit_seconds=10, faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual(len(placements), 1)
        self.assertEqual(placements[0]["day"], "Tue")
        self.assertEqual(placements[0]["start_period"], 0)

    def test_day_off_tie_broken_by_preference(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        prefs = [_pref(1, "DAY_OFF_PREFERENCE", "Mon", None, None)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon", "Tue"], 2, None, None,
            time_limit_seconds=10, faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual(placements[0]["day"], "Tue")

    def test_time_dominance_over_preference(self):
        # Window [2,4) can never outbid an earlier start: one start unit
        # (2N+1 = 3) outweighs the single penalty unit.
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        prefs = [_pref(1, "TIME_WINDOW", "Mon", 2, 4)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon"], 4, None, None,
            time_limit_seconds=10, faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual(placements[0]["start_period"], 0)


class TestPreferenceViolatedWhenNecessary(unittest.TestCase):
    def test_hard_availability_wins_over_soft_window(self):
        # Faculty unavailable Mon; window says Mon-only. The schedule must
        # still be feasible (on Tue), violating the soft pref.
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        prefs = [_pref(1, "TIME_WINDOW", "Mon", 0, 2)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {1: {"Mon:0", "Mon:1"}}, ["Mon", "Tue"],
            2, None, None, time_limit_seconds=10,
            faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual(len(placements), 1)
        self.assertEqual(placements[0]["day"], "Tue")

    def test_day_off_violated_when_only_day(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        prefs = [_pref(1, "DAY_OFF_PREFERENCE", "Mon", None, None)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon"], 1, None, None,
            time_limit_seconds=10, faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual(len(placements), 1)

    def test_malformed_rows_never_crash(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        junk = [None, 42, "x", object(),
                SimpleNamespace(faculty_id=1, kind="SUBJECT_AFFINITY"),
                {"faculty_id": 1, "kind": "TIME_WINDOW",
                 "days": "Mon", "start_period": "a", "end_period": []}]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon"], 1, None, None,
            time_limit_seconds=10, faculty_preferences=junk)
        self.assertTrue(_ok(status))
        self.assertEqual(len(placements), 1)


class TestLockedUnaffected(unittest.TestCase):
    def test_locked_placement_outside_window_stays(self):
        locked_asg = _FakeAssignment(9, 9, "theory", section_id=2)
        normal = _FakeAssignment(1, 1, "theory", section_id=1)
        locked = [{"locked_block_id": 7, "assignment_id": 9, "day": "Mon",
                   "start_period": 0, "length": 1, "room_id": 1,
                   "faculty_id": 9, "session_type": "theory",
                   "group_key": "section:2", "parent_section_key": None}]
        prefs = [_pref(9, "TIME_WINDOW", "Tue", 0, 3)]
        status, placements, _ = run_scheduler(
            [locked_asg, normal], _theory_rooms(), {}, ["Mon", "Tue"], 3,
            None, None, time_limit_seconds=10,
            locked_placements=locked, faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        # Locked assignment never re-emitted; normal session unaffected.
        self.assertEqual([p["assignment_id"] for p in placements], [1])


class TestSpecializationSync(unittest.TestCase):
    def test_sync_holds_with_faculty_prefs(self):
        normal = _FakeAssignment(1, 1, "theory", section_id=1)
        cyber = _FakeSpecAssignment(10, 3, 5)
        ai = _FakeSpecAssignment(11, 4, 6)
        spec_info = {
            5: {"enrollment_id": 1, "section_ids": [1],
                "total_students": 10, "session_type": "theory",
                "name": "Cyber"},
            6: {"enrollment_id": 1, "section_ids": [2],
                "total_students": 10, "session_type": "theory",
                "name": "AI"}}
        # Conflicting faculty day wishes must only rank synchronized
        # alternatives, never split the cohort.
        prefs = [_pref(3, "TIME_WINDOW", "Tue", 0, 3),
                 _pref(4, "DAY_OFF_PREFERENCE", "Tue", None, None)]
        status, placements, _ = run_scheduler(
            [normal, cyber, ai], _theory_rooms(), {}, ["Mon", "Tue"], 3,
            None, None, time_limit_seconds=15,
            specialization_data=spec_info, faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        by_assign = {}
        for p in placements:
            by_assign.setdefault(p["assignment_id"], []).append(
                (p["day"], p["start_period"], p["length"]))
        self.assertEqual(sorted(by_assign[10]), sorted(by_assign[11]))


class TestRoomCoexistence(unittest.TestCase):
    def test_room_and_faculty_prefs_combine(self):
        # Reversed room order: R102 first. Room pref wants R101, faculty
        # pref wants Tue; all starts tie at 0, so both secondaries apply.
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        rooms = list(reversed(_theory_rooms()))
        prefs = [_pref(1, "TIME_WINDOW", "Tue", 0, 2)]
        status, placements, _ = run_scheduler(
            a, rooms, {}, ["Mon", "Tue"], 2, None, None,
            time_limit_seconds=10, preferred_theory_rooms={1: 1},
            faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual(len(placements), 1)
        self.assertEqual((placements[0]["day"], placements[0]["room_id"]),
                         ("Tue", 1))

    def test_room_pref_still_applies_alone(self):
        # Faculty map present but for another faculty: room pref decides.
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        rooms = list(reversed(_theory_rooms()))
        prefs = [_pref(99, "DAY_OFF_PREFERENCE", "Mon", None, None)]
        status, placements, _ = run_scheduler(
            a, rooms, {}, ["Mon"], 1, None, None,
            time_limit_seconds=10, preferred_theory_rooms={1: 1},
            faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual(placements[0]["room_id"], 1)


# ------------------------------------------------------- hard-validation neutrality
class TestHardValidationNeutrality(ServiceBase):
    """Soft prefs never enter candidate validity (moves, reassign, swap)."""

    def setUp(self):
        super().setUp()
        # One placed class: A1 (F1) Mon P0 R101.
        self.m.db.session.add(self.m.ScheduledClass(
            id=1, assignment_id=1, day="Mon", start_period=0,
            length=1, room_id=1, run_id="run1"))
        self.m.db.session.commit()
        # F1 prefers Tue-only windows: the current placement violates it.
        self.fp.create_preference(
            self.m.db, 1, {"kind": "TIME_WINDOW", "days": "Tue",
                           "start_period": 0, "end_period": 7})

    def test_move_away_from_preference_valid(self):
        from backend import manual_edits as me
        # Mon P1 is neither preferred (Tue-only) — must still validate.
        res = me.validate_move_candidate(
            self.m.db, 1, day="Mon", start_period=1, room_id=1)
        self.assertTrue(res.ok)

    def test_move_into_preference_valid(self):
        from backend import manual_edits as me
        res = me.validate_move_candidate(
            self.m.db, 1, day="Tue", start_period=0, room_id=1)
        self.assertTrue(res.ok)

    def test_hard_conflict_still_fails(self):
        from backend import manual_edits as me
        # Occupy Tue P0 R101 with A2 first: moving A1 there must fail on
        # ROOM_CONFLICT regardless of preferences.
        self.m.db.session.add(self.m.ScheduledClass(
            id=2, assignment_id=2, day="Tue", start_period=0,
            length=1, room_id=1, run_id="run1"))
        self.m.db.session.commit()
        res = me.validate_move_candidate(
            self.m.db, 1, day="Tue", start_period=0, room_id=1)
        self.assertFalse(res.ok)
        self.assertIn(res.failures[0].code,
                      ("ROOM_CONFLICT", "GROUP_CONFLICT", "FACULTY_CONFLICT",
                       "SECTION_CONFLICT", "SPECIALIZATION_OVERLAP"))

    def test_reassignment_ignores_preference_mismatch(self):
        from backend import faculty_reassignment as fr
        # F2 has a Mon-only window; A1 sits Mon P0 (a match) — reassigning
        # must validate on hard rules. Then give F2 a Tue-only window and
        # show the placed Mon class still reassigns fine (mismatch ok).
        self.fp.create_preference(
            self.m.db, 2, {"kind": "TIME_WINDOW", "days": "Tue",
                           "start_period": 0, "end_period": 7})
        res = fr.validate_reassignment(self.m.db, 1, 2)
        self.assertTrue(res.ok, [f.code for f in res.failures])

    def test_swap_ignores_preferences(self):
        from backend import faculty_swaps as fs
        self.m.db.session.add(self.m.ScheduledClass(
            id=2, assignment_id=2, day="Tue", start_period=0,
            length=1, room_id=2, run_id="run1"))
        self.m.db.session.commit()
        self.fp.create_preference(
            self.m.db, 2, {"kind": "DAY_OFF_PREFERENCE", "days": "Tue",
                           "start_period": None, "end_period": None})
        res = fs.validate_faculty_swap(self.m.db, 1, 2)
        self.assertTrue(res.ok, [f.code for f in res.failures])


if __name__ == "__main__":
    unittest.main()
