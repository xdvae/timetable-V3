"""Phase 6V regression tests — production safety / release hardening.

Covers the two defect families found during the 6V audit:

* 6V-1 — wrong-method GET requests against POST-only ``/api/*`` routes
  returned JSON 404 (NOT_FOUND) on the real application because the SPA
  ``GET`` catch-all shadows routing-level 405s. The 6U regression test
  only exercised a blueprint-only harness without the catch-all, so the
  production routing path was unguarded. ``backend.app.api_catchall_response``
  restores the unified 405 contract there.
* 6V-2/6V-3 — the checked-in demo database carries 6C-era tables without
  the additive columns (and no ``schema_migrations`` history), so the
  current ORM serves sanitized 500s against it and the plain
  ``CREATE TABLE`` / ``ADD COLUMN`` upgrades crashed instead of repairing
  it. Migration upgrades are now idempotent; these tests pin the repair
  of a reference-like hybrid database (tables present, columns missing).

Every test uses throwaway SQLite files under TemporaryDirectory —
never the reference databases in backend/instance/.
Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_production_safety_6v -v
"""
import argparse
import os
import sqlite3
import tempfile
import unittest


def _hybrid_schema(con):
    """Reference-like hybrid state: core tables (pre-6C columns) plus the
    6C-era tables WITHOUT any additive column (no preferred_theory_room_id,
    no is_locked/slot_id/locked_block_id, no locked_block.assignment_id,
    no teaching_assignment.specialization_id), and no schema_migrations."""
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
    # 6C-era tables in their intermediate shape (as create_all() produced
    # them before the additive columns existed on the models).
    con.execute("CREATE TABLE specialization (id INTEGER PRIMARY KEY, name VARCHAR(120), "
                "enrollment_id INTEGER, session_type VARCHAR(20) DEFAULT 'theory', "
                "block_length INTEGER DEFAULT 1, periods_per_week INTEGER)")
    con.execute("CREATE TABLE specialization_membership (id INTEGER PRIMARY KEY, "
                "specialization_id INTEGER, section_id INTEGER, student_count INTEGER)")
    con.execute("CREATE TABLE specialization_slot (id INTEGER PRIMARY KEY, "
                "specialization_id INTEGER, day VARCHAR(10), "
                "start_period INTEGER, length INTEGER DEFAULT 1)")
    con.execute("CREATE TABLE locked_block (id INTEGER PRIMARY KEY, "
                "kind VARCHAR(30) DEFAULT 'interdepartment', subject_id INTEGER, "
                "faculty_id INTEGER, section_id INTEGER, lab_group_id INTEGER, "
                "day VARCHAR(10), start_period INTEGER, length INTEGER DEFAULT 1, "
                "room_id INTEGER, room_locked BOOLEAN DEFAULT 0, department VARCHAR(120), "
                "is_external BOOLEAN DEFAULT 1, note TEXT)")
    con.execute("CREATE TABLE faculty_preference (id INTEGER PRIMARY KEY, "
                "faculty_id INTEGER, kind VARCHAR(30), subject_id INTEGER, "
                "section_id INTEGER, days VARCHAR(120), start_period INTEGER, "
                "end_period INTEGER, weight INTEGER DEFAULT 5, "
                "is_hard BOOLEAN DEFAULT 0, enabled BOOLEAN DEFAULT 1)")
    con.execute("INSERT INTO program VALUES (1, 'BCA', NULL)")
    con.execute("INSERT INTO enrollment VALUES (1, 1, '1st Year', 60)")
    con.execute("INSERT INTO section VALUES (1, 1, 'BCA-1-A', 60)")
    con.execute("INSERT INTO room VALUES (1, '201', 'theory', 80, NULL)")
    con.execute("INSERT INTO faculty VALUES (1, 'Dr. X', NULL, 'regular', 24, '')")
    con.execute("INSERT INTO subject VALUES (1, 'BCA101', 'Prog', 1, 3, NULL, NULL, 2)")
    con.execute("INSERT INTO lab_group VALUES (1, 1, 'BCA-1-A-G1', 30)")
    con.execute("INSERT INTO teaching_assignment VALUES (1, 1, 1, 'theory', 1, NULL, 3, 1)")
    con.execute("INSERT INTO scheduled_class VALUES (1, 1, 'Mon', 0, 1, 1, 'run1')")
    con.execute("INSERT INTO scheduled_class VALUES (2, 1, 'Tue', 2, 1, 1, 'run1')")
    con.execute("INSERT INTO config VALUES (1, 'S', 80, 40, 'Mon,Tue', 'a|b', 1, 3)")
    con.execute("INSERT INTO admin_user VALUES (1, 'admin', 'x')")
    con.commit()


def _full_dump(con):
    tables = sorted(r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name != 'schema_migrations'"))
    return {t: ([r[1] for r in con.execute(f'PRAGMA table_info("{t}")')],
                con.execute(f'SELECT * FROM "{t}" ORDER BY 1').fetchall())
            for t in tables}


def _assert_no_data_loss(testcase, before, after):
    """Every pre-existing column keeps byte-identical rows; only the
    repaired additive columns may extend the row shape (with defaults)."""
    testcase.assertEqual(set(before), set(after))
    for table, (old_cols, old_rows) in before.items():
        new_cols, new_rows = after[table]
        testcase.assertEqual(
            new_cols[:len(old_cols)], old_cols, f"columns reordered in {table}")
        testcase.assertEqual(
            [r[:len(old_cols)] for r in new_rows], list(old_rows),
            f"pre-existing data changed in {table}")


def _cols(con, table):
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


class TestHybridMigrationRepair6V(unittest.TestCase):
    """6V-2/6V-3: the full runner repairs a reference-like hybrid DB."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "hybrid.db")
        con = sqlite3.connect(self.db)
        _hybrid_schema(con)
        con.close()

    def test_full_upgrade_repairs_and_preserves(self):
        from backend import migrate as mpr
        con = sqlite3.connect(self.db)
        before = _full_dump(con)
        con.close()
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(mpr.cmd_upgrade(con), 0)
            applied = mpr.applied_revisions(con)
            for rev in ("6c_additive_schema", "6e_locked_assignment",
                        "6f_specializations", "6j_faculty_preferences"):
                self.assertIn(rev, applied)
        finally:
            con.close()
        con = sqlite3.connect(self.db)
        try:
            # Every additive column the current ORM selects now exists.
            self.assertIn("preferred_theory_room_id", _cols(con, "section"))
            for c in ("is_locked", "slot_id", "locked_block_id"):
                self.assertIn(c, _cols(con, "scheduled_class"))
            self.assertIn("assignment_id", _cols(con, "locked_block"))
            self.assertIn("specialization_id", _cols(con, "teaching_assignment"))
            # No row touched: every pre-existing column is byte-identical.
            _assert_no_data_loss(self, before, _full_dump(con))
            # New columns carry safe defaults on old rows.
            self.assertEqual(
                con.execute("SELECT is_locked FROM scheduled_class ORDER BY id"
                            ).fetchall(), [(0,), (0,)])
        finally:
            con.close()

    def test_upgrade_is_idempotent(self):
        from backend import migrate as mpr
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(mpr.cmd_upgrade(con), 0)
            before = _full_dump(con)
            # Second run is a clean no-op, not a crash.
            self.assertEqual(mpr.cmd_upgrade(con), 0)
            _assert_no_data_loss(self, before, _full_dump(con))
            applied = mpr.applied_revisions(con)
            self.assertEqual(len(applied), 4)
        finally:
            con.close()

    def test_downgrade_to_6f_and_reupgrade(self):
        from backend import migrate as mpr
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(mpr.cmd_upgrade(con), 0)
            before = {t: rows for t, rows in _full_dump(con).items()
                      if t not in ("schema_migrations",)}
            args = argparse.Namespace(to="6f_specializations")
            self.assertEqual(mpr.cmd_downgrade(con, args), 0)
            applied = mpr.applied_revisions(con)
            self.assertIn("6f_specializations", applied)
            self.assertNotIn("6j_faculty_preferences", applied)
            self.assertEqual(mpr.cmd_upgrade(con), 0)
            self.assertIn("6j_faculty_preferences", mpr.applied_revisions(con))
            # The 6J downgrade removes only its index (rows untouched) and
            # the re-upgrade only re-adds it: every row is byte-identical.
            _assert_no_data_loss(self, before, _full_dump(con))
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM scheduled_class").fetchone()[0], 2)
        finally:
            con.close()

    def test_orm_queries_succeed_after_repair(self):
        from flask import Flask
        from backend import migrate as mpr
        from backend import models as m
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(mpr.cmd_upgrade(con), 0)
        finally:
            con.close()
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.db
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        m.db.init_app(app)
        with app.app_context():
            try:
                sections = m.Section.query.all()
                self.assertEqual(len(sections), 1)
                self.assertIsNone(sections[0].preferred_theory_room_id)
                assigns = m.TeachingAssignment.query.all()
                self.assertEqual(len(assigns), 1)
                self.assertIsNone(assigns[0].specialization_id)
                classes = m.ScheduledClass.query.order_by(
                    m.ScheduledClass.id).all()
                self.assertEqual(len(classes), 2)
                self.assertFalse(classes[0].is_locked)
                self.assertIsNone(classes[0].slot_id)
                # Even count() works (the ORM subquery selects all columns).
                self.assertEqual(m.ScheduledClass.query.count(), 2)
            finally:
                m.db.session.remove()
                m.db.engine.dispose()  # release the sqlite file (Windows locks it)


class TestProductionWrongMethodJson6V(unittest.TestCase):
    """6V-1: the real-app routing shape (SPA GET catch-all + /api/*)
    keeps the unified 405 JSON contract for wrong-method requests."""

    @classmethod
    def setUpClass(cls):
        # Isolate backend.app import BEFORE it happens: the module binds
        # its default database from DATABASE_URL at import time.
        cls._tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
            cls._tmp.name, "isolation.db")
        os.environ["SECRET_KEY"] = "6v-test-key"
        os.environ["ADMIN_USERNAME"] = "admin"
        os.environ["ADMIN_PASSWORD"] = "6v-test-pass"
        import backend.app as appmod  # noqa: PLC0415 (isolated by env above)
        cls.appmod = appmod

    @classmethod
    def tearDownClass(cls):
        from backend.models import db as mdb
        try:
            mdb.session.remove()
        except Exception:
            pass
        try:
            mdb.engine.dispose()  # release sqlite files (Windows locks them)
        except Exception:
            pass
        try:
            # The imported backend.app binds its own engine to isolation.db;
            # dispose it under its own app context so the temp dir unlocks.
            with cls.appmod.app.app_context():
                cls.appmod.db.session.remove()
                cls.appmod.db.engine.dispose()
        except Exception:
            pass
        for key in ("DATABASE_URL", "SECRET_KEY", "ADMIN_USERNAME",
                    "ADMIN_PASSWORD"):
            os.environ.pop(key, None)
        cls._tmp.cleanup()

    def setUp(self):
        self._apps = []

    def tearDown(self):
        from backend.models import db as mdb
        for app in getattr(self, "_apps", []):
            try:
                # Dispose each test app's engine under its own context so
                # the temp sqlite files unlock on Windows.
                with app.app_context():
                    mdb.session.remove()
                    mdb.engine.dispose()
            except Exception:
                pass

    def _production_shaped_app(self):
        """Fresh app with the real blueprint wiring PLUS the production
        SPA GET catch-all delegating to the real fallback helper."""
        from flask import Flask, abort, request
        from flask_login import LoginManager
        from backend.api_routes import init_api
        from backend.models import db as mdb
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "6v-test-key"
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
            self._tmp.name, "t.db")
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        mdb.init_app(app)
        with app.app_context():
            mdb.create_all()
        lm = LoginManager()
        lm.init_app(app)
        init_api(app, lm)
        helper = self.appmod.api_catchall_response

        @app.route("/", defaults={"path": ""}, methods=["GET"])
        @app.route("/<path:path>", methods=["GET"])
        def _serve_react(path):  # mirrors backend.app.serve_react
            if (request.path or "").startswith("/api/"):
                return helper()
            abort(404)

        self._apps.append(app)
        return app

    def test_wrong_method_get_is_405_json(self):
        client = self._production_shaped_app().test_client()
        resp = client.get("/api/schedule/run")
        self.assertEqual(resp.status_code, 405)
        body = resp.get_json()
        self.assertIsNotNone(body)
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "METHOD_NOT_ALLOWED")

    def test_unknown_api_path_stays_404_json(self):
        client = self._production_shaped_app().test_client()
        resp = client.get("/api/no-such-endpoint-6v")
        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertIsNotNone(body)
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "NOT_FOUND")

    def test_wrong_method_post_is_405_json(self):
        client = self._production_shaped_app().test_client()
        resp = client.post("/api/dashboard")
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.get_json()["code"], "METHOD_NOT_ALLOWED")


if __name__ == "__main__":
    unittest.main()
