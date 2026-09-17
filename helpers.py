"""
Shared timetable helpers — presentation-agnostic business logic used by both
the Flask routes in app.py (export/download pages) and the JSON API layer in
api_routes.py.

Relocated verbatim from app.py during the Jinja retirement (Phase 5B) so the
API no longer imports through the Jinja route module. Behavior is unchanged:
same signatures, same queries, same output.
"""
from flask import abort

from models import (db, Config, Room, Faculty, Section, LabGroup,
                    TeachingAssignment, ScheduledClass)


def get_config():
    return Config.query.first()


def split_evenly(total, n):
    base = total // n
    rem = total % n
    sizes = [base + 1] * rem + [base] * (n - rem)
    return sizes


def letters():
    import string
    for c in string.ascii_uppercase:
        yield c


def _cfg_days_periods():
    cfg = get_config()
    return cfg, cfg.day_list(), cfg.period_list()


def cell_text_plain(sc):
    a = sc.assignment
    subj = a.subject.name if a.subject else "?"
    fac = a.faculty.name if a.faculty else "?"
    room = sc.room.name if sc.room else "?"
    group = a.group_label()
    kind = "Lab" if a.session_type == "practical" else "Th"
    return f"{subj} ({kind}) - {fac} - {group} - Room {room}"


def get_view_classes(view, obj_id):
    q = ScheduledClass.query.join(TeachingAssignment)
    if view == "section":
        q = q.filter(
            (TeachingAssignment.section_id == obj_id) |
            (TeachingAssignment.lab_group_id.in_(
                db.session.query(LabGroup.id).filter(LabGroup.section_id == obj_id)
            ))
        )
    elif view == "faculty":
        q = q.filter(TeachingAssignment.faculty_id == obj_id)
    elif view == "room":
        q = q.filter(ScheduledClass.room_id == obj_id)
    else:
        abort(404)
    return q.all()


def view_title(view, obj_id):
    if view == "section":
        obj = Section.query.get_or_404(obj_id)
        return f"Timetable — {obj.name}"
    if view == "faculty":
        obj = Faculty.query.get_or_404(obj_id)
        return f"Timetable — {obj.name}"
    if view == "room":
        obj = Room.query.get_or_404(obj_id)
        return f"Timetable — Room {obj.name}"
    abort(404)
