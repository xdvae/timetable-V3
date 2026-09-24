"""Unit tests for backend/schedule_validator.py snapshot foundation."""
import unittest
from types import SimpleNamespace

from backend import schedule_validator as sv


def _rows():
    rooms = [SimpleNamespace(id=1, name="201", room_type="theory", capacity=80,
                             equipment_count=None),
             SimpleNamespace(id=2, name="401-A", room_type="lab", capacity=35,
                             equipment_count=35)]
    faculty = [SimpleNamespace(id=1, unavailable_slots="Mon:5"),
               SimpleNamespace(id=2, unavailable_slots="")]
    sections = [SimpleNamespace(id=1, name="BCA-1-A", student_count=60)]
    lab_groups = [SimpleNamespace(id=10, section_id=1),
                  SimpleNamespace(id=11, section_id=1)]
    assignments = [
        SimpleNamespace(id=100, faculty_id=1, session_type="theory", section_id=1,
                        lab_group_id=None, section_name="BCA-1-A", section_size=60),
        SimpleNamespace(id=101, faculty_id=2, session_type="practical", section_id=None,
                        lab_group_id=10, lab_group_name="BCA-1-A-G1", lab_group_size=30,
                        lab_group_section_id=1),
    ]
    classes = [SimpleNamespace(id=1000, assignment_id=100, day="Mon",
                               start_period=0, length=1, room_id=1)]
    return rooms, faculty, lab_groups, sections, assignments, classes


def _snap():
    rooms, faculty, lab_groups, sections, assignments, classes = _rows()
    return sv.build_snapshot(["Mon", "Tue"], 7, 4, 3, rooms, faculty,
                             lab_groups, sections, assignments, classes)


class TestSnapshot(unittest.TestCase):
    def test_occupancy_recorded(self):
        snap = _snap()
        self.assertEqual(snap.room_occ.get((1, "Mon", 0)), 1)
        self.assertEqual(snap.faculty_occ.get((1, "Mon", 0)), 1)
        self.assertEqual(snap.group_occ.get(("section:1", "Mon", 0)), 1)

    def test_group_keys(self):
        snap = _snap()
        self.assertEqual(snap.assignments[100]["group_key"], "section:1")
        self.assertEqual(snap.assignments[101]["group_key"], "labgroup:10")
        self.assertEqual(snap.assignments[101]["parent_section_key"], "section:1")

    def test_snapshot_without_removes_class(self):
        snap = _snap()
        slim = sv.snapshot_without(snap, 1000)
        self.assertNotIn(1000, slim.classes)
        self.assertNotIn((1, "Mon", 0), slim.room_occ)
        # original untouched
        self.assertIn(1000, snap.classes)

    def test_snapshot_without_unknown_id(self):
        snap = _snap()
        slim = sv.snapshot_without(snap, 9999)
        self.assertEqual(slim.room_occ, snap.room_occ)


class TestValidateCandidate(unittest.TestCase):
    def test_valid_free_slot(self):
        snap = _snap()
        fails = sv.validate_candidate(
            snap, session_type="theory", group_key="section:1", group_label="BCA-1-A",
            group_size=60, faculty_id=2, day="Mon", start_period=1, length=1, room_id=1)
        self.assertEqual(fails, [])

    def test_room_conflict(self):
        snap = _snap()
        fails = sv.validate_candidate(
            snap, session_type="theory", group_key="section:1", group_label="BCA-1-A",
            group_size=60, faculty_id=2, day="Mon", start_period=0, length=1, room_id=1)
        self.assertTrue(any(f.code == "ROOM_CONFLICT" for f in fails))

    def test_faculty_conflict(self):
        snap = _snap()
        fails = sv.validate_candidate(
            snap, session_type="theory", group_key="section:1", group_label="BCA-1-A",
            group_size=10, faculty_id=1, day="Mon", start_period=0, length=1, room_id=1,
            faculty_name="F1")
        codes = {f.code for f in fails}
        self.assertIn("FACULTY_CONFLICT", codes)

    def test_group_conflict(self):
        snap = _snap()
        fails = sv.validate_candidate(
            snap, session_type="theory", group_key="section:1", group_label="BCA-1-A",
            group_size=10, faculty_id=2, day="Mon", start_period=0, length=1, room_id=1)
        self.assertTrue(any(f.code == "GROUP_CONFLICT" for f in fails))

    def test_move_validated_against_snapshot_without_self(self):
        snap = sv.snapshot_without(_snap(), 1000)
        fails = sv.validate_candidate(
            snap, session_type="theory", group_key="section:1", group_label="BCA-1-A",
            group_size=60, faculty_id=1, day="Tue", start_period=2, length=1, room_id=1,
            faculty_name="F1")
        self.assertEqual(fails, [])

    def test_break_span_rejected(self):
        snap = _snap()
        fails = sv.validate_candidate(
            snap, session_type="theory", group_key="section:1", group_label="BCA-1-A",
            group_size=10, faculty_id=2, day="Mon", start_period=3, length=2, room_id=1)
        self.assertTrue(any(f.code == "BREAK_SPAN" for f in fails))

    def test_faculty_unavailable_rejected(self):
        snap = _snap()
        fails = sv.validate_candidate(
            snap, session_type="theory", group_key="section:1", group_label="BCA-1-A",
            group_size=10, faculty_id=1, day="Mon", start_period=5, length=1, room_id=1,
            faculty_name="F1")
        self.assertTrue(any(f.code == "FACULTY_UNAVAILABLE" for f in fails))

    def test_room_capacity_rejected(self):
        snap = _snap()
        fails = sv.validate_candidate(
            snap, session_type="theory", group_key="section:1", group_label="BCA-1-A",
            group_size=200, faculty_id=2, day="Tue", start_period=0, length=1, room_id=1)
        self.assertTrue(any(f.code == "ROOM_CAPACITY" for f in fails))

    def test_lab_in_theory_room_rejected(self):
        snap = _snap()
        fails = sv.validate_candidate(
            snap, session_type="practical", group_key="labgroup:10",
            group_label="BCA-1-A-G1", group_size=30, faculty_id=2, day="Tue",
            start_period=0, length=2, room_id=1, parent_section_key="section:1")
        self.assertTrue(any(f.code == "ROOM_TYPE_MISMATCH" for f in fails))

    def test_lab_group_vs_section_theory_hierarchy(self):
        snap = _snap()  # section:1 theory occupies Mon period 0
        fails = sv.validate_candidate(
            snap, session_type="practical", group_key="labgroup:10",
            group_label="BCA-1-A-G1", group_size=30, faculty_id=2, day="Mon",
            start_period=0, length=2, room_id=2, parent_section_key="section:1")
        self.assertTrue(any(f.code == "SECTION_HIERARCHY_CONFLICT" for f in fails))

    def test_unknown_room(self):
        snap = _snap()
        fails = sv.validate_candidate(
            snap, session_type="theory", group_key="section:1", group_label="BCA-1-A",
            group_size=10, faculty_id=2, day="Tue", start_period=0, length=1, room_id=999)
        self.assertEqual([f.code for f in fails], ["UNKNOWN_ROOM"])


if __name__ == "__main__":
    unittest.main()
