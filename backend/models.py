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

    enrollment = db.relationship("Enrollment")


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

    faculty = db.relationship("Faculty")
    subject = db.relationship("Subject")
    section = db.relationship("Section")
    lab_group = db.relationship("LabGroup")

    def group_size(self):
        if self.session_type == "practical" and self.lab_group:
            return self.lab_group.student_count
        if self.section:
            return self.section.student_count
        return 0

    def group_label(self):
        if self.session_type == "practical" and self.lab_group:
            return self.lab_group.name
        if self.section:
            return self.section.name
        return "?"

    def group_key(self):
        """A unique key identifying the student group (section or lab group) for overlap checks."""
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

    assignment = db.relationship("TeachingAssignment")
    room = db.relationship("Room")


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
