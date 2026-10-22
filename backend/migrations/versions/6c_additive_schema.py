"""Revision 6c_additive_schema — Phase 6C future schema (additive only).

Adds: specialization, specialization_membership, specialization_slot,
locked_block, faculty_preference tables; section.preferred_theory_room_id;
scheduled_class.is_locked / slot_id / locked_block_id; three supporting
indexes. No existing table is altered beyond ADD COLUMN, no row is touched,
and every existing row keeps its id. New tables are created empty.

Phase 6V: ``upgrade()`` is idempotent — tables/columns/indexes that
already exist (e.g. on hybrid databases created by ``db.create_all()``
from an intermediate models.py, which carry the tables but not the
columns) are skipped instead of crashing, so the runner repairs such
databases instead of aborting. Downgrade is unchanged.

upgrade(conn) / downgrade(conn) take a stdlib sqlite3 connection.
"""
revision = "6c_additive_schema"
down_revision = None
description = "Phase 6C: specializations, locked blocks, preferences, home-room + lock columns"

NEW_TABLES_DDL = {
    "specialization": """CREATE TABLE IF NOT EXISTS specialization (
        id INTEGER NOT NULL PRIMARY KEY,
        name VARCHAR(120) NOT NULL,
        enrollment_id INTEGER NOT NULL REFERENCES enrollment (id),
        session_type VARCHAR(20) NOT NULL DEFAULT 'theory',
        block_length INTEGER NOT NULL DEFAULT 1,
        periods_per_week INTEGER NOT NULL,
        CONSTRAINT uq_specialization_name_enrollment UNIQUE (name, enrollment_id)
    )""",
    "specialization_membership": """CREATE TABLE IF NOT EXISTS specialization_membership (
        id INTEGER NOT NULL PRIMARY KEY,
        specialization_id INTEGER NOT NULL REFERENCES specialization (id),
        section_id INTEGER NOT NULL REFERENCES section (id),
        student_count INTEGER NOT NULL,
        CONSTRAINT uq_spec_membership_spec_section UNIQUE (specialization_id, section_id),
        CONSTRAINT ck_spec_membership_positive CHECK (student_count > 0)
    )""",
    "specialization_slot": """CREATE TABLE IF NOT EXISTS specialization_slot (
        id INTEGER NOT NULL PRIMARY KEY,
        specialization_id INTEGER NOT NULL REFERENCES specialization (id),
        day VARCHAR(10) NOT NULL,
        start_period INTEGER NOT NULL,
        length INTEGER NOT NULL DEFAULT 1
    )""",
    "locked_block": """CREATE TABLE IF NOT EXISTS locked_block (
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
    "faculty_preference": """CREATE TABLE IF NOT EXISTS faculty_preference (
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
}

# (table, column, ADD COLUMN statement). SQLite has no ADD COLUMN IF NOT
# EXISTS, so upgrade() checks PRAGMA table_info first (see _helpers).
ADD_COLUMNS = [
    ("section", "preferred_theory_room_id",
     "ALTER TABLE section ADD COLUMN preferred_theory_room_id INTEGER REFERENCES room (id)"),
    ("scheduled_class", "is_locked",
     "ALTER TABLE scheduled_class ADD COLUMN is_locked BOOLEAN NOT NULL DEFAULT 0"),
    ("scheduled_class", "slot_id",
     "ALTER TABLE scheduled_class ADD COLUMN slot_id INTEGER REFERENCES specialization_slot (id)"),
    ("scheduled_class", "locked_block_id",
     "ALTER TABLE scheduled_class ADD COLUMN locked_block_id INTEGER REFERENCES locked_block (id)"),
]

INDEXES_DDL = [
    "CREATE INDEX IF NOT EXISTS ix_scheduled_class_day_start ON scheduled_class (day, start_period)",
    "CREATE INDEX IF NOT EXISTS ix_teaching_assignment_faculty ON teaching_assignment (faculty_id)",
    "CREATE INDEX IF NOT EXISTS ix_spec_membership_spec ON specialization_membership (specialization_id)",
]

# Canonical statement list (kept for reviewability; upgrade() applies it
# idempotently via _helpers rather than blindly).
UPGRADE_DDL = (
    list(NEW_TABLES_DDL.values())
    + [stmt for _, _, stmt in ADD_COLUMNS]
    + INDEXES_DDL
)

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
    from backend.migrations.versions._helpers import ensure_column, ensure_table
    for table, create_sql in NEW_TABLES_DDL.items():
        ensure_table(conn, table, create_sql)
    for table, column, add_sql in ADD_COLUMNS:
        ensure_column(conn, table, column, add_sql)
    for stmt in INDEXES_DDL:
        conn.execute(stmt)


def downgrade(conn):
    for stmt in DOWNGRADE_DDL:
        conn.execute(stmt)
