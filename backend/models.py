"""
Database models for the Timetable Generator.
Uses SQLAlchemy + SQLite (file-based, zero setup).
"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class Config(db.Model):
    """Global scheduling configuration (one row, singleton)."""
    id = db.Column(db.Integer, primary_key=True)
    session_name = db.Column(db.String(120), default="Current Session")
    max_section_size = db.Column(db.Integer, default=80)
    max_lab_group_size = db.Column(db.Integer, default=40)
    working_days = db.Column(db.String(120), default="Mon,Tue,Wed,Thu,Fri,Sat")
    # periods stored as JSON-ish string: "09:00-10:00|10:00-11:00|..."
    periods = db.Column(db.Text, default="09:00-10:00|10:00-11:00|11:00-12:00|12:00-13:00|13:00-14:00|14:00-15:00|15:00-16:00")
    break_after_periods = db.Column(db.Integer, default=3)  # lunch break inserted after this many periods (index, 0-based count)
    max_consecutive_teaching = db.Column(db.Integer, default=3)  # faculty needs break after this many back-to-back periods

    def day_list(self):
        return [d.strip() for d in self.working_days.split(",") if d.strip()]

    def period_list(self):
        return [p.strip() for p in self.periods.split("|") if p.strip()]


class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    room_type = db.Column(db.String(20), nullable=False)  # 'theory' or 'lab'
    capacity = db.Column(db.Integer, nullable=False)
    equipment_count = db.Column(db.Integer, nullable=True)  # relevant for labs (e.g. computers)


class Faculty(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    department = db.Column(db.String(120))
    faculty_type = db.Column(db.String(20), default="regular")  # regular / inter-department / visiting
    weekly_max_hours = db.Column(db.Integer, default=24)
    # Availability: if empty, faculty considered available all working periods.
    # Stored as comma list of "day:period_index" e.g. "Mon:0,Mon:1,Tue:2"
    unavailable_slots = db.Column(db.Text, default="")

    def unavailable_set(self):
        s = set()
        for tok in (self.unavailable_slots or "").split(","):
            tok = tok.strip()
            if tok:
                s.add(tok)
        return s


class Program(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)  # e.g. "BCA", "Btech CSE"
    department = db.Column(db.String(120))


class Enrollment(db.Model):
    """A program + year with a total student count -> auto-generates sections."""
    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey("program.id"), nullable=False)
    year_label = db.Column(db.String(40), nullable=False)  # e.g. "1st Year", "Sem II"
    total_students = db.Column(db.Integer, nullable=False)

    program = db.relationship("Program")


class Section(db.Model):
    """Auto-generated (or manually created) section, e.g. BCA-1-A."""
    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("enrollment.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)  # e.g. "BCA-1-A"
    student_count = db.Column(db.Integer, nullable=False)
    # Phase 6C (additive, unused by the scheduler until Phase 6G): soft
    # "home room" preference for ordinary theory classes. Nullable so no
    # existing section is affected; never a reservation (see Phase 6B §8).
    preferred_theory_room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=True)

    enrollment = db.relationship("Enrollment")
    preferred_theory_room = db.relationship("Room")


class LabGroup(db.Model):
    """Auto-generated sub-split of a section for lab/practical sessions."""
    id = db.Column(db.Integer, primary_key=True)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)  # e.g. "BCA-1-A-G1"
    student_count = db.Column(db.Integer, nullable=False)

    section = db.relationship("Section")


class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40))
    name = db.Column(db.String(200), nullable=False)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("enrollment.id"), nullable=False)
    credits = db.Column(db.Integer, default=3)
    theory_hours_per_week = db.Column(db.Integer, nullable=True)      # default suggestion for new assignments
    practical_hours_per_week = db.Column(db.Integer, nullable=True)   # default suggestion for new assignments
    practical_block_length = db.Column(db.Integer, default=2)         # labs default to a 2-hour block

    enrollment = db.relationship("Enrollment")


class TeachingAssignment(db.Model):
    """
    A required teaching session set: one faculty teaching one subject
    to one section (theory) or one lab-group (practical), with a given
    number of periods/week and the block length per session.

    e.g. Dr. Sharma teaches DAA Theory to BCA-1-A: 3 periods/week, 1 period/session (3 sessions)
    e.g. Dr. Sharma teaches DAA Lab to BCA-1-A-G1: 2 periods/week, 2 periods/session (1 session, a 2hr block)
    """
    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey("faculty.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False)
    session_type = db.Column(db.String(20), nullable=False)  # 'theory' or 'practical'
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=True)      # used for theory
    lab_group_id = db.Column(db.Integer, db.ForeignKey("lab_group.id"), nullable=True)  # used for practical
    periods_per_week = db.Column(db.Integer, nullable=False)   # total contact periods/week
    block_length = db.Column(db.Integer, nullable=False)       # periods per single session block (e.g. 1 for theory, 2 for a lab block)
    # Phase 6F (additive, nullable): when set, this assignment teaches one
    # specialization (cross-section group) instead of a section/lab-group.
    # section_id/lab_group_id stay NULL; group size = sum of membership
    # headcounts; the scheduler blocks every participating section.
    # Pre-6F rows keep NULL (normal teaching, unchanged behavior).
    specialization_id = db.Column(db.Integer, db.ForeignKey("specialization.id"), nullable=True)

    faculty = db.relationship("Faculty")
    subject = db.relationship("Subject")
    section = db.relationship("Section")
    lab_group = db.relationship("LabGroup")
    specialization = db.relationship("Specialization")

    def group_size(self):
        if self.specialization_id is not None:
            # Specialization headcount is membership-driven; ORM rows here
            # cannot sum it without a query, so callers (scheduler/validator)
            # override with the membership total. Fall back to section size
            # only when no specialization link exists.
            if self.section:
                return self.section.student_count
            return 0
        if self.session_type == "practical" and self.lab_group:
            return self.lab_group.student_count
        if self.section:
            return self.section.student_count
        return 0

    def group_label(self):
        if self.specialization_id is not None and self.specialization is not None:
            return f"SPEC:{self.specialization.name}"
        if self.session_type == "practical" and self.lab_group:
            return self.lab_group.name
        if self.section:
            return self.section.name
        if self.specialization_id is not None:
            return f"specialization:{self.specialization_id}"
        return "?"

    def group_key(self):
        """A unique key identifying the student group (section or lab group) for overlap checks."""
        if self.specialization_id is not None:
            return f"specialization:{self.specialization_id}"
        if self.session_type == "practical" and self.lab_group:
            return f"labgroup:{self.lab_group_id}"
        return f"section:{self.section_id}"


class ScheduledClass(db.Model):
    """One placed session block: day + start period + room, produced by the solver."""
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("teaching_assignment.id"), nullable=False)
    day = db.Column(db.String(10), nullable=False)
    start_period = db.Column(db.Integer, nullable=False)  # 0-based index into Config.period_list()
    length = db.Column(db.Integer, nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False)
    run_id = db.Column(db.String(40))  # groups results from one solver run so we can clear/replace
    # Phase 6C (additive, unused until later phases): lock/slot anchors.
    # is_locked defaults false so every existing row stays logically identical.
    is_locked = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    slot_id = db.Column(db.Integer, db.ForeignKey("specialization_slot.id"), nullable=True)
    locked_block_id = db.Column(db.Integer, db.ForeignKey("locked_block.id"), nullable=True)

    assignment = db.relationship("TeachingAssignment")
    room = db.relationship("Room")
    slot = db.relationship("SpecializationSlot")
    locked_block = db.relationship("LockedBlock")


# ---------------------------------------------------------------------------
# Phase 6C additive schema (design: Phase 6B report §§5-9).
# New tables only; nothing here is populated or consumed by the scheduler,
# the API, or the audit in this phase. All relationships avoid delete
# cascades (matching the existing codebase style); deletions that would
# orphan rows must be guarded at the application layer in later phases.
# ---------------------------------------------------------------------------

class Specialization(db.Model):
    """A cross-section student grouping (e.g. Cyber Security for BCA-3).

    Students are NOT individual rows: membership headcounts per originating
    section live on SpecializationMembership, preserving each section's
    contribution (Phase 6B §6)."""
    __tablename__ = "specialization"
    __table_args__ = (db.UniqueConstraint("name", "enrollment_id",
                                          name="uq_specialization_name_enrollment"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)  # e.g. "Cyber Security"
    enrollment_id = db.Column(db.Integer, db.ForeignKey("enrollment.id"), nullable=False)
    session_type = db.Column(db.String(20), nullable=False, default="theory")  # theory | practical
    block_length = db.Column(db.Integer, nullable=False, default=1)
    periods_per_week = db.Column(db.Integer, nullable=False)

    enrollment = db.relationship("Enrollment")
    memberships = db.relationship("SpecializationMembership",
                                  back_populates="specialization",
                                  cascade="all, delete-orphan")
    slots = db.relationship("SpecializationSlot",
                            back_populates="specialization",
                            cascade="all, delete-orphan")
    # Phase 6F: teaching assignments for this specialization (each carries
    # faculty/subject/periods; section/lab stay NULL). View-only here;
    # lifecycle (delete with spec) is handled in specializations.py.
    assignments = db.relationship("TeachingAssignment",
                                  primaryjoin="Specialization.id==TeachingAssignment.specialization_id",
                                  viewonly=True)


class SpecializationMembership(db.Model):
    """Headcount of one section's students in one specialization."""
    __tablename__ = "specialization_membership"
    __table_args__ = (
        db.UniqueConstraint("specialization_id", "section_id",
                            name="uq_spec_membership_spec_section"),
        db.CheckConstraint("student_count > 0", name="ck_spec_membership_positive"),
    )

    id = db.Column(db.Integer, primary_key=True)
    specialization_id = db.Column(db.Integer, db.ForeignKey("specialization.id"),
                                 nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=False)
    student_count = db.Column(db.Integer, nullable=False)

    specialization = db.relationship("Specialization", back_populates="memberships")
    section = db.relationship("Section")


class SpecializationSlot(db.Model):
    """One synchronized common time window for a specialization (Phase 6B HN3).

    Member classes (future phases) reference the slot; rooms/faculty may
    differ per class but (day, start_period, length) is shared."""
    __tablename__ = "specialization_slot"

    id = db.Column(db.Integer, primary_key=True)
    specialization_id = db.Column(db.Integer, db.ForeignKey("specialization.id"),
                                 nullable=False)
    day = db.Column(db.String(10), nullable=False)
    start_period = db.Column(db.Integer, nullable=False)
    length = db.Column(db.Integer, nullable=False, default=1)

    specialization = db.relationship("Specialization", back_populates="slots")


class LockedBlock(db.Model):
    """Generalized immutable scheduling input (Phase 6B §7).

    kind='interdepartment' covers externally-controlled classes (pinned time
    + teacher; room optional); 'manual_fix' / 'admin_override' cover future
    admin-pinned blocks. The scheduler consumes these as fixed occupancy in
    a later phase — not in 6C."""
    __tablename__ = "locked_block"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(30), nullable=False, default="interdepartment")
    # interdepartment | manual_fix | admin_override
    # Phase 6E (additive, nullable): the TeachingAssignment whose session
    # this block pins. Lets the scheduler subtract locked periods from
    # demand and lets validation report ASSIGNMENT_MISMATCH precisely.
    # Pre-6E rows keep NULL; every 6E interdepartment block sets it.
    assignment_id = db.Column(db.Integer, db.ForeignKey("teaching_assignment.id"),
                              nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey("faculty.id"), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=True)
    lab_group_id = db.Column(db.Integer, db.ForeignKey("lab_group.id"), nullable=True)
    day = db.Column(db.String(10), nullable=False)
    start_period = db.Column(db.Integer, nullable=False)
    length = db.Column(db.Integer, nullable=False, default=1)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=True)
    room_locked = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    department = db.Column(db.String(120), nullable=True)  # external owning department
    is_external = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    note = db.Column(db.Text, nullable=True)

    assignment = db.relationship("TeachingAssignment")
    subject = db.relationship("Subject")
    faculty = db.relationship("Faculty")
    section = db.relationship("Section")
    lab_group = db.relationship("LabGroup")
    room = db.relationship("Room")


class FacultyPreference(db.Model):
    """Optional soft (rarely hard) faculty scheduling preference (Phase 6B §9).

    kinds: TIME_WINDOW (teach inside [start_period, end_period) on `days`),
    SUBJECT_AFFINITY (prefer subject_id for section_id),
    DAY_OFF_PREFERENCE (soft reward for no classes that day; distinct from
    the hard unavailable_slots mechanism). New kinds need no schema change."""
    __tablename__ = "faculty_preference"
    __table_args__ = (
        db.CheckConstraint("weight >= 1 AND weight <= 10",
                           name="ck_faculty_preference_weight"),
    )

    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey("faculty.id"), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    # TIME_WINDOW | SUBJECT_AFFINITY | DAY_OFF_PREFERENCE
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=True)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=True)
    days = db.Column(db.String(120), nullable=True)  # e.g. "Mon,Tue,Wed,Thu,Fri"
    start_period = db.Column(db.Integer, nullable=True)
    end_period = db.Column(db.Integer, nullable=True)  # exclusive
    weight = db.Column(db.Integer, nullable=False, default=5)
    is_hard = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    enabled = db.Column(db.Boolean, nullable=False, default=True, server_default="1")

    faculty = db.relationship("Faculty")
    subject = db.relationship("Subject")
    section = db.relationship("Section")


class AdminUser(db.Model):
    """
    Single-tenant Phase 1 auth: one (or a few) admin logins per deployed
    institution. Created automatically on first run from the
    ADMIN_USERNAME / ADMIN_PASSWORD environment variables — see
    init_admin_from_env() in app.py.
    """
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # Flask-Login required properties/methods
    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        if Config.query.count() == 0:
            db.session.add(Config())
            db.session.commit()
