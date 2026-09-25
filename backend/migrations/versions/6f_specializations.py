"""Revision 6f_specializations — Phase 6F specialization assignments.

Additive only: adds teaching_assignment.specialization_id (nullable FK to
specialization) so specialization teaching uses the existing assignment
model instead of a parallel system. Nullable so every pre-6F row stays
valid with NULL (normal section/lab teaching); new 6F specialization
assignments set it and leave section_id/lab_group_id NULL. A supporting
index speeds scheduler/validator lookups. No existing table is altered
beyond ADD COLUMN, no row is touched, no IDs change.

upgrade(conn) / downgrade(conn) take a stdlib sqlite3 connection.
"""
revision = "6f_specializations"
down_revision = "6e_locked_assignment"
description = "Phase 6F: teaching_assignment.specialization_id link (additive)"

UPGRADE_DDL = [
    "ALTER TABLE teaching_assignment ADD COLUMN specialization_id INTEGER REFERENCES specialization (id)",
    "CREATE INDEX IF NOT EXISTS ix_teaching_assignment_specialization ON teaching_assignment (specialization_id)",
]

DOWNGRADE_DDL = [
    "DROP INDEX IF EXISTS ix_teaching_assignment_specialization",
    "ALTER TABLE teaching_assignment DROP COLUMN specialization_id",
]


def upgrade(conn):
    for stmt in UPGRADE_DDL:
        conn.execute(stmt)


def downgrade(conn):
    for stmt in DOWNGRADE_DDL:
        conn.execute(stmt)
