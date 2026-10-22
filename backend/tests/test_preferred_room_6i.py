"""Phase 6I.2 tests: preferred theory room scheduler objective.

Covers backward compatibility (None/omitted/empty map), preferred-room
selection on tied starts, start-time dominance over the preference
(the critical lexicographic test), occupied/incompatible/missing
preference fallback, no-preference validity, lab exclusion,
specialization exclusion, locked-placement exclusion, shared-room soft
competition, plus pure unit tests for the penalty/normalizer/scale
helpers (including the K = N + 1 dominance invariant).

Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_preferred_room_6i -v
"""
import unittest
from types import SimpleNamespace

from backend.scheduler import (
    normalize_preferred_rooms,
    preferred_room_penalty,
    preferred_time_scale,
    run_scheduler,
)


def _theory_rooms():
    return [SimpleNamespace(id=1, name="R101", room_type="theory",
                            capacity=100, equipment_count=None),
            SimpleNamespace(id=2, name="R102", room_type="theory",
                            capacity=100, equipment_count=None)]


def _rooms_with_lab():
    return _theory_rooms() + [SimpleNamespace(
        id=3, name="L1", room_type="lab", capacity=40,
        equipment_count=40)]


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


def _spec_info():
    return {5: {"enrollment_id": 1, "section_ids": [1],
                "total_students": 10, "session_type": "theory",
                "name": "Cyber"},
            6: {"enrollment_id": 1, "section_ids": [2],
                "total_students": 10, "session_type": "theory",
                "name": "AI"}}


def _ok(status):
    return status in ("OPTIMAL", "FEASIBLE")


# ------------------------------------------------------- pure helpers
class TestPenaltyHelper(unittest.TestCase):
    def test_theory_match_zero(self):
        sess = {"session_type": "theory", "group_key": "section:1"}
        self.assertEqual(preferred_room_penalty(sess, 7, {1: 7}), 0)

    def test_theory_other_one(self):
        sess = {"session_type": "theory", "group_key": "section:1"}
        self.assertEqual(preferred_room_penalty(sess, 8, {1: 7}), 1)

    def test_no_map_zero(self):
        sess = {"session_type": "theory", "group_key": "section:1"}
        self.assertEqual(preferred_room_penalty(sess, 8, {}), 0)
        self.assertEqual(preferred_room_penalty(sess, 8, None), 0)

    def test_unmapped_section_zero(self):
        sess = {"session_type": "theory", "group_key": "section:1"}
        self.assertEqual(preferred_room_penalty(sess, 8, {2: 8}), 0)

    def test_practical_never_penalized(self):
        sess = {"session_type": "practical", "group_key": "labgroup:10"}
        self.assertEqual(preferred_room_penalty(sess, 3, {1: 3}), 0)

    def test_specialization_never_penalized(self):
        sess = {"session_type": "theory", "group_key": "specialization:5"}
        self.assertEqual(preferred_room_penalty(sess, 3, {1: 3}), 0)

    def test_malformed_group_key_zero(self):
        for key in ("", "section:", "section:X", "other:1"):
            sess = {"session_type": "theory", "group_key": key}
            self.assertEqual(preferred_room_penalty(sess, 1, {1: 1}), 0)

    def test_penalty_is_binary(self):
        sess = {"session_type": "theory", "group_key": "section:1"}
        for room in (1, 2, 99):
            self.assertIn(preferred_room_penalty(sess, room, {1: 1}), (0, 1))


class TestNormalizeHelper(unittest.TestCase):
    def test_keeps_valid(self):
        rooms = _theory_rooms()
        self.assertEqual(normalize_preferred_rooms({1: 1, 2: 2}, rooms),
                         {1: 1, 2: 2})

    def test_drops_missing_and_junk(self):
        rooms = _theory_rooms()
        # None value, unknown room id, non-integer keys/values.
        self.assertEqual(normalize_preferred_rooms(
            {1: None, 2: 999, "x": 1, 3: "y", 4: 2}, rooms), {4: 2})

    def test_empty_inputs(self):
        self.assertEqual(normalize_preferred_rooms(None, _theory_rooms()),
                         {})
        self.assertEqual(normalize_preferred_rooms({}, _theory_rooms()), {})
        self.assertEqual(normalize_preferred_rooms({1: 1}, []), {})


class TestTimeScale(unittest.TestCase):
    def test_scale_is_sessions_plus_one(self):
        self.assertEqual(preferred_time_scale(0), 1)
        self.assertEqual(preferred_time_scale(1), 2)
        self.assertEqual(preferred_time_scale(5), 6)

    def test_dominance_invariant(self):
        # Max total preferred penalty (N x 1) is always less than one
        # start-period unit (K = N + 1): time-compactness strictly
        # dominates, by construction, for every N >= 0.
        for n in (0, 1, 2, 7, 40):
            self.assertLess(n, preferred_time_scale(n))


# ------------------------------------------------------- integration
class TestBackwardCompat(unittest.TestCase):
    """A: omitted / None / {} maps all behave exactly as before."""

    def test_identical_unique_solution(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        rooms = [SimpleNamespace(id=1, name="R101", room_type="theory",
                                 capacity=100, equipment_count=None)]
        expected = [{"assignment_id": 1, "day": "Mon", "start_period": 0,
                     "length": 1, "room_id": 1}]
        base = run_scheduler(a, rooms, {}, ["Mon"], 1, None, None,
                             time_limit_seconds=10)
        none = run_scheduler(a, rooms, {}, ["Mon"], 1, None, None,
                             time_limit_seconds=10,
                             preferred_theory_rooms=None)
        empty = run_scheduler(a, rooms, {}, ["Mon"], 1, None, None,
                              time_limit_seconds=10,
                              preferred_theory_rooms={})
        for status, placements, _ in (base, none, empty):
            self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
            self.assertEqual(placements, expected)


class TestPreferredSelected(unittest.TestCase):
    """B: preferred room wins among time-equal candidates (listed last)."""

    def test_preferred_room_chosen(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        rooms = list(reversed(_theory_rooms()))  # R102 first, R101 last
        status, placements, _ = run_scheduler(
            a, rooms, {}, ["Mon"], 2, None, None, time_limit_seconds=10,
            preferred_theory_rooms={1: 1})
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(len(placements), 1)
        self.assertEqual(placements[0]["room_id"], 1)
        self.assertEqual(placements[0]["start_period"], 0)


class TestStartDominance(unittest.TestCase):
    """C+I: earlier start beats the preferred room; locked rows untouched.

    R101 (preferred) is pinned at Mon P0 by a locked block, so the only
    time-optimal placement is Mon P0 R102. Under a fixed-constant
    weighting this would tie with Mon P1 R101; the K = N + 1 scale makes
    the earlier start strictly better.
    """

    def test_earlier_start_wins(self):
        locked_asg = _FakeAssignment(9, 9, "theory", section_id=2)
        normal = _FakeAssignment(1, 1, "theory", section_id=1)
        locked = [{"locked_block_id": 7, "assignment_id": 9, "day": "Mon",
                   "start_period": 0, "length": 1, "room_id": 1,
                   "faculty_id": 9, "session_type": "theory",
                   "group_key": "section:2", "parent_section_key": None}]
        status, placements, _ = run_scheduler(
            [locked_asg, normal], _theory_rooms(), {}, ["Mon"], 3, None,
            None, time_limit_seconds=10, locked_placements=locked,
            preferred_theory_rooms={1: 1})
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(len(placements), 1)
        # Locked assignment is never re-emitted; the normal session takes
        # the earlier start in the other room instead of waiting for R101.
        self.assertEqual(placements[0]["assignment_id"], 1)
        self.assertEqual((placements[0]["day"],
                          placements[0]["start_period"],
                          placements[0]["room_id"]), ("Mon", 0, 2))


class TestOccupiedFallback(unittest.TestCase):
    """D+J: shared preferred room is soft competition, never a conflict."""

    def test_one_period_two_sections(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1),
             _FakeAssignment(2, 2, "theory", section_id=2)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon"], 1, None, None,
            time_limit_seconds=10, preferred_theory_rooms={1: 1, 2: 1})
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(len(placements), 2)
        # Feasible with exactly one session in the shared preferred room
        # (either section may win; no priority tiers in 6I.2).
        self.assertEqual(sorted(p["room_id"] for p in placements), [1, 2])


class TestIncompatiblePreference(unittest.TestCase):
    """E: unknown or incompatible preferred rooms never block scheduling."""

    def test_unknown_room_id(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon"], 2, None, None,
            time_limit_seconds=10, preferred_theory_rooms={1: 999})
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(len(placements), 1)
        self.assertIn(placements[0]["room_id"], (1, 2))

    def test_lab_room_preferred_for_theory(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        status, placements, _ = run_scheduler(
            a, _rooms_with_lab(), {}, ["Mon"], 2, None, None,
            time_limit_seconds=10, preferred_theory_rooms={1: 3})
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(len(placements), 1)
        # The lab stays filtered by hard compatibility; schedule lands in
        # an ordinary theory room.
        self.assertIn(placements[0]["room_id"], (1, 2))


class TestNoPreference(unittest.TestCase):
    """F: null preference behaves exactly like today (valid placements)."""

    def test_none_map_valid(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1, ppw=2, block=1),
             _FakeAssignment(2, 2, "theory", section_id=2, ppw=1, block=1)]
        by_room = {r.id: r for r in _theory_rooms()}
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon", "Tue"], 3, None, None,
            time_limit_seconds=10, preferred_theory_rooms=None)
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(len(placements), 3)
        for p in placements:
            room = by_room[p["room_id"]]
            self.assertEqual(room.room_type, "theory")
            self.assertGreaterEqual(room.capacity, 30)


class TestLabExclusion(unittest.TestCase):
    """G: practical sessions never receive the theory preference."""

    def test_lab_placement_unchanged(self):
        lab = _FakeAssignment(4, 2, "practical", section_id=1,
                              lab_group_id=10)
        rooms = [SimpleNamespace(id=1, name="R101", room_type="theory",
                                 capacity=100, equipment_count=None),
                 SimpleNamespace(id=3, name="L1", room_type="lab",
                                 capacity=40, equipment_count=40)]
        kw = dict(days=["Mon"], num_periods=2, break_after=None,
                  max_consecutive=None, time_limit_seconds=10)
        base = run_scheduler([lab], rooms, {}, **kw)
        pref = run_scheduler([lab], rooms, {}, preferred_theory_rooms={1: 1},
                             **kw)
        for status, placements, _ in (base, pref):
            self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        # Identical solution with and without the map; lab stays in labs.
        self.assertEqual(base[1], pref[1])
        self.assertEqual(pref[1][0]["room_id"], 3)


class TestSpecializationExclusion(unittest.TestCase):
    """H: spec sessions are never preference-penalized; sync unchanged."""

    def test_sync_and_feasibility_with_map(self):
        normal = _FakeAssignment(1, 1, "theory", section_id=1)
        cyber = _FakeSpecAssignment(10, 3, 5)
        ai = _FakeSpecAssignment(11, 4, 6)
        status, placements, _ = run_scheduler(
            [normal, cyber, ai], _theory_rooms(), {}, ["Mon", "Tue"], 3,
            None, None, time_limit_seconds=15,
            specialization_data=_spec_info(),
            preferred_theory_rooms={1: 1, 2: 2})
        self.assertIn(status, ("OPTIMAL", "FEASIBLE"))
        by_assign = {}
        for p in placements:
            by_assign.setdefault(p["assignment_id"], []).append(
                (p["day"], p["start_period"], p["length"]))
            self.assertIn(p["room_id"], (1, 2))
        # Cohort synchronization holds with the map enabled.
        self.assertEqual(sorted(by_assign[10]), sorted(by_assign[11]))


if __name__ == "__main__":
    unittest.main()
