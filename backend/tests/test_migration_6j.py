"""Unit tests for the Phase 6J migration (additive, idempotent).

Covers upgrade on a pre-6C database (no faculty_preference table),
upgrade idempotence on a hybrid database (table present, index absent),
downgrade (index removed, 6C-owned table + rows preserved), schedule-row
immutability, the weight CHECK parity with the ORM model, and registry
chain integrity (6j sits on 6f_specializations; full upgrade applies).

Uses throwaway SQLite files in a temp dir — never the real database.
Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_migration_6j -v
"""
import importlib
import os
import sqlite3
import tempfile
import unittest


UP = importlib.import_module(
    "backend.migrations.versions.6j_faculty_preferences")


def _old_schema(con):
    """Pre-6C schema (no faculty_preference table), with schedule rows."""
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
    con.execute("INSERT INTO faculty VALUES (1, 'Dr. X', NULL, 'regular', 24, '')")
    con.execute("INSERT INTO section VALUES (1, 1, 'BCA-1-A', 60)")
    con.execute("INSERT INTO room VALUES (1, '201', 'theory', 80, NULL)")
    con.execute("INSERT INTO teaching_assignment VALUES (1, 1, 1, 'theory', 1, NULL, 3, 1)")
    con.execute("INSERT INTO scheduled_class VALUES (1, 1, 'Mon', 0, 1, 1, 'run1')")
    con.execute("INSERT INTO scheduled_class VALUES (2, 1, 'Tue', 2, 1, 1, 'run1')")
    con.commit()


def _table_cols(con, table):
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def _full_dump(con):
    tables = sorted(r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'"))
    return {t: con.execute(f'SELECT * FROM "{t}" ORDER BY 1').fetchall()
            for t in tables}


class TestMigration6J(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "t.db")
        con = sqlite3.connect(self.db)
        _old_schema(con)
        con.close()

    def test_upgrade_from_old_schema(self):
        con = sqlite3.connect(self.db)
        before = con.execute(
            "SELECT * FROM scheduled_class ORDER BY id").fetchall()
        UP.upgrade(con)
        con.commit()
        try:
            tables = sorted(r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"))
            self.assertIn("faculty_preference", tables)
            cols = _table_cols(con, "faculty_preference")
            for c in ("id", "faculty_id", "kind", "subject_id",
                      "section_id", "days", "start_period", "end_period",
                      "weight", "is_hard", "enabled"):
                self.assertIn(c, cols)
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM faculty_preference"
                            ).fetchone()[0], 0)
            idx = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")]
            self.assertIn("ix_faculty_preference_faculty", idx)
            # No existing data touched; schedule rows byte-identical.
            after = con.execute(
                "SELECT * FROM scheduled_class ORDER BY id").fetchall()
            self.assertEqual(before, after)
        finally:
            con.close()

    def test_upgrade_idempotent_on_hybrid_db(self):
        # Hybrid shape (like the current demo DB): table present via
        # create_all, index absent. Upgrade must be a safe no-op.
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE faculty_preference ("
                    "id INTEGER PRIMARY KEY, faculty_id INTEGER, "
                    "kind VARCHAR(30), weight INTEGER DEFAULT 5)")
        con.execute("INSERT INTO faculty_preference VALUES (1, 1, 'TIME_WINDOW', 5)")
        con.commit()
        before = con.execute(
            "SELECT * FROM faculty_preference ORDER BY id").fetchall()
        UP.upgrade(con)
        UP.upgrade(con)  # twice: idempotence
        con.commit()
        try:
            after = con.execute(
                "SELECT * FROM faculty_preference ORDER BY id").fetchall()
            self.assertEqual(before, after)
            idx = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")]
            self.assertIn("ix_faculty_preference_faculty", idx)
        finally:
            con.close()

    def test_downgrade_keeps_table_and_rows(self):
        con = sqlite3.connect(self.db)
        UP.upgrade(con)
        con.execute("INSERT INTO faculty_preference "
                    "(faculty_id, kind, weight) VALUES (1, 'TIME_WINDOW', 5)")
        con.commit()
        UP.downgrade(con)
        con.commit()
        try:
            tables = sorted(r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"))
            # 6C-owned table and its rows survive the 6J downgrade.
            self.assertIn("faculty_preference", tables)
            rows = con.execute(
                "SELECT faculty_id, kind FROM faculty_preference").fetchall()
            self.assertEqual(rows, [(1, "TIME_WINDOW")])
            idx = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")]
            self.assertNotIn("ix_faculty_preference_faculty", idx)
            # Schedule rows still untouched.
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM scheduled_class"
                            ).fetchone()[0], 2)
        finally:
            con.close()

    def test_weight_check_parity_with_model(self):
        con = sqlite3.connect(self.db)
        UP.upgrade(con)
        con.commit()
        try:
            con.execute("INSERT INTO faculty_preference "
                        "(faculty_id, kind, weight) VALUES (1, 'TIME_WINDOW', 7)")
            con.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO faculty_preference "
                            "(faculty_id, kind, weight) VALUES (1, 'TIME_WINDOW', 99)")
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO faculty_preference "
                            "(faculty_id, kind, weight) VALUES (1, 'TIME_WINDOW', 0)")
        finally:
            con.close()

    def test_registry_chain(self):
        from backend import migrate as mpr
        chain = mpr._load_revisions()
        revs = [r for r, _ in chain]
        self.assertIn("6j_faculty_preferences", revs)
        self.assertEqual(revs[-1], "6j_faculty_preferences")
        by_rev = dict(chain)
        self.assertEqual(
            by_rev["6j_faculty_preferences"].down_revision,
            "6f_specializations")
        self.assertEqual(
            by_rev["6e_locked_assignment"].down_revision,
            "6c_additive_schema")

    def test_full_upgrade_and_rollback_on_copy(self):
        # Exercise the real runner: upgrade everything on a pre-6C copy,
        # then roll back to 6f and verify the table outlives the 6J row.
        import argparse
        from backend import migrate as mpr
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(mpr.cmd_upgrade(con), 0)
            applied = mpr.applied_revisions(con)
            self.assertIn("6j_faculty_preferences", applied)
            args = argparse.Namespace(to="6f_specializations")
            self.assertEqual(mpr.cmd_downgrade(con, args), 0)
            applied = mpr.applied_revisions(con)
            self.assertNotIn("6j_faculty_preferences", applied)
            self.assertIn("6f_specializations", applied)
            tables = sorted(r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'schema_migrations'"))
            self.assertIn("faculty_preference", tables)  # 6C table remains
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM scheduled_class"
                            ).fetchone()[0], 2)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
