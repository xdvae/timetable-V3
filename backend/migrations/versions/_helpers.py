"""Shared idempotency guards for migration upgrades (Phase 6V).

Background: the checked-in demo database was created by ``db.create_all()``
from an intermediate models.py — its 6C-era tables exist but the additive
columns (``section.preferred_theory_room_id``,
``scheduled_class.is_locked/slot_id/locked_block_id``,
``locked_block.assignment_id``, ``teaching_assignment.specialization_id``)
were never added, and no ``schema_migrations`` row was ever recorded. A
plain ``CREATE TABLE`` / ``ADD COLUMN`` upgrade therefore crashes on such
hybrid databases instead of repairing them, while the current ORM always
selects every mapped column (even for ``count()``) — so the application
serves sanitized 500s against that database until the schema is repaired.

These helpers let upgrades skip effects that already exist (tables,
columns, indexes) while still applying everything that is missing. They
are pure ``sqlite3`` introspection (``sqlite_master`` / ``PRAGMA
table_info``); they never write. Modules here have no ``revision``
attribute, so ``backend.migrate._load_revisions`` skips this file.
"""


def existing_tables(conn):
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def existing_columns(conn, table):
    return {row[1] for row in conn.execute(
        f'PRAGMA table_info("{table}")')}


def ensure_table(conn, table, create_sql):
    """Run ``create_sql`` unless ``table`` already exists."""
    if table not in existing_tables(conn):
        conn.execute(create_sql)


def ensure_column(conn, table, column, add_column_sql):
    """Run ``add_column_sql`` unless ``column`` already exists on ``table``.

    SQLite has no ``ADD COLUMN IF NOT EXISTS``, so the existence check
    stands in for it. Missing parent tables are left for the caller's
    ``ensure_table`` step (or surface as an error, as before).
    """
    if table in existing_tables(conn) and column not in existing_columns(conn, table):
        conn.execute(add_column_sql)
