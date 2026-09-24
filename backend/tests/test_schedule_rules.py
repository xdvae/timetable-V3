"""Unit tests for backend/schedule_rules.py (existing rules H1–H14 only).

Run from the repository root:
    venv\\Scripts\\python.exe -m unittest discover -s backend/tests -t . -v
"""
import unittest

from backend import schedule_rules as rules


class TestRoomCompatibility(unittest.TestCase):
    def test_theory_in_theory_room_ok(self):
        self.assertTrue(rules.check_room_compatible(
            "theory", 80, None, "theory", 60, "201", "BCA-1-A").ok)

    def test_capacity_violation(self):
        res = rules.check_room_compatible("theory", 50, None, "theory", 65, "201", "BCA-1-A")
        self.assertFalse(res.ok)
        self.assertEqual(res.code, "ROOM_CAPACITY")

    def test_capacity_boundary_ok(self):
        self.assertTrue(rules.check_room_compatible(
            "theory", 60, None, "theory", 60).ok)

    def test_type_mismatch(self):
        res = rules.check_room_compatible("theory", 200, None, "practical", 20, "101", "G1")
        self.assertFalse(res.ok)
        self.assertEqual(res.code, "ROOM_TYPE_MISMATCH")

    def test_lab_in_lab_room_ok(self):
        self.assertTrue(rules.check_room_compatible(
            "lab", 40, 40, "practical", 30).ok)

    def test_equipment_violation(self):
        res = rules.check_room_compatible("lab", 40, 20, "practical", 30, "401-A", "G1")
        self.assertFalse(res.ok)
        self.assertEqual(res.code, "ROOM_EQUIPMENT")

    def test_equipment_unset_allowed(self):
        self.assertTrue(rules.check_room_compatible(
            "lab", 40, None, "practical", 30).ok)

    def test_wanted_room_type(self):
        self.assertEqual(rules.wanted_room_type("practical"), "lab")
        self.assertEqual(rules.wanted_room_type("theory"), "theory")


class TestGeometry(unittest.TestCase):
    def test_valid_starts_avoids_break(self):
        # 7 periods, break after period index 4, length 2 -> start 3 spans (3<4<5).
        self.assertEqual(rules.valid_starts(2, 7, 4), [0, 1, 2, 4, 5])

    def test_valid_starts_no_break(self):
        self.assertEqual(rules.valid_starts(1, 7, None), [0, 1, 2, 3, 4, 5, 6])

    def test_valid_starts_full_day_block(self):
        self.assertEqual(rules.valid_starts(7, 7, 4), [])

    def test_break_span_detected(self):
        res = rules.check_break_geometry(3, 2, 4, "BCA-1-A")
        self.assertFalse(res.ok)
        self.assertEqual(res.code, "BREAK_SPAN")

    def test_break_boundary_ok(self):
        # ends exactly at the break -> fine
        self.assertTrue(rules.check_break_geometry(2, 2, 4).ok)
        # starts exactly at the break -> fine
        self.assertTrue(rules.check_break_geometry(4, 2, 4).ok)

    def test_block_out_of_range(self):
        res = rules.check_block_geometry(6, 2, 7)
        self.assertFalse(res.ok)
        self.assertEqual(res.code, "PERIOD_OUT_OF_RANGE")

    def test_block_geometry_ok(self):
        self.assertTrue(rules.check_block_geometry(5, 2, 7).ok)

    def test_unknown_day(self):
        res = rules.check_day_known("Sun", ["Mon", "Tue"])
        self.assertFalse(res.ok)
        self.assertEqual(res.code, "UNKNOWN_DAY")
        self.assertTrue(rules.check_day_known("Mon", ["Mon", "Tue"]).ok)

    def test_spans_break_none_break(self):
        self.assertFalse(rules.spans_break(3, 2, None))


class TestAvailability(unittest.TestCase):
    def test_slot_key_format(self):
        self.assertEqual(rules.slot_key("Mon", 0), "Mon:0")

    def test_available(self):
        self.assertTrue(rules.is_faculty_available({"Mon:5"}, "Mon", 0, 2))

    def test_unavailable_overlap(self):
        res = rules.check_faculty_available({"Mon:1"}, "Mon", 0, 2, "Dr. X")
        self.assertFalse(res.ok)
        self.assertEqual(res.code, "FACULTY_UNAVAILABLE")

    def test_unavailable_elsewhere_ok(self):
        self.assertTrue(rules.check_faculty_available({"Tue:1"}, "Mon", 0, 2).ok)


class TestAssignmentRule(unittest.TestCase):
    def test_block_length_ok(self):
        self.assertTrue(rules.check_assignment_block_length(2, 2).ok)

    def test_block_length_exceeds(self):
        res = rules.check_assignment_block_length(3, 2)
        self.assertFalse(res.ok)
        self.assertEqual(res.code, "BLOCK_LENGTH_INVALID")

    def test_block_length_zero(self):
        self.assertFalse(rules.check_assignment_block_length(0, 3).ok)


class TestOccupancy(unittest.TestCase):
    def test_no_overlap(self):
        occ = {}
        rules.add_placement(occ, 1, "Mon", 0, 2)
        rules.add_placement(occ, 2, "Mon", 0, 1)
        self.assertEqual(rules.find_overlaps(occ), [])
        self.assertEqual(rules.check_no_overlap(occ, "ROOM_CONFLICT", "Room"), [])

    def test_room_overlap(self):
        occ = {}
        rules.add_placement(occ, 1, "Mon", 0, 1)
        rules.add_placement(occ, 1, "Mon", 0, 1)
        self.assertEqual(rules.find_overlaps(occ), [(1, "Mon", 0)])
        res = rules.check_no_overlap(occ, "ROOM_CONFLICT", "Room")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].code, "ROOM_CONFLICT")

    def test_multiblock_overlap_single_cell(self):
        occ = {}
        rules.add_placement(occ, 1, "Mon", 0, 2)
        rules.add_placement(occ, 1, "Mon", 1, 2)
        self.assertEqual(rules.find_overlaps(occ), [(1, "Mon", 1)])

    def test_hierarchy_overlap(self):
        lab_periods = {10: {("Mon", 1), ("Tue", 2)}}
        sec_periods = {5: {("Mon", 1), ("Mon", 3)}}
        out = rules.find_hierarchy_overlaps(lab_periods, sec_periods, {10: 5})
        self.assertEqual(out, [(10, 5, ("Mon", 1))])

    def test_hierarchy_no_overlap(self):
        out = rules.find_hierarchy_overlaps({10: {("Mon", 1)}}, {5: {("Mon", 2)}}, {10: 5})
        self.assertEqual(out, [])

    def test_parallel_lab_groups_do_not_overlap(self):
        # different group keys never collide in one occupancy map
        occ = {}
        rules.add_placement(occ, "labgroup:1", "Mon", 0, 2)
        rules.add_placement(occ, "labgroup:2", "Mon", 0, 2)
        self.assertEqual(rules.find_overlaps(occ), [])


class TestConsecutive(unittest.TestCase):
    def test_within_limit(self):
        self.assertTrue(rules.check_faculty_consecutive([0, 1, 2], 3, faculty_id=1).ok)

    def test_exceeds_limit(self):
        res = rules.check_faculty_consecutive([0, 1, 2, 3], 3, faculty_id=1, day="Mon")
        self.assertFalse(res.ok)
        self.assertEqual(res.code, "FACULTY_CONSECUTIVE")

    def test_gap_resets_run(self):
        self.assertTrue(rules.check_faculty_consecutive([0, 1, 3, 4, 5], 3).ok)

    def test_disabled_limit(self):
        self.assertTrue(rules.check_faculty_consecutive(list(range(7)), 0).ok)
        self.assertTrue(rules.check_faculty_consecutive(list(range(7)), None).ok)

    def test_max_run_length(self):
        self.assertEqual(rules.max_run_length([]), 0)
        self.assertEqual(rules.max_run_length([2]), 1)
        self.assertEqual(rules.max_run_length([0, 1, 2]), 3)


class TestCoverage(unittest.TestCase):
    def test_exact_coverage_ok(self):
        self.assertEqual(rules.check_session_coverage({1: 2, 2: 1}, {1: 2, 2: 1}), [])

    def test_mismatch_reported(self):
        res = rules.check_session_coverage({1: 2}, {1: 1})
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].code, "COVERAGE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
