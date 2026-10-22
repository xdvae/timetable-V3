"""Revision 6e_locked_assignment — Phase 6E locked-block assignment link.

Additive only: adds locked_block.assignment_id (nullable FK to
teaching_assignment) so an interdepartment LockedBlock unambiguously
identifies the TeachingAssignment whose session it pins. Nullable so
pre-6E rows (none exist in production yet — timetable_v2.db is pre-6C)
stay valid; new 6E rows always set it. No existing table is altered
beyond ADD COLUMN, no row is touched.

upgrade(conn) / downgrade(conn) take a stdlib sqlite3 connection.

Phase 6V: ``upgrade()`` is idempotent — the column is added only when
missing, so hybrid databases (``locked_block`` present without the link,
as in the checked-in demo database) are repaired instead of crashing.
"""
revision = "6e_locked_assignment"
down_revision = "6c_additive_schema"
description = "Phase 6E: locked_block.assignment_id link (additive)"

UPGRADE_DDL = [
    "ALTER TABLE locked_block ADD COLUMN assignment_id INTEGER REFERENCES teaching_assignment (id)",
]

DOWNGRADE_DDL = [
    "ALTER TABLE locked_block DROP COLUMN assignment_id",
]


def upgrade(conn):
    from backend.migrations.versions._helpers import ensure_column
    ensure_column(conn, "locked_block", "assignment_id", UPGRADE_DDL[0])


def downgrade(conn):
    for stmt in DOWNGRADE_DDL:
        conn.execute(stmt)
