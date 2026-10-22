"""Unit tests for the Phase 6C migration (additive schema only).

Uses throwaway SQLite files in a temp dir — never the real database.
"""
import importlib
import os
import sqlite3
import tempfile
import unittest


UP = importlib.import_module("backend.migrations.versions.6c_additive_schema")

OLD_TABLES = ["admin_user", "config", "enrollment", "faculty", "lab_group",
              "program", "room", "scheduled_class", "section", "subject",
              "teaching_assignment"]
NEW_TABLES = ["specialization", "specialization_membership",
              "specialization_slot", "locked_block", "faculty_preference"]


def _old_schema(con):
    con.execute("CREATE TABLE program (id INTEGER PRIMARY KEY, name VARCHAR(80), "
                "department VARCHAR(120))")
    con.execute("CREATE TABLE enrollment (id INTEGER PRIMARY KEY, program_id INTEGER, "
                "year_label VARCHAR(40), total_students INTEGER)")
    con.execute("CREATE TABLE section (id INTEGER PRIMARY KEY, enrollment_id INTEGER, "
                "name VARCHAR(80), student_count INTEGER)")
    con.execute("CREATE TABLE room (id INTEGER PRIMARY KEY, name VARCHAR(80), "
                "room_type VARCHAR(20), capacity INTEGER, equipment_count INTEGER)")
    con.execute("CREATE TABLE faculty (id INTEGER PRIMARY KEY, name VARCHAR(120), "
                "department VARCHAR(120), faculty_type VARCHAR(20), "
                "weekly_max_hours INTEGER, unavailable_slots TEXT)")
    con.execute("CREATE TABLE subject (id INTEGER PRIMARY KEY, code VARCHAR(40), "
                "name VARCHAR(200), enrollment_id INTEGER, credits INTEGER, "
                "theory_hours_per_week INTEGER, practical_hours_per_week INTEGER, "
                "practical_block_length INTEGER)")
    con.execute("CREATE TABLE lab_group (id INTEGER PRIMARY KEY, section_id INTEGER, "
                "name VARCHAR(80), student_count INTEGER)")
    con.execute("CREATE TABLE teaching_assignment (id INTEGER PRIMARY KEY, faculty_id INTEGER, "
                "subject_id INTEGER, session_type VARCHAR(20), section_id INTEGER, "
                "lab_group_id INTEGER, periods_per_week INTEGER, block_length INTEGER)")
    con.execute("CREATE TABLE scheduled_class (id INTEGER PRIMARY KEY, assignment_id INTEGER, "
                "day VARCHAR(10), start_period INTEGER, length INTEGER, "
                "room_id INTEGER, run_id VARCHAR(40))")
    con.execute("CREATE TABLE config (id INTEGER PRIMARY KEY, session_name VARCHAR(120), "
                "max_section_size INTEGER, max_lab_group_size INTEGER, "
                "working_days VARCHAR(120), periods TEXT, break_after_periods INTEGER, "
                "max_consecutive_teaching INTEGER)")
    con.execute("CREATE TABLE admin_user (id INTEGER PRIMARY KEY, username VARCHAR(80), "
                "password_hash VARCHAR(255))")
    con.execute("INSERT INTO program VALUES (1, 'BCA', NULL)")
    con.execute("INSERT INTO enrollment VALUES (1, 1, '1st Year', 60)")
    con.execute("INSERT INTO section VALUES (1, 1, 'BCA-1-A', 60)")
    con.execute("INSERT INTO room VALUES (1, '201', 'theory', 80, NULL)")
    con.execute("INSERT INTO faculty VALUES (1, 'Dr. X', NULL, 'regular', 24, '')")
    con.execute("INSERT INTO subject VALUES (1, 'BCA101', 'Prog', 1, 3, NULL, NULL, 2)")
    con.execute("INSERT INTO lab_group VALUES (1, 1, 'BCA-1-A-G1', 30)")
    con.execute("INSERT INTO teaching_assignment VALUES (1, 1, 1, 'theory', 1, NULL, 3, 1)")
    con.execute("INSERT INTO scheduled_class VALUES (1, 1, 'Mon', 0, 1, 1, 'run1')")
    con.execute("INSERT INTO config VALUES (1, 'S', 80, 40, 'Mon,Tue', 'a|b', 1, 3)")
    con.execute("INSERT INTO admin_user VALUES (1, 'admin', 'x')")
    con.commit()


class TestMigration6C(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        con = sqlite3.connect(self.db)
        _old_schema(con)
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def _counts(self):
        con = sqlite3.connect(self.db)
        try:
            tables = sorted(r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name NOT LIKE 'sqlite_%'"))
            counts = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                      for t in tables}
            return tables, counts, con
        except Exception:
            con.close()
            raise

    def test_upgrade_preserves_and_adds(self):
        con = sqlite3.connect(self.db)
        UP.upgrade(con)
        con.commit()
        con.close()
        tables, counts, con = self._counts()
        try:
            for t in OLD_TABLES:
                self.assertIn(t, tables)
            self.assertEqual(counts["scheduled_class"], 1)
            self.assertEqual(counts["teaching_assignment"], 1)
            self.assertEqual(counts["section"], 1)
            self.assertEqual(
                con.execute("SELECT name, student_count FROM section WHERE id=1").fetchone(),
                ("BCA-1-A", 60))
            self.assertEqual(
                con.execute("SELECT day, start_period FROM scheduled_class WHERE id=1").fetchone(),
                ("Mon", 0))
            for t in NEW_TABLES:
                self.assertIn(t, tables)
                self.assertEqual(counts[t], 0)
            cols = [r[1] for r in con.execute("PRAGMA table_info(section)")]
            self.assertIn("preferred_theory_room_id", cols)
            scols = [r[1] for r in con.execute("PRAGMA table_info(scheduled_class)")]
            for c in ("is_locked", "slot_id", "locked_block_id"):
                self.assertIn(c, scols)
            self.assertEqual(
                con.execute("SELECT is_locked FROM scheduled_class WHERE id=1").fetchone()[0], 0)
        finally:
            con.close()

    def test_downgrade_restores(self):
        con = sqlite3.connect(self.db)
        UP.upgrade(con)
        con.commit()
        UP.downgrade(con)
        con.commit()
        con.close()
        tables, counts, con = self._counts()
        try:
            for t in NEW_TABLES:
                self.assertNotIn(t, tables)
            self.assertEqual(counts["scheduled_class"], 1)
            self.assertEqual(counts["section"], 1)
            scols = [r[1] for r in con.execute("PRAGMA table_info(scheduled_class)")]
            self.assertNotIn("is_locked", scols)
        finally:
            con.close()

    def test_check_constraints_enforced(self):
        con = sqlite3.connect(self.db)
        UP.upgrade(con)
        con.commit()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO specialization_membership "
                            "(specialization_id, section_id, student_count) VALUES (1, 1, 0)")
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO faculty_preference "
                            "(faculty_id, kind, weight) VALUES (1, 'TIME_WINDOW', 99)")
        finally:
            con.close()


class TestNewModelDefaults(unittest.TestCase):
    def test_orm_defaults_on_fresh_db(self):
        from flask import Flask
        from backend import models as m
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(tmp.name, "n.db")
        m.db.init_app(app)
        with app.app_context():
            m.db.create_all()
            for t in NEW_TABLES:
                self.assertEqual(m.db.session.execute(
                    m.db.text(f'SELECT COUNT(*) FROM "{t}"')).scalar(), 0)
            sc = m.ScheduledClass(assignment_id=1, day="Mon", start_period=0,
                                  length=1, room_id=1)
            m.db.session.add(sc)
            m.db.session.flush()
            self.assertFalse(sc.is_locked)
            self.assertIsNone(sc.slot_id)
            fp = m.FacultyPreference(faculty_id=1, kind="TIME_WINDOW")
            m.db.session.add(fp)
            m.db.session.flush()
            self.assertEqual(fp.weight, 5)
            self.assertFalse(fp.is_hard)
            self.assertTrue(fp.enabled)
            m.db.session.rollback()
            m.db.session.remove()
            m.db.engine.dispose()  # release the sqlite file (Windows locks it)


if __name__ == "__main__":
    unittest.main()
