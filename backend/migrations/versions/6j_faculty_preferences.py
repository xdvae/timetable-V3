"""Revision 6j_faculty_preferences — Phase 6J faculty custom preferences.

Ensures the ``faculty_preference`` table (introduced by 6C) exists with
its 6C-compatible shape plus a faculty lookup index for the scheduler
and admin API. Additive and idempotent:

* ``CREATE TABLE IF NOT EXISTS`` — a no-op on databases that already
  have the table via ``db.create_all()`` or the 6C migration (e.g. the
  current demo database, which carries an empty table);
* ``CREATE INDEX IF NOT EXISTS`` — safe to re-run;
* no existing table is altered, no row is touched, no
  ``ScheduledClass``/``LockedBlock``/``SpecializationSlot`` row is
  modified merely by migrating.

Downgrade removes only what 6J added (the lookup index). The table
itself is owned by revision 6C and is preserved with its data.

upgrade(conn) / downgrade(conn) take a stdlib sqlite3 connection.
"""
revision = "6j_faculty_preferences"
down_revision = "6f_specializations"
description = "Phase 6J: faculty_preference table guarantee + faculty index (additive)"

UPGRADE_DDL = [
    """CREATE TABLE IF NOT EXISTS faculty_preference (
        id INTEGER NOT NULL PRIMARY KEY,
        faculty_id INTEGER NOT NULL REFERENCES faculty (id),
        kind VARCHAR(30) NOT NULL,
        subject_id INTEGER REFERENCES subject (id),
        section_id INTEGER REFERENCES section (id),
        days VARCHAR(120),
        start_period INTEGER,
        end_period INTEGER,
        weight INTEGER NOT NULL DEFAULT 5,
        is_hard BOOLEAN NOT NULL DEFAULT 0,
        enabled BOOLEAN NOT NULL DEFAULT 1,
        CONSTRAINT ck_faculty_preference_weight CHECK (weight >= 1 AND weight <= 10)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_faculty_preference_faculty "
    "ON faculty_preference (faculty_id)",
]

DOWNGRADE_DDL = [
    # Only the 6J addition is removed; the 6C-owned table and its rows
    # stay intact.
    "DROP INDEX IF EXISTS ix_faculty_preference_faculty",
]


def upgrade(conn):
    for stmt in UPGRADE_DDL:
        conn.execute(stmt)


def downgrade(conn):
    for stmt in DOWNGRADE_DDL:
        conn.execute(stmt)
