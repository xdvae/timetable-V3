"""Phase 6D.1 tests: HN1 capacity/demand diagnostic calculations.

Tests the pure planning primitives in schedule_rules.py (capacity bounds
derived from Config segments, per-section theory demand aggregation).
Does not alter any existing test behavior.

Run from the repository root:
    venv\\Scripts\\python.exe -m unittest discover -s backend\\tests -t .
"""
import itertools
import unittest
from types import SimpleNamespace

from backend import schedule_rules as rules


def _brute_capacity(length):
    """Ground truth by exhaustive search: max ones in a binary string of
    `length` with no three consecutive ones."""
    best = 0
    for mask in range(1 << length):
        ok = True
        run = 0
        for p in range(length):
            if mask & (1 << p):
                run += 1
                if run >= 3:
                    ok = False
                    break
            else:
                run = 0
        if ok:
            best = max(best, bin(mask).count("1"))
    return best


class TestSegmentCapacity(unittest.TestCase):
    def test_closed_form_matches_brute_force(self):
        for L in range(0, 11):
            self.assertEqual(rules.segment_theory_capacity(L),
                             _brute_capacity(L), f"L={L}")

    def test_spot_values(self):
        self.assertEqual(rules.segment_theory_capacity(3), 2)
        self.assertEqual(rules.segment_theory_capacity(4), 3)
        self.assertEqual(rules.segment_theory_capacity(7), 5)
        self.assertEqual(rules.segment_theory_capacity(0), 0)
        self.assertEqual(rules.segment_theory_capacity(-2), 0)


class TestCapacityFromConfig(unittest.TestCase):
    def test_no_break_is_single_segment(self):
        # 7 periods, no break -> one segment of 7 -> capacity 5.
        self.assertEqual(rules.hn1_daily_capacity(7, None), 5)
        self.assertEqual(rules.hn1_daily_capacity(7, 0), 5)
        self.assertEqual(rules.hn1_daily_capacity(7, 99), 5)

    def test_break_sums_segment_capacities(self):
        # break_after=4 -> [0..3] cap 3 + [4..6] cap 2 = 5.
        self.assertEqual(
            rules.hn1_daily_capacity(7, 4),
            rules.segment_theory_capacity(4) + rules.segment_theory_capacity(3))
        self.assertEqual(rules.hn1_daily_capacity(7, 4), 5)

    def test_weekly_capacity(self):
        self.assertEqual(rules.hn1_weekly_capacity(7, 4, 5), 25)
        self.assertEqual(rules.hn1_weekly_capacity(7, None, 6), 30)
        self.assertEqual(rules.hn1_weekly_capacity(7, 4, 0), 0)


class TestDemandAggregation(unittest.TestCase):
    def _rows(self):
        return [
            SimpleNamespace(session_type="theory", section_id=1,
                            periods_per_week=3, block_length=1),
            SimpleNamespace(session_type="theory", section_id=1,
                            periods_per_week=2, block_length=2),
            SimpleNamespace(session_type="theory", section_id=2,
                            periods_per_week=4, block_length=1),
            SimpleNamespace(session_type="practical", section_id=None,
                            periods_per_week=6, block_length=2),
            SimpleNamespace(session_type="theory", section_id=None,
                            periods_per_week=9, block_length=1),
        ]

    def test_theory_per_section(self):
        self.assertEqual(rules.section_theory_demand(self._rows()),
                         {1: 5, 2: 4})

    def test_multiperiod_counts_actual_periods(self):
        # periods_per_week already counts periods; a 2-period block
        # assignment with ppw=2 contributes 2, not 1.
        rows = [SimpleNamespace(session_type="theory", section_id=7,
                                periods_per_week=2, block_length=2)]
        self.assertEqual(rules.section_theory_demand(rows), {7: 2})

    def test_practicals_excluded(self):
        rows = [SimpleNamespace(session_type="practical", section_id=3,
                                periods_per_week=8, block_length=2)]
        self.assertEqual(rules.section_theory_demand(rows), {})


class TestViolationDetectionMatchesRule(unittest.TestCase):
    def test_detector_agrees_with_check(self):
        occ = {0, 1, 2, 4}
        found = rules.find_theory_streaks(occ, 7, 4)
        checked = rules.check_max_two_theory(occ, 7, 4, "S", "Mon", 1)
        self.assertEqual([r.details["periods"] for r in checked],
                         [list(w) for w in found])
        self.assertEqual(found, [(0, 1, 2)])


if __name__ == "__main__":
    unittest.main()
