"""
Additive JSON connectivity layer for the React frontend.

Everything in here is NEW and additive: no existing Jinja route, business
rule, scheduler call, import/export logic, or validation is changed by this
module. It only *reads* through the same queries/helpers the Jinja views use
and mirrors the same form-POST rules while returning machine-readable JSON.

Registered from app.py via init_api() (one import + one call at the bottom
of app.py). All routes live under /api/* and reuse the existing Flask-Login
session cookie — no new auth system, no tokens, no CORS.
"""
import uuid

from flask import Blueprint, jsonify, request, url_for
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func

from models import (db, Config, Room, Faculty, Program, Enrollment,
                    Section, LabGroup, Subject, TeachingAssignment,
                    ScheduledClass, AdminUser)
from scheduler import run_scheduler
import export as exp
import csv_import
from validators import normalize_room_name, RoomNameError

api_bp = Blueprint("api", __name__, url_prefix="/api")

TIMETABLE_VIEWS = ("section", "faculty", "room")


# ------------------------------------------------------------------ helpers
class ApiError(Exception):
    """Raise inside an API view to return a structured JSON error."""

    def __init__(self, message, status=422, field_errors=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.field_errors = field_errors


@api_bp.errorhandler(ApiError)
def _handle_api_error(err):
    payload = {"error": err.message}
    if err.field_errors:
        payload["field_errors"] = err.field_errors
    return jsonify(payload), err.status


@api_bp.errorhandler(404)
def _handle_404(err):
    return jsonify({"error": "Not found."}), 404


@api_bp.errorhandler(405)
def _handle_405(err):
    return jsonify({"error": "Method not allowed."}), 405


@api_bp.errorhandler(400)
def _handle_400(err):
    return jsonify({"error": "Bad request."}), 400


def _data():
    """Request payload as a plain dict: JSON body if sent, else form fields."""
    if request.is_json:
        body = request.get_json(silent=True)
        return dict(body) if isinstance(body, dict) else {}
    return request.form.to_dict()


def _require_str(data, field):
    value = (data.get(field) or "")
    if isinstance(value, str):
        value = value.strip()
    if not value:
        raise ApiError("Missing required fields.", 422, {field: "This field is required."})
    return value


def _optional_int(data, field, default=None):
    """Mirror the Jinja forms' blank-means-default numeric handling."""
    raw = data.get(field, "")
    if raw == "" or raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("Invalid input.", 422, {field: "Must be a whole number."})


def _required_int(data, field):
    raw = data.get(field, "")
    if raw == "" or raw is None:
        raise ApiError("Missing required fields.", 422, {field: "This field is required."})
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("Invalid input.", 422, {field: "Must be a whole number."})


def _get_config():
    return Config.query.first()


def _faculty_load_map():
    rows = db.session.query(
        TeachingAssignment.faculty_id,
        func.coalesce(func.sum(TeachingAssignment.periods_per_week), 0),
    ).group_by(TeachingAssignment.faculty_id).all()
    return {fid: total for fid, total in rows}


def _room_json(r):
    return {"id": r.id, "name": r.name, "room_type": r.room_type,
            "capacity": r.capacity, "equipment_count": r.equipment_count}


def _faculty_json(f, load=0):
    return {"id": f.id, "name": f.name, "department": f.department,
            "faculty_type": f.faculty_type, "weekly_max_hours": f.weekly_max_hours,
            "weekly_load": load}


def _config_json(cfg):
    return {"id": cfg.id, "session_name": cfg.session_name,
            "max_section_size": cfg.max_section_size,
            "max_lab_group_size": cfg.max_lab_group_size,
            "working_days": cfg.working_days, "periods": cfg.periods,
            "break_after_periods": cfg.break_after_periods,
            "max_consecutive_teaching": cfg.max_consecutive_teaching,
            "days": cfg.day_list(), "periods_list": cfg.period_list()}


def _cell_json(sc):
    """Structured equivalent of app.cell_text_for(): same fields, no HTML."""
    a = sc.assignment
    subj = a.subject.name if a.subject else "?"
    fac = a.faculty.name if a.faculty else "?"
    room = sc.room.name if sc.room else "?"
    return {"assignment_id": sc.assignment_id, "subject": subj, "faculty": fac,
            "group": a.group_label(), "room": room,
            "session_type": a.session_type,
            "kind": "Lab" if a.session_type == "practical" else "Theory",
            "css_class": "cell-practical" if a.session_type == "practical" else "cell-theory",
            "start_period": sc.start_period, "length": sc.length, "day": sc.day}


def _lane_rows_json(classes, days, periods):
    """Reuse export.build_lane_rows (the lane algorithm stays server-side);
    only the cell payload changes from an HTML string to structured data."""
    raw_rows = exp.build_lane_rows(classes, days, periods, _cell_json)
    out = []
    for row in raw_rows:
        lanes = []
        for lane in row["lanes"]:
            cells = []
            for cell in lane:
                if cell.get("empty"):
                    cells.append({"empty": True, "colspan": cell.get("colspan", 1)})
                else:
                    cells.append({"empty": False, "colspan": cell.get("colspan", 1),
                                  "class": cell.get("html")})
            lanes.append(cells)
        out.append({"day": row["day"], "lanes": lanes})
    return out


def _view_title_json(view, obj_id):
    """Same titles as app.view_title(), with JSON 404s instead of HTML ones."""
    if view == "section":
        obj = Section.query.get(obj_id)
        if not obj:
            raise ApiError("Section not found.", 404)
        return f"Timetable — {obj.name}"
    if view == "faculty":
        obj = Faculty.query.get(obj_id)
        if not obj:
            raise ApiError("Faculty not found.", 404)
        return f"Timetable — {obj.name}"
    if view == "room":
        obj = Room.query.get(obj_id)
        if not obj:
            raise ApiError("Room not found.", 404)
        return f"Timetable — Room {obj.name}"
    raise ApiError("Invalid view. Use 'section', 'faculty', or 'room'.", 404)


# ------------------------------------------------------------------ session
@api_bp.route("/login", methods=["POST"])
def api_login():
    # Same credential check as the Jinja login; only the representation differs.
    if current_user.is_authenticated:
        return jsonify({"ok": True, "username": current_user.username,
                        "message": "Already signed in."})
    data = _data()
    username = (data.get("username") or "").strip() if isinstance(data.get("username"), str) \
        else data.get("username") or ""
    user = AdminUser.query.filter_by(username=username).first()
    if user and user.check_password(data.get("password", "")):
        login_user(user)
        next_page = request.args.get("next")
        return jsonify({"ok": True, "username": user.username,
                        "redirect": next_page or url_for("dashboard")})
    return jsonify({"error": "Incorrect username or password."}), 401


@api_bp.route("/logout", methods=["POST"])
@login_required
def api_logout():
    logout_user()
    return jsonify({"ok": True, "message": "Logged out."})


@api_bp.route("/me", methods=["GET"])
@login_required
def api_me():
    return jsonify({"username": current_user.username})


@api_bp.route("/change-password", methods=["POST"])
@login_required
def api_change_password():
    # Same three checks and messages as the Jinja change-password form.
    data = _data()
    current = data.get("current_password", "")
    new = data.get("new_password", "")
    confirm = data.get("confirm_password", "")
    if not current_user.check_password(current):
        raise ApiError("Current password is incorrect.", 422,
                       {"current_password": "Current password is incorrect."})
    if len(new) < 8:
        raise ApiError("New password must be at least 8 characters.", 422,
                       {"new_password": "New password must be at least 8 characters."})
    if new != confirm:
        raise ApiError("New password and confirmation don't match.", 422,
                       {"confirm_password": "New password and confirmation don't match."})
    current_user.set_password(new)
    db.session.commit()
    return jsonify({"ok": True, "message": "Password changed."})


# ------------------------------------------------------------------- reads
@api_bp.route("/dashboard", methods=["GET"])
@login_required
def api_dashboard():
    cfg = _get_config()
    return jsonify({
        "session_name": cfg.session_name,
        "counts": {
            "rooms": Room.query.count(),
            "faculty": Faculty.query.count(),
            "programs": Program.query.count(),
            "enrollments": Enrollment.query.count(),
            "sections": Section.query.count(),
            "subjects": Subject.query.count(),
            "assignments": TeachingAssignment.query.count(),
            "scheduled": ScheduledClass.query.count(),
        },
    })


@api_bp.route("/config", methods=["GET"])
@login_required
def api_config():
    return jsonify(_config_json(_get_config()))


@api_bp.route("/rooms", methods=["GET"])
@login_required
def api_rooms():
    rooms = Room.query.order_by(Room.room_type, Room.name).all()
    return jsonify({"rooms": [_room_json(r) for r in rooms]})


@api_bp.route("/faculty", methods=["GET"])
@login_required
def api_faculty():
    faculty = Faculty.query.order_by(Faculty.name).all()
    loads = _faculty_load_map()
    return jsonify({"faculty": [_faculty_json(f, loads.get(f.id, 0)) for f in faculty]})


@api_bp.route("/faculty/<int:fid>/availability", methods=["GET"])
@login_required
def api_faculty_availability(fid):
    f = Faculty.query.get(fid)
    if not f:
        raise ApiError("Faculty not found.", 404)
    cfg = _get_config()
    return jsonify({"faculty": {"id": f.id, "name": f.name},
                    "days": cfg.day_list(), "periods": cfg.period_list(),
                    "unavailable": sorted(f.unavailable_set())})


@api_bp.route("/programs", methods=["GET"])
@login_required
def api_programs():
    programs = Program.query.order_by(Program.name).all()
    return jsonify({"programs": [{"id": p.id, "name": p.name,
                                  "department": p.department} for p in programs]})


@api_bp.route("/enrollments", methods=["GET"])
@login_required
def api_enrollments():
    enrollments = Enrollment.query.all()
    programs = Program.query.order_by(Program.name).all()
    return jsonify({
        "enrollments": [{"id": e.id, "program_id": e.program_id,
                         "program_name": e.program.name if e.program else "?",
                         "year_label": e.year_label,
                         "total_students": e.total_students} for e in enrollments],
        "programs": [{"id": p.id, "name": p.name} for p in programs],
    })


@api_bp.route("/enrollments/<int:eid>/sections", methods=["GET"])
@login_required
def api_sections(eid):
    e = Enrollment.query.get(eid)
    if not e:
        raise ApiError("Enrollment not found.", 404)
    sections = Section.query.filter_by(enrollment_id=eid).all()
    return jsonify({
        "enrollment": {"id": e.id,
                       "program_name": e.program.name if e.program else "?",
                       "year_label": e.year_label, "total_students": e.total_students},
        "sections": [{"id": s.id, "name": s.name, "student_count": s.student_count,
                      "lab_groups": [{"id": lg.id, "name": lg.name,
                                      "student_count": lg.student_count}
                                     for lg in LabGroup.query.filter_by(section_id=s.id).all()]}
                     for s in sections],
    })


@api_bp.route("/subjects", methods=["GET"])
@login_required
def api_subjects():
    subjects = Subject.query.all()
    enrollments = Enrollment.query.all()
    return jsonify({
        "subjects": [{"id": s.id, "code": s.code, "name": s.name,
                      "enrollment_id": s.enrollment_id,
                      "program_name": s.enrollment.program.name if s.enrollment and s.enrollment.program else "?",
                      "year_label": s.enrollment.year_label if s.enrollment else "?",
                      "credits": s.credits,
                      "theory_hours_per_week": s.theory_hours_per_week,
                      "practical_hours_per_week": s.practical_hours_per_week,
                      "practical_block_length": s.practical_block_length}
                     for s in subjects],
        "enrollments": [{"id": e.id,
                         "program_name": e.program.name if e.program else "?",
                         "year_label": e.year_label} for e in enrollments],
    })


@api_bp.route("/assignments", methods=["GET"])
@login_required
def api_assignments():
    assignments = TeachingAssignment.query.all()
    faculty = Faculty.query.order_by(Faculty.name).all()
    subjects = Subject.query.all()
    sections = Section.query.all()
    lab_groups = LabGroup.query.all()
    loads = _faculty_load_map()
    return jsonify({
        "assignments": [{"id": a.id, "faculty_id": a.faculty_id,
                         "faculty_name": a.faculty.name if a.faculty else "?",
                         "subject_id": a.subject_id,
                         "subject_name": a.subject.name if a.subject else "?",
                         "session_type": a.session_type,
                         "section_id": a.section_id, "lab_group_id": a.lab_group_id,
                         "group": a.group_label(),
                         "periods_per_week": a.periods_per_week,
                         "block_length": a.block_length} for a in assignments],
        "faculty": [_faculty_json(f, loads.get(f.id, 0)) for f in faculty],
        # Same conceptual shape as the Jinja template's subjects_json.
        "subjects": [{"id": s.id, "name": s.name,
                      "program_name": s.enrollment.program.name if s.enrollment and s.enrollment.program else "?",
                      "year_label": s.enrollment.year_label if s.enrollment else "?",
                      "theory_hours_per_week": s.theory_hours_per_week,
                      "practical_hours_per_week": s.practical_hours_per_week,
                      "practical_block_length": s.practical_block_length}
                     for s in subjects],
        "sections": [{"id": s.id, "name": s.name,
                      "student_count": s.student_count} for s in sections],
        "lab_groups": [{"id": lg.id, "name": lg.name,
                        "student_count": lg.student_count} for lg in lab_groups],
        "faculty_load": loads,
        "subjects_json": {s.id: {"theory": s.theory_hours_per_week,
                                 "practical": s.practical_hours_per_week,
                                 "block": s.practical_block_length or 2}
                          for s in subjects},
    })


@api_bp.route("/overview", methods=["GET"])
@login_required
def api_overview():
    enrollments = Enrollment.query.all()
    faculty = Faculty.query.order_by(Faculty.name).all()
    loads = _faculty_load_map()
    return jsonify({
        "enrollments": [{
            "id": e.id,
            "program_name": e.program.name if e.program else "?",
            "year_label": e.year_label, "total_students": e.total_students,
            "sections": [{
                "id": s.id, "name": s.name, "student_count": s.student_count,
                "lab_groups": [{"id": lg.id, "name": lg.name,
                                "student_count": lg.student_count}
                               for lg in LabGroup.query.filter_by(section_id=s.id).all()],
            } for s in Section.query.filter_by(enrollment_id=e.id).all()],
        } for e in enrollments],
        "faculty": [{
            "id": f.id, "name": f.name, "faculty_type": f.faculty_type,
            "weekly_max_hours": f.weekly_max_hours,
            "weekly_load": loads.get(f.id, 0),
            "assignments": [{
                "id": a.id,
                "subject_name": a.subject.name if a.subject else "?",
                "group": a.group_label(), "session_type": a.session_type,
                "periods_per_week": a.periods_per_week,
            } for a in TeachingAssignment.query.filter_by(faculty_id=f.id).all()],
        } for f in faculty],
    })


@api_bp.route("/timetable", methods=["GET"])
@login_required
def api_timetable_home():
    return jsonify({
        "sections": [{"id": s.id, "name": s.name} for s in Section.query.all()],
        "faculty": [{"id": f.id, "name": f.name}
                    for f in Faculty.query.order_by(Faculty.name).all()],
        "rooms": [{"id": r.id, "name": r.name} for r in Room.query.order_by(Room.name).all()],
        "has_schedule": ScheduledClass.query.count() > 0,
    })


@api_bp.route("/timetable/<view>/<int:obj_id>", methods=["GET"])
@login_required
def api_timetable_view(view, obj_id):
    # Reuse the Jinja view's query helper so filtering semantics are identical.
    from app import get_view_classes
    title = _view_title_json(view, obj_id)
    cfg = _get_config()
    days, periods = cfg.day_list(), cfg.period_list()
    classes = get_view_classes(view, obj_id)
    extra = None
    if view == "faculty":
        total = db.session.query(
            func.coalesce(func.sum(TeachingAssignment.periods_per_week), 0)
        ).filter_by(faculty_id=obj_id).scalar()
        fac = Faculty.query.get(obj_id)
        extra = f"Weekly teaching load: {total} hrs" + (
            f" (max {fac.weekly_max_hours} hrs)" if fac.weekly_max_hours else "")
    return jsonify({"title": title, "view": view, "obj_id": obj_id,
                    "days": days, "periods": periods, "extra": extra,
                    "day_rows": _lane_rows_json(classes, days, periods)})


@api_bp.route("/timetable/free", methods=["GET"])
@login_required
def api_free_faculty():
    cfg = _get_config()
    days, periods = cfg.day_list(), cfg.period_list()
    faculty = Faculty.query.order_by(Faculty.name).all()
    selected_day = request.args.get("day", days[0] if days else None)
    has_schedule = ScheduledClass.query.count() > 0
    # Same busy-cell semantics as the Jinja view: one label per busy
    # (faculty, period), blocks expanded over the periods they cover.
    busy = []
    rows = ScheduledClass.query.join(TeachingAssignment).filter(
        ScheduledClass.day == selected_day).all()
    for sc in rows:
        a = sc.assignment
        room_name = sc.room.name if sc.room else "?"
        label = f"{a.subject.name} · {a.group_label()} · Room {room_name}"
        for p in range(sc.start_period, sc.start_period + sc.length):
            busy.append({"faculty_id": a.faculty_id, "period": p, "label": label})
    payload = {"days": days, "periods": periods,
               "faculty": [{"id": f.id, "name": f.name} for f in faculty],
               "selected_day": selected_day, "busy": busy,
               "break_after": cfg.break_after_periods,
               "has_schedule": has_schedule}
    if not has_schedule:
        payload["warning"] = ("No timetable has been generated yet — everyone will show "
                              "as free. Generate one first.")
    return jsonify(payload)


# ------------------------------------------------------------------ writes
@api_bp.route("/config", methods=["POST"])
@login_required
def api_config_save():
    # Same fields and blank-break-means-0 rule as the Jinja config form.
    data = _data()
    cfg = _get_config()
    cfg.session_name = _require_str(data, "session_name")
    cfg.max_section_size = _required_int(data, "max_section_size")
    cfg.max_lab_group_size = _required_int(data, "max_lab_group_size")
    cfg.working_days = _require_str(data, "working_days")
    cfg.periods = _require_str(data, "periods")
    cfg.break_after_periods = _optional_int(data, "break_after_periods", default=0)
    cfg.max_consecutive_teaching = _required_int(data, "max_consecutive_teaching")
    db.session.commit()
    return jsonify({"ok": True, "message": "Configuration saved.",
                    "config": _config_json(cfg)})


@api_bp.route("/rooms", methods=["POST"])
@login_required
def api_room_create():
    # Same normalization + duplicate rule/messages as the Jinja rooms form.
    data = _data()
    try:
        name = normalize_room_name(data.get("name", ""))
    except RoomNameError as ex:
        raise ApiError(str(ex), 422, {"name": str(ex)})
    if Room.query.filter_by(name=name).first():
        message = f"Room '{name}' already exists — not adding a duplicate."
        raise ApiError(message, 422, {"name": message})
    r = Room(name=name, room_type=_require_str(data, "room_type"),
             capacity=_required_int(data, "capacity"),
             equipment_count=_optional_int(data, "equipment_count", default=None))
    db.session.add(r)
    db.session.commit()
    return jsonify({"ok": True, "message": f"Room '{r.name}' added.",
                    "room": _room_json(r)}), 201


@api_bp.route("/rooms/<int:room_id>/delete", methods=["POST"])
@login_required
def api_room_delete(room_id):
    r = Room.query.get(room_id)
    if not r:
        raise ApiError("Room not found.", 404)
    db.session.delete(r)
    db.session.commit()
    return jsonify({"ok": True, "message": "Room deleted."})


@api_bp.route("/faculty", methods=["POST"])
@login_required
def api_faculty_create():
    data = _data()
    f = Faculty(name=_require_str(data, "name"),
                department=data.get("department", ""),
                faculty_type=data.get("faculty_type", "") or "regular",
                weekly_max_hours=_optional_int(data, "weekly_max_hours", default=24))
    db.session.add(f)
    db.session.commit()
    return jsonify({"ok": True, "message": f"Faculty '{f.name}' added.",
                    "faculty": _faculty_json(f, 0)}), 201


@api_bp.route("/faculty/<int:fid>/delete", methods=["POST"])
@login_required
def api_faculty_delete(fid):
    f = Faculty.query.get(fid)
    if not f:
        raise ApiError("Faculty not found.", 404)
    db.session.delete(f)
    db.session.commit()
    return jsonify({"ok": True, "message": "Faculty deleted."})


@api_bp.route("/faculty/<int:fid>/availability", methods=["POST"])
@login_required
def api_faculty_availability_save(fid):
    f = Faculty.query.get(fid)
    if not f:
        raise ApiError("Faculty not found.", 404)
    if request.is_json:
        body = request.get_json(silent=True) or {}
        selected = body.get("unavailable", []) or []
    else:
        selected = request.form.getlist("unavailable")
    f.unavailable_slots = ",".join(selected)
    db.session.commit()
    return jsonify({"ok": True, "message": f"Availability updated for {f.name}.",
                    "unavailable": sorted(f.unavailable_set())})


@api_bp.route("/programs", methods=["POST"])
@login_required
def api_program_create():
    data = _data()
    p = Program(name=_require_str(data, "name"),
                department=data.get("department", ""))
    db.session.add(p)
    db.session.commit()
    return jsonify({"ok": True, "message": f"Program '{p.name}' added.",
                    "program": {"id": p.id, "name": p.name,
                                "department": p.department}}), 201


@api_bp.route("/programs/<int:pid>/delete", methods=["POST"])
@login_required
def api_program_delete(pid):
    p = Program.query.get(pid)
    if not p:
        raise ApiError("Program not found.", 404)
    db.session.delete(p)
    db.session.commit()
    return jsonify({"ok": True, "message": "Program deleted."})


@api_bp.route("/enrollments", methods=["POST"])
@login_required
def api_enrollment_create():
    # Same auto-generation as the Jinja enrollments form (sections split
    # evenly, letters A.., lab groups per section). Reuses app.split_evenly.
    from app import split_evenly, letters
    data = _data()
    cfg = _get_config()
    program_id = _required_int(data, "program_id")
    year_label = _require_str(data, "year_label")
    total_students = _required_int(data, "total_students")

    e = Enrollment(program_id=program_id, year_label=year_label,
                   total_students=total_students)
    db.session.add(e)
    db.session.flush()

    import math
    max_sec = cfg.max_section_size
    n_sections = max(1, math.ceil(total_students / max_sec))
    sizes = split_evenly(total_students, n_sections)
    prog = Program.query.get(program_id)
    base_name = f"{prog.name}-{year_label}".replace(" ", "") if prog else year_label
    created_sections = []
    for size, letter in zip(sizes, letters()):
        sec = Section(enrollment_id=e.id, name=f"{base_name}-{letter}",
                      student_count=size)
        db.session.add(sec)
        created_sections.append(sec)
    db.session.flush()

    max_lab = cfg.max_lab_group_size
    for sec in created_sections:
        n_groups = max(1, math.ceil(sec.student_count / max_lab))
        gsizes = split_evenly(sec.student_count, n_groups)
        for i, gsize in enumerate(gsizes, start=1):
            db.session.add(LabGroup(section_id=sec.id, name=f"{sec.name}-G{i}",
                                    student_count=gsize))
    db.session.commit()
    return jsonify({
        "ok": True,
        "message": f"Enrollment added: {n_sections} section(s) auto-generated.",
        "enrollment": {"id": e.id, "program_id": e.program_id,
                       "year_label": e.year_label,
                       "total_students": e.total_students},
        "sections": [{"id": s.id, "name": s.name,
                      "student_count": s.student_count} for s in created_sections],
    }), 201


@api_bp.route("/enrollments/<int:eid>/delete", methods=["POST"])
@login_required
def api_enrollment_delete(eid):
    e = Enrollment.query.get(eid)
    if not e:
        raise ApiError("Enrollment not found.", 404)
    db.session.delete(e)
    db.session.commit()
    return jsonify({"ok": True,
                    "message": "Enrollment (and its sections/lab groups) deleted."})


@api_bp.route("/subjects", methods=["POST"])
@login_required
def api_subject_create():
    # Same blank-means-None numeric handling as the Jinja subjects form.
    data = _data()
    credits_raw = data.get("credits", "")
    try:
        credits = int(credits_raw or 0) or None
    except (TypeError, ValueError):
        raise ApiError("Invalid input.", 422, {"credits": "Must be a whole number."})
    s = Subject(code=data.get("code", ""),
                name=_require_str(data, "name"),
                enrollment_id=_required_int(data, "enrollment_id"),
                credits=credits,
                theory_hours_per_week=_optional_int(data, "theory_hours_per_week"),
                practical_hours_per_week=_optional_int(data, "practical_hours_per_week"),
                practical_block_length=_optional_int(data, "practical_block_length", default=2))
    db.session.add(s)
    db.session.commit()
    return jsonify({"ok": True, "message": f"Subject '{s.name}' added.",
                    "subject": {"id": s.id, "code": s.code, "name": s.name}}), 201


@api_bp.route("/subjects/<int:sid>/delete", methods=["POST"])
@login_required
def api_subject_delete(sid):
    s = Subject.query.get(sid)
    if not s:
        raise ApiError("Subject not found.", 404)
    db.session.delete(s)
    db.session.commit()
    return jsonify({"ok": True, "message": "Subject deleted."})


@api_bp.route("/assignments", methods=["POST"])
@login_required
def api_assignment_create():
    # Same block-length rule, load accounting, and messages as the Jinja form.
    data = _data()
    session_type = _require_str(data, "session_type")
    faculty_id = _required_int(data, "faculty_id")
    periods_per_week = _required_int(data, "periods_per_week")
    block_length = _required_int(data, "block_length")

    if block_length < 1 or block_length > periods_per_week:
        message = (f"Block length ({block_length}) can't exceed periods/week "
                   f"({periods_per_week}).")
        raise ApiError(message, 422, {"block_length": message})

    fac = Faculty.query.get(faculty_id)
    if not fac:
        raise ApiError("Faculty not found.", 404)
    prior_total = db.session.query(
        func.coalesce(func.sum(TeachingAssignment.periods_per_week), 0)
    ).filter_by(faculty_id=faculty_id).scalar()

    if session_type == "theory":
        a = TeachingAssignment(
            faculty_id=faculty_id, subject_id=_required_int(data, "subject_id"),
            session_type="theory", section_id=_required_int(data, "section_id"),
            periods_per_week=periods_per_week, block_length=block_length)
    else:
        a = TeachingAssignment(
            faculty_id=faculty_id, subject_id=_required_int(data, "subject_id"),
            session_type="practical",
            lab_group_id=_required_int(data, "lab_group_id"),
            periods_per_week=periods_per_week, block_length=block_length)
    db.session.add(a)
    db.session.commit()

    new_total = prior_total + periods_per_week
    message = (f"Teaching assignment added. {fac.name}'s weekly load is now "
               f"{new_total} hrs (was {prior_total}).")
    category = "success"
    if fac.weekly_max_hours and new_total > fac.weekly_max_hours:
        message += (f" ⚠ This exceeds their configured max of "
                    f"{fac.weekly_max_hours} hrs/week.")
        category = "warning"
    return jsonify({"ok": True, "message": message, "category": category,
                    "assignment": {"id": a.id, "group": a.group_label()},
                    "faculty_load": {"before": prior_total, "after": new_total}}), 201


@api_bp.route("/assignments/<int:aid>/delete", methods=["POST"])
@login_required
def api_assignment_delete(aid):
    a = TeachingAssignment.query.get(aid)
    if not a:
        raise ApiError("Assignment not found.", 404)
    db.session.delete(a)
    db.session.commit()
    return jsonify({"ok": True, "message": "Assignment deleted."})


# ------------------------------------------------------------------- import
@api_bp.route("/import/rooms", methods=["POST"])
@login_required
def api_import_rooms():
    # Same pipeline and messages as the Jinja rooms import.
    file = request.files.get("file")
    if not file or file.filename == "":
        raise ApiError("Choose a rooms CSV file first.", 422, {"file": "Choose a rooms CSV file first."})
    counts, errors = csv_import.import_rooms_csv(file)
    return jsonify({"ok": True,
                    "message": f"Rooms import: {counts['created']} created, {counts['updated']} updated.",
                    "counts": counts, "errors": errors})


@api_bp.route("/import/workload", methods=["POST"])
@login_required
def api_import_workload():
    # Same pipeline and summary as the Jinja workload import.
    file = request.files.get("file")
    if not file or file.filename == "":
        raise ApiError("Choose a workload CSV file first.", 422,
                       {"file": "Choose a workload CSV file first."})
    cfg = _get_config()
    counts, errors = csv_import.import_workload_csv(file, cfg)
    summary = ", ".join(f"{v} {k}" for k, v in counts.items()) or "nothing new"
    return jsonify({"ok": True, "message": f"Workload import: {summary}.",
                    "counts": counts, "errors": errors})


# --------------------------------------------------------------- generation
@api_bp.route("/schedule/run", methods=["POST"])
@login_required
def api_schedule_run():
    # Invokes the EXISTING scheduler with the EXACT same inputs the Jinja
    # route uses (same time limit, same wipe-and-replace persistence).
    cfg = _get_config()
    assignments = TeachingAssignment.query.all()
    rooms = Room.query.all()
    faculty_unavail = {f.id: f.unavailable_set() for f in Faculty.query.all()}
    days = cfg.day_list()
    periods = cfg.period_list()

    status, placements, message = run_scheduler(
        assignments, rooms, faculty_unavail, days, len(periods),
        cfg.break_after_periods if cfg.break_after_periods else None,
        cfg.max_consecutive_teaching,
        time_limit_seconds=30,
    )

    if status in ("INFEASIBLE", "NO_SESSIONS"):
        raise ApiError(f"Scheduling failed: {message}", 422)

    run_id = uuid.uuid4().hex[:10]
    ScheduledClass.query.delete()
    for p in placements:
        db.session.add(ScheduledClass(
            assignment_id=p["assignment_id"], day=p["day"], start_period=p["start_period"],
            length=p["length"], room_id=p["room_id"], run_id=run_id))
    db.session.commit()
    return jsonify({"ok": True,
                    "message": f"Timetable generated ({status}). {len(placements)} class blocks placed.",
                    "status": status, "placements": len(placements), "run_id": run_id})


# ------------------------------------------------------------------ wiring
def init_api(app, login_manager):
    """Register the /api/* blueprint. The only app.py integration point."""
    from werkzeug.exceptions import NotFound

    app.register_blueprint(api_bp)

    @app.errorhandler(404)
    def _api_aware_not_found(err):
        # Unmatched /api/* URLs get JSON (blueprint handlers cannot catch
        # these: no route matched, so no blueprint is active). Every other
        # 404 keeps Werkzeug's default HTML page, exactly as today.
        if (request.path or "").startswith("/api/"):
            return jsonify({"error": "Not found."}), 404
        return NotFound()

    @login_manager.unauthorized_handler
    def _api_aware_unauthorized():
        # Machine-readable 401 for API callers; every other request falls
        # through to Flask-Login's default (flash + redirect to /login?next=)
        # by temporarily restoring the default handler for one call.
        if (request.blueprint == api_bp.name) or (request.path or "").startswith("/api/"):
            return jsonify({"error": "Authentication required."}), 401
        previous = login_manager.unauthorized_callback
        login_manager.unauthorized_callback = None
        try:
            return login_manager.unauthorized()
        finally:
            login_manager.unauthorized_callback = previous
