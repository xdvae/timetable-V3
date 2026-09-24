"""Revision 6c_additive_schema — Phase 6C future schema (additive only).

Adds: specialization, specialization_membership, specialization_slot,
locked_block, faculty_preference tables; section.preferred_theory_room_id;
scheduled_class.is_locked / slot_id / locked_block_id; three supporting
indexes. No existing table is altered beyond ADD COLUMN, no row is touched,
and every existing row keeps its id. New tables are created empty.

upgrade(conn) / downgrade(conn) take a stdlib sqlite3 connection.
"""
revision = "6c_additive_schema"
down_revision = None
description = "Phase 6C: specializations, locked blocks, preferences, home-room + lock columns"

UPGRADE_DDL = [
    """CREATE TABLE specialization (
        id INTEGER NOT NULL PRIMARY KEY,
        name VARCHAR(120) NOT NULL,
        enrollment_id INTEGER NOT NULL REFERENCES enrollment (id),
        session_type VARCHAR(20) NOT NULL DEFAULT 'theory',
        block_length INTEGER NOT NULL DEFAULT 1,
        periods_per_week INTEGER NOT NULL,
        CONSTRAINT uq_specialization_name_enrollment UNIQUE (name, enrollment_id)
    )""",
    """CREATE TABLE specialization_membership (
        id INTEGER NOT NULL PRIMARY KEY,
        specialization_id INTEGER NOT NULL REFERENCES specialization (id),
        section_id INTEGER NOT NULL REFERENCES section (id),
        student_count INTEGER NOT NULL,
        CONSTRAINT uq_spec_membership_spec_section UNIQUE (specialization_id, section_id),
        CONSTRAINT ck_spec_membership_positive CHECK (student_count > 0)
    )""",
    """CREATE TABLE specialization_slot (
        id INTEGER NOT NULL PRIMARY KEY,
        specialization_id INTEGER NOT NULL REFERENCES specialization (id),
        day VARCHAR(10) NOT NULL,
        start_period INTEGER NOT NULL,
        length INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE locked_block (
        id INTEGER NOT NULL PRIMARY KEY,
        kind VARCHAR(30) NOT NULL DEFAULT 'interdepartment',
        subject_id INTEGER NOT NULL REFERENCES subject (id),
        faculty_id INTEGER NOT NULL REFERENCES faculty (id),
        section_id INTEGER REFERENCES section (id),
        lab_group_id INTEGER REFERENCES lab_group (id),
        day VARCHAR(10) NOT NULL,
        start_period INTEGER NOT NULL,
        length INTEGER NOT NULL DEFAULT 1,
        room_id INTEGER REFERENCES room (id),
        room_locked BOOLEAN NOT NULL DEFAULT 0,
        department VARCHAR(120),
        is_external BOOLEAN NOT NULL DEFAULT 1,
        note TEXT
    )""",
    """CREATE TABLE faculty_preference (
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
    "ALTER TABLE section ADD COLUMN preferred_theory_room_id INTEGER REFERENCES room (id)",
    "ALTER TABLE scheduled_class ADD COLUMN is_locked BOOLEAN NOT NULL DEFAULT 0",
    "ALTER TABLE scheduled_class ADD COLUMN slot_id INTEGER REFERENCES specialization_slot (id)",
    "ALTER TABLE scheduled_class ADD COLUMN locked_block_id INTEGER REFERENCES locked_block (id)",
    "CREATE INDEX ix_scheduled_class_day_start ON scheduled_class (day, start_period)",
    "CREATE INDEX ix_teaching_assignment_faculty ON teaching_assignment (faculty_id)",
    "CREATE INDEX ix_spec_membership_spec ON specialization_membership (specialization_id)",
]

DOWNGRADE_DDL = [
    "DROP INDEX IF EXISTS ix_spec_membership_spec",
    "DROP INDEX IF EXISTS ix_teaching_assignment_faculty",
    "DROP INDEX IF EXISTS ix_scheduled_class_day_start",
    "ALTER TABLE scheduled_class DROP COLUMN locked_block_id",
    "ALTER TABLE scheduled_class DROP COLUMN slot_id",
    "ALTER TABLE scheduled_class DROP COLUMN is_locked",
    "ALTER TABLE section DROP COLUMN preferred_theory_room_id",
    "DROP TABLE IF EXISTS faculty_preference",
    "DROP TABLE IF EXISTS locked_block",
    "DROP TABLE IF EXISTS specialization_slot",
    "DROP TABLE IF EXISTS specialization_membership",
    "DROP TABLE IF EXISTS specialization",
]


def upgrade(conn):
    for stmt in UPGRADE_DDL:
        conn.execute(stmt)


def downgrade(conn):
    for stmt in DOWNGRADE_DDL:
        conn.execute(stmt)
