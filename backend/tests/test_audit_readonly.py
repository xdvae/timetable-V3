"""Phase 6D.2 safety regression: the audit CLI is strictly read-only.

Running `python -m backend.audit_schedule --db <copy>` must leave the
database file byte-identical: same SHA-256, same tables, same row counts,
no admin user inserted, no migration applied. This prevents a repeat of
the Phase 6D.1 incident (audit importing backend.app, whose
init_db()/init_admin_from_env() created tables + inserted the admin user).

Run from the repository root:
    venv\\Scripts\\python.exe -m unittest discover -s backend\\tests -t .
"""
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _inventory(path):
    """(tables, counts, admin_count) read through a plain sqlite3 handle."""
    con = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
    try:
        tables = sorted(r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"))
        counts = {}
        for t in tables:
            counts[t] = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        admin = counts.get("admin_user")
        return tables, counts, admin
    finally:
        con.close()


def _repo_root():
    import backend.tests as _t
    tests_dir = os.path.dirname(os.path.abspath(_t.__file__))
    return os.path.dirname(os.path.dirname(tests_dir))


def _run_audit(db_path):
    return subprocess.run(
        [sys.executable, "-m", "backend.audit_schedule", "--db", db_path],
        capture_output=True, text=True, cwd=_repo_root(),
        env=dict(os.environ), timeout=120)


def _make_current_schema_db(db_path):
    """Small migrated-schema DB (ORM create_all includes 6C columns)."""
    from flask import Flask
    from backend import models as m
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + db_path
    m.db.init_app(app)
    with app.app_context():
        m.db.create_all()
        m.db.session.add(m.Config(
            session_name="RO", working_days="Mon,Tue",
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


def _make_legacy_db(db_path):
    """Pre-Phase-6C database: no 6C columns/tables, no schema_migrations."""
    con = sqlite3.connect(db_path)
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
    con.execute("INSERT INTO program VALUES (1, 'BCA', NULL)")
    con.execute("INSERT INTO enrollment VALUES (1, 1, '1st Year', 60)")
    con.execute("INSERT INTO section VALUES (1, 1, 'BCA-5-A', 60)")
    con.execute("INSERT INTO room VALUES (1, '201', 'theory', 80, NULL)")
    con.execute("INSERT INTO faculty VALUES (1, 'F1', NULL, 'regular', 24, '')")
    con.execute("INSERT INTO subject VALUES (1, 'BCA101', 'DSA', 1, 3, NULL, NULL, 2)")
    con.execute("INSERT INTO lab_group VALUES (1, 1, 'BCA-5-A-G1', 30)")
    con.execute("INSERT INTO teaching_assignment VALUES (1, 1, 1, 'theory', 1, NULL, 3, 1)")
    for i, p in enumerate((0, 1, 2)):
        con.execute("INSERT INTO scheduled_class VALUES (?, 1, 'Mon', ?, 1, 1, 't')",
                    (10 + i, p))
    con.execute("INSERT INTO config VALUES (1, 'S', 80, 40, 'Mon,Tue', "
                "'p0|p1|p2|p3|p4|p5|p6', 4, 3)")
    con.commit()
    con.close()


class TestAuditReadOnly(unittest.TestCase):
    def test_audit_leaves_current_db_byte_identical(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = os.path.join(tmp.name, "audit.db")
        _make_current_schema_db(db_path)
        before_sha = _sha(db_path)
        before_tables, before_counts, _ = _inventory(db_path)

        proc = _run_audit(db_path)

        self.assertIn("MAX_TWO_THEORY", proc.stdout)
        self.assertIn("[FAIL]", proc.stdout)
        self.assertEqual(_sha(db_path), before_sha,
                         "audit mutated the database file")
        tables, counts, _ = _inventory(db_path)
        self.assertEqual(tables, before_tables)
        self.assertEqual(counts, before_counts)

    def test_audit_inserts_no_admin_and_creates_no_tables(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = os.path.join(tmp.name, "audit.db")
        _make_current_schema_db(db_path)
        _, _, admin_before = _inventory(db_path)
        self.assertEqual(admin_before, 0)
        _run_audit(db_path)
        tables, _, admin_after = _inventory(db_path)
        self.assertEqual(admin_after, 0,
                         "audit inserted an admin user")
        self.assertNotIn("schema_migrations", tables)

    def test_audit_legacy_db_reports_note_and_stays_unchanged(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = os.path.join(tmp.name, "legacy.db")
        _make_legacy_db(db_path)
        before_sha = _sha(db_path)

        proc = _run_audit(db_path)

        # Legacy columns are sufficient: the streak is still detected...
        self.assertIn("MAX_TWO_THEORY", proc.stdout)
        # ...with an explicit no-migration note, and no auto-repair.
        self.assertIn("missing Phase 6C", proc.stdout)
        self.assertIn("no migration was performed", proc.stdout)
        self.assertEqual(_sha(db_path), before_sha,
                         "audit mutated the legacy database file")
        tables, _, _ = _inventory(db_path)
        self.assertNotIn("schema_migrations", tables)
        self.assertNotIn("specialization", tables)

    def test_audit_missing_db_is_explicit_error(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        missing = os.path.join(tmp.name, "nope.db")
        proc = _run_audit(missing)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not found", proc.stdout + proc.stderr)
        self.assertFalse(os.path.exists(missing))


if __name__ == "__main__":
    unittest.main()
