"""
Dependency-aware deletes (and orphan repair).

The models deliberately declare no ORM delete cascades and SQLite does not
enforce foreign keys, so a bare ``db.session.delete(row)`` used to leave
dependent rows pointing at a parent that no longer exists. Those ghosts
were invisible in most screens but still fed the scheduler: deleting a
teacher kept their teaching assignments (and timetable classes) alive
under a missing faculty id, deleting an enrollment left its sections and
subjects behind, and so on.

Every delete route now goes through this module. Each function removes
the target *and* everything that only makes sense with it, in one
transaction, and returns a ``DeleteReport`` with counts so the API can
tell the administrator exactly what went.

Nothing here commits half-way: callers commit once on success and roll
back on any exception.
"""
from dataclasses import dataclass, field

from backend.models import (
    db, Enrollment, Faculty, FacultyPreference, LabGroup, LockedBlock,
    Program, Room, ScheduledClass, Section, Specialization,
    SpecializationMembership, SpecializationSlot, Subject,
    TeachingAssignment,
)


class DeleteBlocked(Exception):
    """Raised when a delete would silently drop data the admin must handle."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


@dataclass
class DeleteReport:
    counts: dict = field(default_factory=dict)

    def add(self, key, n):
        if n:
            self.counts[key] = self.counts.get(key, 0) + int(n)

    def summary(self):
        """Human list like '3 teaching assignments and 5 timetable classes'."""
        labels = [
            ("sections", "section", "sections"),
            ("lab_groups", "lab group", "lab groups"),
            ("subjects", "subject", "subjects"),
            ("enrollments", "enrollment", "enrollments"),
            ("specializations", "specialization", "specializations"),
            ("assignments", "teaching assignment", "teaching assignments"),
            ("locked_blocks", "fixed block", "fixed blocks"),
            ("scheduled_classes", "timetable class", "timetable classes"),
            ("preferences", "faculty preference", "faculty preferences"),
        ]
        parts = []
        for key, one, many in labels:
            n = self.counts.get(key, 0)
            if n:
                parts.append(f"{n} {one if n == 1 else many}")
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " and " + parts[-1]


def _ids(query):
    return [row[0] for row in query.all()]


# --------------------------------------------------------------- primitives
def _delete_locked_blocks(block_ids, report):
    block_ids = sorted(set(i for i in block_ids if i is not None))
    if not block_ids:
        return
    report.add("scheduled_classes", ScheduledClass.query.filter(
        ScheduledClass.locked_block_id.in_(block_ids)).delete(
            synchronize_session=False))
    report.add("locked_blocks", LockedBlock.query.filter(
        LockedBlock.id.in_(block_ids)).delete(synchronize_session=False))


def _delete_assignments(assignment_ids, report):
    assignment_ids = sorted(set(i for i in assignment_ids if i is not None))
    if not assignment_ids:
        return
    _delete_locked_blocks(_ids(db.session.query(LockedBlock.id).filter(
        LockedBlock.assignment_id.in_(assignment_ids))), report)
    report.add("scheduled_classes", ScheduledClass.query.filter(
        ScheduledClass.assignment_id.in_(assignment_ids)).delete(
            synchronize_session=False))
    report.add("assignments", TeachingAssignment.query.filter(
        TeachingAssignment.id.in_(assignment_ids)).delete(
            synchronize_session=False))


def _delete_specializations(spec_ids, report):
    spec_ids = sorted(set(i for i in spec_ids if i is not None))
    if not spec_ids:
        return
    _delete_assignments(_ids(db.session.query(TeachingAssignment.id).filter(
        TeachingAssignment.specialization_id.in_(spec_ids))), report)
    slot_ids = _ids(db.session.query(SpecializationSlot.id).filter(
        SpecializationSlot.specialization_id.in_(spec_ids)))
    if slot_ids:
        report.add("scheduled_classes", ScheduledClass.query.filter(
            ScheduledClass.slot_id.in_(slot_ids)).delete(
                synchronize_session=False))
        SpecializationSlot.query.filter(
            SpecializationSlot.id.in_(slot_ids)).delete(
                synchronize_session=False)
    SpecializationMembership.query.filter(
        SpecializationMembership.specialization_id.in_(spec_ids)).delete(
            synchronize_session=False)
    report.add("specializations", Specialization.query.filter(
        Specialization.id.in_(spec_ids)).delete(synchronize_session=False))


def _delete_subjects(subject_ids, report):
    subject_ids = sorted(set(i for i in subject_ids if i is not None))
    if not subject_ids:
        return
    _delete_assignments(_ids(db.session.query(TeachingAssignment.id).filter(
        TeachingAssignment.subject_id.in_(subject_ids))), report)
    _delete_locked_blocks(_ids(db.session.query(LockedBlock.id).filter(
        LockedBlock.subject_id.in_(subject_ids))), report)
    report.add("preferences", FacultyPreference.query.filter(
        FacultyPreference.subject_id.in_(subject_ids)).delete(
            synchronize_session=False))
    report.add("subjects", Subject.query.filter(
        Subject.id.in_(subject_ids)).delete(synchronize_session=False))


def _delete_sections(section_ids, report):
    section_ids = sorted(set(i for i in section_ids if i is not None))
    if not section_ids:
        return
    lab_ids = _ids(db.session.query(LabGroup.id).filter(
        LabGroup.section_id.in_(section_ids)))
    group_filter = TeachingAssignment.section_id.in_(section_ids)
    if lab_ids:
        group_filter = group_filter | TeachingAssignment.lab_group_id.in_(lab_ids)
    _delete_assignments(_ids(db.session.query(TeachingAssignment.id).filter(
        group_filter)), report)
    lb_filter = LockedBlock.section_id.in_(section_ids)
    if lab_ids:
        lb_filter = lb_filter | LockedBlock.lab_group_id.in_(lab_ids)
    _delete_locked_blocks(_ids(db.session.query(LockedBlock.id).filter(
        lb_filter)), report)
    SpecializationMembership.query.filter(
        SpecializationMembership.section_id.in_(section_ids)).delete(
            synchronize_session=False)
    report.add("preferences", FacultyPreference.query.filter(
        FacultyPreference.section_id.in_(section_ids)).delete(
            synchronize_session=False))
    if lab_ids:
        report.add("lab_groups", LabGroup.query.filter(
            LabGroup.id.in_(lab_ids)).delete(synchronize_session=False))
    report.add("sections", Section.query.filter(
        Section.id.in_(section_ids)).delete(synchronize_session=False))


def _delete_enrollments(enrollment_ids, report):
    enrollment_ids = sorted(set(i for i in enrollment_ids if i is not None))
    if not enrollment_ids:
        return
    _delete_specializations(_ids(db.session.query(Specialization.id).filter(
        Specialization.enrollment_id.in_(enrollment_ids))), report)
    _delete_sections(_ids(db.session.query(Section.id).filter(
        Section.enrollment_id.in_(enrollment_ids))), report)
    _delete_subjects(_ids(db.session.query(Subject.id).filter(
        Subject.enrollment_id.in_(enrollment_ids))), report)
    report.add("enrollments", Enrollment.query.filter(
        Enrollment.id.in_(enrollment_ids)).delete(synchronize_session=False))


# ------------------------------------------------------------ public API
def delete_faculty(faculty):
    report = DeleteReport()
    _delete_assignments(_ids(db.session.query(TeachingAssignment.id).filter(
        TeachingAssignment.faculty_id == faculty.id)), report)
    _delete_locked_blocks(_ids(db.session.query(LockedBlock.id).filter(
        LockedBlock.faculty_id == faculty.id)), report)
    report.add("preferences", FacultyPreference.query.filter(
        FacultyPreference.faculty_id == faculty.id).delete(
            synchronize_session=False))
    db.session.delete(faculty)
    return report


def delete_subject(subject):
    report = DeleteReport()
    _delete_subjects([subject.id], report)
    report.counts.pop("subjects", None)  # the target itself
    if subject in db.session:
        db.session.expunge(subject)
    return report


def delete_assignment(assignment):
    report = DeleteReport()
    _delete_assignments([assignment.id], report)
    report.counts.pop("assignments", None)
    if assignment in db.session:
        db.session.expunge(assignment)
    return report


def delete_enrollment(enrollment):
    report = DeleteReport()
    _delete_enrollments([enrollment.id], report)
    report.counts.pop("enrollments", None)
    if enrollment in db.session:
        db.session.expunge(enrollment)
    return report


def delete_program(program):
    report = DeleteReport()
    _delete_enrollments(_ids(db.session.query(Enrollment.id).filter(
        Enrollment.program_id == program.id)), report)
    db.session.delete(program)
    return report


def delete_room(room):
    """Delete a room. Fixed blocks pinned to it must be removed first.

    Normal timetable classes placed in the room are removed (the next
    generation re-places them elsewhere); section home-room preferences
    pointing at it are cleared.
    """
    pinned = LockedBlock.query.filter(LockedBlock.room_id == room.id).count()
    pinned_classes = ScheduledClass.query.filter(
        ScheduledClass.room_id == room.id,
        ScheduledClass.is_locked.is_(True)).count()
    if pinned or pinned_classes:
        n = max(pinned, pinned_classes)
        raise DeleteBlocked(
            f"Room '{room.name}' is used by {n} fixed "
            f"block{'s' if n != 1 else ''}. Delete or move those fixed "
            f"blocks first, then delete the room.",
            {"room_id": room.id, "locked_blocks": n})
    report = DeleteReport()
    report.add("scheduled_classes", ScheduledClass.query.filter(
        ScheduledClass.room_id == room.id).delete(synchronize_session=False))
    Section.query.filter(Section.preferred_theory_room_id == room.id).update(
        {Section.preferred_theory_room_id: None}, synchronize_session=False)
    db.session.delete(room)
    return report


# ---------------------------------------------------------- orphan repair
def purge_orphans():
    """Remove rows whose parent no longer exists (left by older versions).

    Every row removed here was already unreachable from the UI (its
    teacher, subject, class, enrollment or program had been deleted) but
    could still leak into timetable generation. Returns a DeleteReport;
    the caller commits.
    """
    report = DeleteReport()

    def missing(child_col, parent_model):
        return _ids(db.session.query(child_col.class_.id).outerjoin(
            parent_model, parent_model.id == child_col).filter(
                child_col.isnot(None), parent_model.id.is_(None)))

    # Top-down so a purge cascades exactly like a real delete would.
    _delete_enrollments(missing(Enrollment.program_id, Program), report)
    _delete_sections(missing(Section.enrollment_id, Enrollment), report)
    _delete_subjects(missing(Subject.enrollment_id, Enrollment), report)
    _delete_specializations(
        missing(Specialization.enrollment_id, Enrollment), report)
    stray_labs = missing(LabGroup.section_id, Section)
    if stray_labs:
        _delete_assignments(_ids(db.session.query(TeachingAssignment.id).filter(
            TeachingAssignment.lab_group_id.in_(stray_labs))), report)
        report.add("lab_groups", LabGroup.query.filter(
            LabGroup.id.in_(stray_labs)).delete(synchronize_session=False))

    bad_assignments = set()
    bad_assignments.update(missing(TeachingAssignment.faculty_id, Faculty))
    bad_assignments.update(missing(TeachingAssignment.subject_id, Subject))
    bad_assignments.update(missing(TeachingAssignment.section_id, Section))
    bad_assignments.update(missing(TeachingAssignment.lab_group_id, LabGroup))
    bad_assignments.update(
        missing(TeachingAssignment.specialization_id, Specialization))
    # An ordinary assignment needs a group: theory -> section, practical ->
    # lab group (specialization rows carry neither by design).
    bad_assignments.update(_ids(db.session.query(TeachingAssignment.id).filter(
        TeachingAssignment.specialization_id.is_(None),
        TeachingAssignment.section_id.is_(None),
        TeachingAssignment.lab_group_id.is_(None))))
    _delete_assignments(sorted(bad_assignments), report)

    bad_blocks = set()
    bad_blocks.update(missing(LockedBlock.faculty_id, Faculty))
    bad_blocks.update(missing(LockedBlock.subject_id, Subject))
    bad_blocks.update(missing(LockedBlock.assignment_id, TeachingAssignment))
    bad_blocks.update(missing(LockedBlock.section_id, Section))
    bad_blocks.update(missing(LockedBlock.lab_group_id, LabGroup))
    _delete_locked_blocks(sorted(bad_blocks), report)

    report.add("scheduled_classes", ScheduledClass.query.filter(
        ScheduledClass.id.in_(
            missing(ScheduledClass.assignment_id, TeachingAssignment)
            + missing(ScheduledClass.room_id, Room)
            + missing(ScheduledClass.locked_block_id, LockedBlock)
        )).delete(synchronize_session=False))

    report.add("preferences", FacultyPreference.query.filter(
        FacultyPreference.id.in_(
            missing(FacultyPreference.faculty_id, Faculty)
            + missing(FacultyPreference.subject_id, Subject)
            + missing(FacultyPreference.section_id, Section)
        )).delete(synchronize_session=False))
    SpecializationMembership.query.filter(SpecializationMembership.id.in_(
        missing(SpecializationMembership.section_id, Section)
        + missing(SpecializationMembership.specialization_id, Specialization)
    )).delete(synchronize_session=False)
    Section.query.filter(Section.id.in_(
        missing(Section.preferred_theory_room_id, Room))).update(
            {Section.preferred_theory_room_id: None}, synchronize_session=False)
    return report
