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

from flask import Blueprint, jsonify, request
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func

from backend.models import (db, Config, Room, Faculty, Program, Enrollment,
                            Section, LabGroup, Subject, TeachingAssignment,
                            ScheduledClass, AdminUser)
from backend.scheduler import run_scheduler
from backend import export as exp
from backend import csv_import
from backend.validators import normalize_room_name, RoomNameError

api_bp = Blueprint("api", __name__, url_prefix="/api")

TIMETABLE_VIEWS = ("section", "faculty", "room")


# ------------------------------------------------------------------ helpers
class ApiError(Exception):
    """Raise inside an API view to return a structured JSON error.

    Phase 6E: optional `code` (stable UPPER_SNAKE), `details` (structured
    conflict context), and `failures` (list of {code, message, details})
    carry the RuleResult contract to administrators without changing the
    shape of pre-6E errors (those fields are omitted when unset).
    """

    def __init__(self, message, status=422, field_errors=None, code=None,
                 details=None, failures=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.field_errors = field_errors
        self.code = code
        self.details = details
        self.failures = failures


@api_bp.errorhandler(ApiError)
def _handle_api_error(err):
    payload = {"error": err.message}
    if err.field_errors:
        payload["field_errors"] = err.field_errors
    if getattr(err, "code", None):
        payload["code"] = err.code
    if getattr(err, "details", None) is not None:
        payload["details"] = err.details
    if getattr(err, "failures", None):
        payload["failures"] = err.failures
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
    """Structured per-class cell payload: same fields the old Jinja timetable
    view rendered as HTML, without the HTML."""
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
    """Same titles as helpers.view_title(), with JSON 404s instead of HTML ones."""
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
        # Literal React dashboard path: api_login must not depend on the
        # Jinja dashboard endpoint (retired in Phase 5B). "/" is both the
        # Flask dashboard URL and the React dashboard route.
        return jsonify({"ok": True, "username": user.username,
                        "redirect": next_page or "/"})
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
    # Reuse the shared timetable query helper so filtering semantics are identical.
    from backend.helpers import get_view_classes
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
    # evenly, letters A.., lab groups per section). Reuses helpers.split_evenly.
    from backend.helpers import split_evenly, letters
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
    # Phase 6F: when specialization_id is provided, the assignment teaches
    # one specialization (cross-section group); section/lab stay NULL and
    # the subject must belong to the specialization's enrollment/cohort.
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

    spec_raw = data.get("specialization_id", "")
    if spec_raw not in ("", None):
        try:
            spec_id = int(spec_raw)
        except (TypeError, ValueError):
            raise ApiError("Invalid input.", 422,
                           {"specialization_id": "Must be a whole number."})
        from backend.models import Specialization, Subject
        spec = Specialization.query.get(spec_id)
        if not spec:
            raise ApiError("Specialization not found.", 404)
        subject_id = _required_int(data, "subject_id")
        subj = Subject.query.get(subject_id)
        if not subj:
            raise ApiError("Subject not found.", 404)
        if subj.enrollment_id != spec.enrollment_id:
            raise ApiError(
                f"Subject enrollment does not match specialization cohort.",
                422, None, code="SPECIALIZATION_ENROLLMENT",
                details={"specialization_id": spec.id,
                         "specialization_enrollment_id": spec.enrollment_id,
                         "subject_id": subj.id,
                         "subject_enrollment_id": subj.enrollment_id},
                failures=[{"code": "SPECIALIZATION_ENROLLMENT",
                           "message": "Subject enrollment does not match "
                                      "specialization cohort.",
                           "details": {"specialization_id": spec.id,
                                       "subject_id": subj.id}}])
        a = TeachingAssignment(
            faculty_id=faculty_id, subject_id=subject_id,
            session_type=session_type, section_id=None, lab_group_id=None,
            specialization_id=spec.id,
            periods_per_week=periods_per_week, block_length=block_length)
        db.session.add(a)
        db.session.commit()
        new_total = prior_total + periods_per_week
        message = (f"Specialization assignment added for '{spec.name}'. "
                   f"{fac.name}'s weekly load is now {new_total} hrs "
                   f"(was {prior_total}).")
        category = "success"
        if fac.weekly_max_hours and new_total > fac.weekly_max_hours:
            message += (f" ⚠ This exceeds their configured max of "
                        f"{fac.weekly_max_hours} hrs/week.")
            category = "warning"
        return jsonify({"ok": True, "message": message, "category": category,
                        "assignment": {"id": a.id, "group": a.group_label(),
                                       "specialization_id": spec.id},
                        "faculty_load": {"before": prior_total,
                                         "after": new_total}}), 201

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


# -------------------------------------- faculty reassignment/swap (6H)
# Thin ownership operations: every rule lives in
# backend/faculty_reassignment.py and backend/faculty_swaps.py. Routes
# only parse the request shape, call the domain service, and map the
# structured result/error onto the ApiError envelope (code/details/
# failures preserved verbatim for the future frontend).
def _assignment_json(a):
    """Serialize one TeachingAssignment (same fields as GET /assignments,
    plus specialization_id for spec assignments)."""
    return {"id": a.id, "faculty_id": a.faculty_id,
            "faculty_name": a.faculty.name if a.faculty else "?",
            "subject_id": a.subject_id,
            "subject_name": a.subject.name if a.subject else "?",
            "session_type": a.session_type,
            "section_id": a.section_id, "lab_group_id": a.lab_group_id,
            "specialization_id": getattr(a, "specialization_id", None),
            "group": a.group_label(),
            "periods_per_week": a.periods_per_week,
            "block_length": a.block_length}


def _reassign_api_error(exc):
    """Map FacultyReassignmentError onto the structured ApiError envelope."""
    payload = exc.to_payload()
    # 404 is reserved for missing assignment/faculty; every failed
    # placement validation (including unknown room) is a 422.
    status = 404 if payload["code"] in ("UNKNOWN_ASSIGNMENT",
                                        "UNKNOWN_FACULTY") else 422
    raise ApiError(payload["error"], status, None,
                   code=payload["code"], details=payload["details"],
                   failures=payload["failures"])


def _reassign_failures_api_error(failures):
    """Structured ApiError for a dry-run reassignment failure list."""
    primary = failures[0]
    raise ApiError(primary.message, 422, None,
                   code=primary.code, details=primary.details,
                   failures=[{"code": f.code, "message": f.message,
                              "details": f.details} for f in failures])


def _swap_api_error(exc):
    """Map FacultySwapError onto the structured ApiError envelope."""
    payload = exc.to_payload()
    # 404 is reserved for missing assignments; every failed placement
    # validation (including unknown room) is a 422.
    status = 404 if payload["code"] == "UNKNOWN_ASSIGNMENT" else 422
    raise ApiError(payload["error"], status, None,
                   code=payload["code"], details=payload["details"],
                   failures=payload["failures"])


def _swap_failures_api_error(failures):
    """Structured ApiError for a dry-run swap failure list."""
    primary = failures[0]
    raise ApiError(primary.message, 422, None,
                   code=primary.code, details=primary.details,
                   failures=[{"code": f.code, "message": f.message,
                              "details": f.details} for f in failures])


@api_bp.route("/assignments/<int:aid>/validate-reassign", methods=["POST"])
@login_required
def api_validate_reassign(aid):
    """DRY-RUN: check whether a faculty reassignment would be valid.

    Payload: {faculty_id} — only this field is read. No mutation.
    """
    from backend import faculty_reassignment as fr_svc
    data = _data()
    faculty_id = _required_int(data, "faculty_id")
    try:
        result = fr_svc.validate_reassignment(db, aid, faculty_id)
    except fr_svc.FacultyReassignmentError as exc:
        _reassign_api_error(exc)
    if not result.ok:
        _reassign_failures_api_error(result.failures)
    if result.noop:
        return jsonify({"ok": True, "noop": True, "dry_run": True,
                        "message": "Assignment already uses this faculty; "
                                   "nothing would change.",
                        "assignment_id": result.assignment_id,
                        "current_faculty_id": result.current_faculty_id,
                        "new_faculty_id": result.new_faculty_id,
                        "scheduled_class_ids": result.scheduled_class_ids,
                        "warning": result.warning})
    return jsonify({"ok": True, "noop": False, "dry_run": True,
                    "message": "Reassignment is valid.",
                    "assignment_id": result.assignment_id,
                    "current_faculty_id": result.current_faculty_id,
                    "new_faculty_id": result.new_faculty_id,
                    "scheduled_class_ids": result.scheduled_class_ids,
                    "warning": result.warning})


@api_bp.route("/assignments/<int:aid>/reassign", methods=["POST"])
@login_required
def api_reassign_assignment(aid):
    """REASSIGN: atomically change one assignment's faculty (no schedule
    regeneration; placements preserved). On failure nothing is modified.
    """
    from backend import faculty_reassignment as fr_svc
    data = _data()
    faculty_id = _required_int(data, "faculty_id")
    try:
        assignment, result = fr_svc.reassign_faculty(db, aid, faculty_id)
    except fr_svc.FacultyReassignmentError as exc:
        _reassign_api_error(exc)
    if result.noop:
        return jsonify({"ok": True, "noop": True,
                        "message": "Assignment already uses this faculty; "
                                   "nothing changed.",
                        "assignment": _assignment_json(assignment)})
    return jsonify({"ok": True, "noop": False,
                    "message": f"Assignment {assignment.id} reassigned to "
                               f"{assignment.faculty.name if assignment.faculty else '?'}.",
                    "assignment": _assignment_json(assignment),
                    "result": {"assignment_id": result.assignment_id,
                               "previous_faculty_id":
                                   result.current_faculty_id,
                               "faculty_id": result.new_faculty_id,
                               "scheduled_class_ids":
                                   result.scheduled_class_ids,
                               "noop": False,
                               "warning": result.warning}})


@api_bp.route("/assignments/validate-swap", methods=["POST"])
@login_required
def api_validate_swap():
    """DRY-RUN: check whether a faculty swap would be valid (no mutation).

    Payload: {assignment_a_id, assignment_b_id}.
    """
    from backend import faculty_swaps as fs_svc
    data = _data()
    a_id = _required_int(data, "assignment_a_id")
    b_id = _required_int(data, "assignment_b_id")
    try:
        result = fs_svc.validate_faculty_swap(db, a_id, b_id)
    except fs_svc.FacultySwapError as exc:
        _swap_api_error(exc)
    if not result.ok:
        _swap_failures_api_error(result.failures)
    if result.noop:
        return jsonify({"ok": True, "noop": True, "dry_run": True,
                        "message": "Both assignments already use the same "
                                   "faculty; nothing would change.",
                        "assignment_a_id": result.assignment_a_id,
                        "assignment_b_id": result.assignment_b_id,
                        "faculty_a_id": result.faculty_a_id,
                        "faculty_b_id": result.faculty_b_id,
                        "scheduled_class_ids_a":
                            result.scheduled_class_ids_a,
                        "scheduled_class_ids_b":
                            result.scheduled_class_ids_b,
                        "warnings": result.warnings})
    return jsonify({"ok": True, "noop": False, "dry_run": True,
                    "message": "Swap is valid.",
                    "assignment_a_id": result.assignment_a_id,
                    "assignment_b_id": result.assignment_b_id,
                    "faculty_a_id": result.faculty_a_id,
                    "faculty_b_id": result.faculty_b_id,
                    "scheduled_class_ids_a": result.scheduled_class_ids_a,
                    "scheduled_class_ids_b": result.scheduled_class_ids_b,
                    "warnings": result.warnings})


@api_bp.route("/assignments/swap", methods=["POST"])
@login_required
def api_swap_assignments():
    """SWAP: atomically exchange two assignments' faculties (placements
    preserved). On failure nothing is modified — never half-swapped.
    """
    from backend import faculty_swaps as fs_svc
    data = _data()
    a_id = _required_int(data, "assignment_a_id")
    b_id = _required_int(data, "assignment_b_id")
    try:
        assignment_a, assignment_b, result = fs_svc.swap_faculty(
            db, a_id, b_id)
    except fs_svc.FacultySwapError as exc:
        _swap_api_error(exc)
    if result.noop:
        return jsonify({"ok": True, "noop": True,
                        "message": "Both assignments already use the same "
                                   "faculty; nothing changed.",
                        "assignments": [_assignment_json(assignment_a),
                                        _assignment_json(assignment_b)]})
    return jsonify({"ok": True, "noop": False,
                    "message": f"Assignments {assignment_a.id} and "
                               f"{assignment_b.id} swapped faculties.",
                    "assignments": [_assignment_json(assignment_a),
                                    _assignment_json(assignment_b)],
                    "result": {"assignment_a_id": result.assignment_a_id,
                               "assignment_b_id": result.assignment_b_id,
                               "faculty_a_id": result.faculty_a_id,
                               "faculty_b_id": result.faculty_b_id,
                               "scheduled_class_ids_a":
                                   result.scheduled_class_ids_a,
                               "scheduled_class_ids_b":
                                   result.scheduled_class_ids_b,
                               "noop": False,
                               "warnings": result.warnings}})


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
    # route uses (same time limit, same persistence semantics).
    # Phase 6E: locked interdepartment blocks enter the solver as fixed
    # pre-solve occupancy (never moved); on SUCCESS only non-locked rows
    # are replaced, on FAILURE the previous schedule is preserved untouched.
    cfg = _get_config()
    assignments = TeachingAssignment.query.all()
    rooms = Room.query.all()
    faculty_unavail = {f.id: f.unavailable_set() for f in Faculty.query.all()}
    days = cfg.day_list()
    periods = cfg.period_list()
    try:
        from backend import locked_blocks as lb_svc
        locked_placements = lb_svc.query_locked_placements()
    except Exception:
        locked_placements = []
    locked_ids = sorted({p.get("locked_block_id") for p in locked_placements
                         if p.get("locked_block_id") is not None})

    # Phase 6F: specialization cohorts enter the solver as synchronized
    # sessions (same day/start per session index; rooms/faculty may differ).
    try:
        from backend import specializations as spec_svc
        specialization_data = spec_svc.query_spec_info(db)
    except Exception:
        specialization_data = {}
    # Drop empty specs (no memberships): configured but not schedulable.
    specialization_data = {sid: info for sid, info in
                           (specialization_data or {}).items()
                           if (info.get("section_ids") and
                               (info.get("total_students", 0) or 0) > 0)}

    # Phase 6I: section home-room preferences enter the solver as a
    # strictly subordinate soft objective (never a constraint). Dangling
    # ids (room deleted after configuration) are dropped by the
    # scheduler normalizer; a missing column on legacy databases means
    # no preferences at all.
    try:
        preferred_theory_rooms = {
            s.id: s.preferred_theory_room_id
            for s in Section.query.all()
            if getattr(s, "preferred_theory_room_id", None) is not None
        }
    except Exception:
        preferred_theory_rooms = {}

    status, placements, message = run_scheduler(
        assignments, rooms, faculty_unavail, days, len(periods),
        cfg.break_after_periods if cfg.break_after_periods else None,
        cfg.max_consecutive_teaching,
        time_limit_seconds=30,
        locked_placements=locked_placements,
        specialization_data=specialization_data,
        preferred_theory_rooms=preferred_theory_rooms,
    )

    if status in ("INFEASIBLE", "NO_SESSIONS"):
        # FAILURE: preserve the previous schedule — nothing is deleted or
        # written here. Locked-caused infeasibility carries a structured
        # SCHEDULING_INFEASIBLE payload identifying the blocking locks.
        # Phase 6F: specialization infeasibility carries its stable code
        # (SPECIALIZATION_SYNC/CAPACITY/OVERLAP/...) for administrators.
        msg = message or ""
        for _code in ("SPECIALIZATION_SYNC", "SPECIALIZATION_CAPACITY",
                      "SPECIALIZATION_OVERLAP", "SPECIALIZATION_ENROLLMENT",
                      "SPECIALIZATION_MEMBERSHIP"):
            if _code in msg:
                raise ApiError(
                    f"Scheduling failed: {msg}", 422, code=_code,
                    details={"reason": msg},
                    failures=[{"code": _code, "message": msg,
                               "details": {}}])
        if locked_ids and status == "INFEASIBLE":
            raise ApiError(
                f"Scheduling failed: {message}", 422,
                code="SCHEDULING_INFEASIBLE",
                details={"locked_block_ids": locked_ids,
                         "reason": message or "locked placements leave no feasible schedule"},
                failures=[{"code": "SCHEDULING_INFEASIBLE",
                           "message": message or "",
                           "details": {"locked_block_ids": locked_ids}}])
        raise ApiError(f"Scheduling failed: {message}", 422)

    # SUCCESS: atomically replace non-locked rows; locked rows stay exactly
    # where they are (same day/start/length/room/faculty).
    # Phase 6F: specialization slots are scheduler output (synchronized
    # pattern persisted per spec); spec classes link via slot_id.
    run_id = uuid.uuid4().hex[:10]
    try:
        db.session.query(ScheduledClass).filter(
            ScheduledClass.is_locked.is_(False)).delete(synchronize_session=False)
    except Exception:
        # Pre-6C database without lock columns: legacy wipe-and-replace.
        db.session.rollback()
        ScheduledClass.query.delete()
    # Separate normal vs specialization placements (spec assignments carry
    # specialization_id; ScheduledClass stays the source of truth).
    try:
        from backend.models import SpecializationSlot
        _assign_spec = {a.id: getattr(a, "specialization_id", None)
                        for a in assignments}
    except Exception:
        SpecializationSlot = None
        _assign_spec = {}
    _spec_slots_cache = {}  # (spec_id, day, start, length) -> slot_id
    for p in placements:
        spec_id = _assign_spec.get(p["assignment_id"])
        slot_id = None
        if spec_id is not None and SpecializationSlot is not None:
            key = (spec_id, p["day"], p["start_period"], p["length"])
            slot_id = _spec_slots_cache.get(key)
            if slot_id is None:
                existing = SpecializationSlot.query.filter_by(
                    specialization_id=spec_id, day=p["day"],
                    start_period=p["start_period"],
                    length=p["length"]).first()
                if existing is None:
                    row = SpecializationSlot(
                        specialization_id=spec_id, day=p["day"],
                        start_period=p["start_period"], length=p["length"])
                    db.session.add(row)
                    db.session.flush()
                    slot_id = row.id
                else:
                    slot_id = existing.id
                _spec_slots_cache[key] = slot_id
        db.session.add(ScheduledClass(
            assignment_id=p["assignment_id"], day=p["day"], start_period=p["start_period"],
            length=p["length"], room_id=p["room_id"], run_id=run_id,
            slot_id=slot_id))
    # Prune stale specialization slots no longer referenced by any class
    # (keeps the synchronized pattern exactly equal to the schedule).
    try:
        if SpecializationSlot is not None:
            live_slot_ids = set(_spec_slots_cache.values())
            # Keep slots that still back a locked class (locked rows were
            # preserved above and were not re-emitted in placements).
            for sc in ScheduledClass.query.filter(
                    ScheduledClass.slot_id.isnot(None)).all():
                if sc.slot_id is not None:
                    live_slot_ids.add(sc.slot_id)
            if live_slot_ids:
                SpecializationSlot.query.filter(
                    ~SpecializationSlot.id.in_(live_slot_ids)).delete(
                        synchronize_session=False)
            else:
                # No spec schedule at all: clear orphan slots only when no
                # spec classes remain (never touch unscheduled config? slots
                # ARE schedule output in 6F, so empty schedule clears them).
                if ScheduledClass.query.filter(
                        ScheduledClass.slot_id.isnot(None)).count() == 0:
                    SpecializationSlot.query.delete()
    except Exception:
        pass
    db.session.commit()
    return jsonify({"ok": True,
                    "message": f"Timetable generated ({status}). {len(placements)} class blocks placed.",
                    "status": status, "placements": len(placements), "run_id": run_id,
                    "locked_preserved": len(locked_ids),
                    "specializations_scheduled": len(_spec_slots_cache)})


# ------------------------------------------------------- locked blocks (6E)
@api_bp.route("/locked-blocks", methods=["GET"])
@login_required
def api_locked_blocks_list():
    """READ: return existing interdepartment locked blocks.

    ScheduledClass stays the timetable source of truth; each entry carries
    its scheduled_class_id link for auditability.
    """
    from backend.models import LockedBlock
    try:
        blocks = LockedBlock.query.filter_by(kind="interdepartment").order_by(
            LockedBlock.id).all()
    except Exception:
        # Pre-6C database: no locked-block table yet.
        return jsonify({"locked_blocks": []})
    out = []
    try:
        from backend import locked_blocks as lb_svc
        for lb in blocks:
            sc = ScheduledClass.query.filter_by(locked_block_id=lb.id).first()
            out.append(lb_svc.locked_block_json(
                lb, scheduled_class_id=sc.id if sc else None))
    except Exception:
        out = []
    return jsonify({"locked_blocks": out})


@api_bp.route("/locked-blocks", methods=["POST"])
@login_required
def api_locked_block_create():
    """CREATE: validate + atomically persist LockedBlock + ScheduledClass.

    Inputs (JSON or form): assignment_id, day, start_period, length,
    room_id, plus optional department/note (and optional explicit
    faculty_id/subject_id/section_id/lab_group_id overrides, which are
    mismatch-checked against the assignment).
    """
    from backend import locked_blocks as lb_svc
    data = _data()
    assignment_id = _required_int(data, "assignment_id")
    day = _require_str(data, "day")
    start_period = _required_int(data, "start_period")
    length = _required_int(data, "length")
    room_id = _required_int(data, "room_id")
    department = (data.get("department") or "").strip() \
        if isinstance(data.get("department"), str) else data.get("department")
    note = (data.get("note") or "").strip() \
        if isinstance(data.get("note"), str) else data.get("note")
    overrides = {}
    for field in ("faculty_id", "subject_id", "section_id", "lab_group_id"):
        if data.get(field) not in ("", None):
            overrides[field] = _required_int(data, field)
    try:
        lb, sc = lb_svc.create_locked_block(
            db, assignment_id=assignment_id, day=day,
            start_period=start_period, length=length, room_id=room_id,
            department=department or None, note=note or None, **overrides)
    except lb_svc.LockedBlockError as exc:
        payload = exc.to_payload()
        primary = exc.failures[0] if exc.failures else None
        field_errors = None
        if primary and primary.code in ("UNKNOWN_DAY", "PERIOD_OUT_OF_RANGE",
                                        "BLOCK_GEOMETRY", "BREAK_SPAN",
                                        "UNKNOWN_ASSIGNMENT", "UNKNOWN_ROOM",
                                        "ROOM_REQUIRED"):
            field_errors = {"placement": primary.message}
        raise ApiError(payload["error"], 422, field_errors,
                       code=payload["code"], details=payload["details"],
                       failures=payload["failures"])
    return jsonify({"ok": True,
                    "message": f"Locked block created for assignment {lb.assignment_id} "
                               f"on {lb.day} period {lb.start_period} (x{lb.length}).",
                    "locked_block": lb_svc.locked_block_json(lb, scheduled_class_id=sc.id),
                    "scheduled_class": {"id": sc.id, "assignment_id": sc.assignment_id,
                                        "day": sc.day, "start_period": sc.start_period,
                                        "length": sc.length, "room_id": sc.room_id,
                                        "is_locked": True,
                                        "locked_block_id": lb.id}}), 201


@api_bp.route("/locked-blocks/<int:bid>/delete", methods=["POST"])
@login_required
def api_locked_block_delete(bid):
    """DELETE/CANCEL: atomically remove a LockedBlock + its ScheduledClass.

    Removal only frees resources, so it is always permitted once the block
    exists; both rows are removed together (never a dangling class).
    """
    from backend import locked_blocks as lb_svc
    try:
        lb_svc.delete_locked_block(db, bid)
    except lb_svc.LockedBlockError as exc:
        payload = exc.to_payload()
        raise ApiError(payload["error"], 404 if "does not exist" in payload["error"] else 422,
                       code=payload["code"], details=payload["details"],
                       failures=payload["failures"])
    return jsonify({"ok": True, "message": "Locked block deleted."})


# ------------------------------------------------ manual editing (6G)
def _scheduled_class_json(sc):
    """Serialize one ScheduledClass with assignment context for the move API.

    ScheduledClass stays the source of truth; section/faculty/room views
    derive from it, so a successful move propagates immediately.
    """
    a = sc.assignment
    subj = a.subject.name if a and a.subject else "?"
    fac = a.faculty.name if a and a.faculty else "?"
    room = sc.room.name if sc.room else "?"
    section = lab_group = specialization = None
    section_id = lab_group_id = specialization_id = None
    if a is not None:
        if getattr(a, "specialization_id", None) is not None:
            specialization_id = a.specialization_id
            specialization = a.specialization.name \
                if getattr(a, "specialization", None) else \
                f"specialization:{specialization_id}"
        elif a.session_type == "practical" and a.lab_group is not None:
            lab_group_id = a.lab_group_id
            lab_group = a.lab_group.name
        elif a.section is not None:
            section_id = a.section_id
            section = a.section.name
    return {"id": sc.id, "assignment_id": sc.assignment_id,
            "day": sc.day, "start_period": sc.start_period,
            "length": sc.length, "room_id": sc.room_id, "room": room,
            "subject": subj, "subject_id": a.subject_id if a else None,
            "faculty": fac, "faculty_id": a.faculty_id if a else None,
            "session_type": a.session_type if a else None,
            "section_id": section_id, "section": section,
            "lab_group_id": lab_group_id, "lab_group": lab_group,
            "specialization_id": specialization_id,
            "specialization": specialization,
            "run_id": sc.run_id, "is_locked": bool(sc.is_locked),
            "slot_id": sc.slot_id, "locked_block_id": sc.locked_block_id}


def _manual_edit_api_error(exc):
    """Map ManualEditError onto the structured ApiError envelope."""
    payload = exc.to_payload()
    # 404 is reserved for a missing scheduled class; every failed
    # placement validation (unknown room included) is a 422.
    status = 404 if (payload["code"] == "MANUAL_EDIT_INVALID"
                     and "Scheduled class" in payload["error"]
                     and "does not exist" in payload["error"]) else 422
    primary = exc.failures[0] if exc.failures else None
    field_errors = None
    if primary and primary.code in ("UNKNOWN_DAY", "PERIOD_OUT_OF_RANGE",
                                    "BLOCK_GEOMETRY", "BREAK_SPAN",
                                    "UNKNOWN_ROOM"):
        field_errors = {"placement": primary.message}
    raise ApiError(payload["error"], status, field_errors,
                   code=payload["code"], details=payload["details"],
                   failures=payload["failures"])


def _move_failures_api_error(failures):
    """Structured ApiError for a dry-run validation failure list."""
    primary = failures[0]
    field_errors = None
    if primary.code in ("UNKNOWN_DAY", "PERIOD_OUT_OF_RANGE",
                        "BLOCK_GEOMETRY", "BREAK_SPAN", "UNKNOWN_ROOM"):
        field_errors = {"placement": primary.message}
    raise ApiError(primary.message, 422, field_errors,
                   code=primary.code, details=primary.details,
                   failures=[{"code": f.code, "message": f.message,
                              "details": f.details} for f in failures])


@api_bp.route("/schedule/classes/<int:cid>/validate-move", methods=["POST"])
@login_required
def api_validate_move(cid):
    """DRY-RUN: check whether a manual move would be valid (no mutation).

    Payload: {day, start_period, room_id} — only these three fields are
    read; anything else in the body is ignored. Lets the future drag/drop
    editor ask "can this class be moved here?" using exactly the same
    validation as the move itself.
    """
    from backend import manual_edits as me_svc
    data = _data()
    day = _require_str(data, "day")
    start_period = _required_int(data, "start_period")
    room_id = _required_int(data, "room_id")
    try:
        result = me_svc.validate_move_candidate(
            db, cid, day=day, start_period=start_period, room_id=room_id)
    except me_svc.ManualEditError as exc:
        _manual_edit_api_error(exc)
    if not result.ok:
        _move_failures_api_error(result.failures)
    if result.noop:
        return jsonify({"ok": True, "noop": True,
                        "message": "Class is already at the requested "
                                   "placement; nothing to change.",
                        "candidate": result.candidate,
                        "current": result.current})
    return jsonify({"ok": True, "noop": False,
                    "message": "Move is valid.",
                    "candidate": result.candidate,
                    "current": result.current})


@api_bp.route("/schedule/classes/<int:cid>/move", methods=["POST"])
@login_required
def api_move_class(cid):
    """MOVE: atomically relocate one scheduled class (day/start/room).

    Only day, start_period, and room_id are accepted; assignment, length,
    run_id, lock, and slot linkage are preserved and cannot be changed
    through this endpoint. On failure nothing is modified (atomic).
    """
    from backend import manual_edits as me_svc
    data = _data()
    day = _require_str(data, "day")
    start_period = _required_int(data, "start_period")
    room_id = _required_int(data, "room_id")
    try:
        sc, result = me_svc.move_scheduled_class(
            db, cid, day=day, start_period=start_period, room_id=room_id)
    except me_svc.ManualEditError as exc:
        _manual_edit_api_error(exc)
    if result.noop:
        return jsonify({"ok": True, "noop": True,
                        "message": "Class is already at the requested "
                                   "placement; nothing changed.",
                        "scheduled_class": _scheduled_class_json(sc)})
    return jsonify({"ok": True, "noop": False,
                    "message": f"Scheduled class {sc.id} moved to {sc.day} "
                               f"period {sc.start_period} (room {sc.room_id}).",
                    "scheduled_class": _scheduled_class_json(sc)})


# ------------------------------------------------- specializations (6F)
def _spec_payload(spec_id):
    """Full schedule payload for one specialization (future frontend)."""
    from backend.models import (ScheduledClass, Specialization,
                                SpecializationMembership, SpecializationSlot,
                                TeachingAssignment)
    from backend import specializations as spec_svc
    spec = Specialization.query.get(spec_id)
    if not spec:
        return None
    mems = SpecializationMembership.query.filter_by(
        specialization_id=spec.id).all()
    slots = SpecializationSlot.query.filter_by(
        specialization_id=spec.id).order_by(
            SpecializationSlot.day, SpecializationSlot.start_period).all()
    assign_ids = [a.id for a in TeachingAssignment.query.filter_by(
        specialization_id=spec.id).all()]
    if assign_ids:
        classes = ScheduledClass.query.filter(
            ScheduledClass.assignment_id.in_(assign_ids)).order_by(
                ScheduledClass.day, ScheduledClass.start_period).all()
    else:
        classes = []
    out_classes = []
    for sc in classes:
        a = TeachingAssignment.query.get(sc.assignment_id)
        fac = a.faculty.name if a and a.faculty else "?"
        room = sc.room.name if sc.room else "?"
        subj = a.subject.name if a and a.subject else "?"
        out_classes.append({"id": sc.id, "assignment_id": sc.assignment_id,
                            "subject": subj, "faculty": fac, "room": room,
                            "faculty_id": a.faculty_id if a else None,
                            "room_id": sc.room_id, "day": sc.day,
                            "start_period": sc.start_period,
                            "length": sc.length, "slot_id": sc.slot_id,
                            "session_type": a.session_type if a else spec.session_type})
    return spec_svc.specialization_json(
        spec, memberships=mems, slots=slots, scheduled=out_classes,
        total=sum(m.student_count for m in mems))


@api_bp.route("/specializations", methods=["GET"])
@login_required
def api_specializations_list():
    """READ: list specializations with memberships, slots, and schedule."""
    from backend.models import Specialization
    try:
        specs = Specialization.query.order_by(Specialization.id).all()
    except Exception:
        return jsonify({"specializations": []})
    return jsonify({"specializations": [_spec_payload(s.id) for s in specs]})


@api_bp.route("/specializations/<int:sid>", methods=["GET"])
@login_required
def api_specialization_get(sid):
    payload = _spec_payload(sid)
    if payload is None:
        raise ApiError("Specialization not found.", 404)
    return jsonify({"specialization": payload})


@api_bp.route("/specializations", methods=["POST"])
@login_required
def api_specialization_create():
    """CREATE: {name, enrollment_id, session_type?, block_length?,
    periods_per_week?}. Defaults keep the documented minimal payload
    {name, enrollment_id} working: theory / 1 / 2."""
    from backend import specializations as spec_svc
    data = _data()
    name = (data.get("name") or "").strip() \
        if isinstance(data.get("name"), str) else ""
    if not name:
        raise ApiError("Missing required fields.", 422,
                       {"name": "This field is required."})
    enrollment_id = _required_int(data, "enrollment_id")
    session_type = (data.get("session_type") or "theory").strip() \
        if isinstance(data.get("session_type"), str) \
        else (data.get("session_type") or "theory")
    block_length = _optional_int(data, "block_length", default=1)
    periods_per_week = _optional_int(data, "periods_per_week", default=2)
    try:
        spec = spec_svc.create_specialization(
            db, name=name, enrollment_id=enrollment_id,
            session_type=session_type, block_length=block_length,
            periods_per_week=periods_per_week)
    except spec_svc.SpecializationError as exc:
        payload = exc.to_payload()
        raise ApiError(payload["error"], 422, None, code=payload["code"],
                       details=payload["details"],
                       failures=payload["failures"])
    return jsonify({"ok": True,
                    "message": f"Specialization '{spec.name}' added.",
                    "specialization": _spec_payload(spec.id)}), 201


@api_bp.route("/specializations/<int:sid>/delete", methods=["POST"])
@login_required
def api_specialization_delete(sid):
    from backend import specializations as spec_svc
    try:
        spec_svc.delete_specialization(db, sid)
    except spec_svc.SpecializationError as exc:
        payload = exc.to_payload()
        raise ApiError(payload["error"], 404
                       if "does not exist" in payload["error"] else 422,
                       code=payload["code"], details=payload["details"],
                       failures=payload["failures"])
    return jsonify({"ok": True, "message": "Specialization deleted."})


@api_bp.route("/specializations/<int:sid>/memberships", methods=["POST"])
@login_required
def api_specialization_membership_upsert(sid):
    """Add/update membership (upsert): {section_id, student_count}."""
    from backend import specializations as spec_svc
    data = _data()
    section_id = _required_int(data, "section_id")
    student_count = _required_int(data, "student_count")
    try:
        row = spec_svc.add_or_update_membership(
            db, sid, section_id, student_count)
    except spec_svc.SpecializationError as exc:
        payload = exc.to_payload()
        raise ApiError(payload["error"], 422, None, code=payload["code"],
                       details=payload["details"],
                       failures=payload["failures"])
    return jsonify({"ok": True,
                    "message": "Membership saved.",
                    "membership": {"id": row.id,
                                   "specialization_id": row.specialization_id,
                                   "section_id": row.section_id,
                                   "student_count": row.student_count},
                    "specialization": _spec_payload(sid)}), 201


@api_bp.route("/specializations/<int:sid>/memberships/delete",
              methods=["POST"])
@login_required
def api_specialization_membership_delete(sid):
    """POST-style delete: {section_id}."""
    from backend import specializations as spec_svc
    data = _data()
    section_id = _required_int(data, "section_id")
    try:
        spec_svc.delete_membership(db, sid, section_id)
    except spec_svc.SpecializationError as exc:
        payload = exc.to_payload()
        raise ApiError(payload["error"], 404
                       if "No membership" in payload["error"] else 422,
                       code=payload["code"], details=payload["details"],
                       failures=payload["failures"])
    return jsonify({"ok": True, "message": "Membership deleted.",
                    "specialization": _spec_payload(sid)})


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
        # through to Flask-Login's default (a plain 401 abort — no
        # login_view is configured since React owns the /login page)
        # by temporarily restoring the default handler for one call.
        if (request.blueprint == api_bp.name) or (request.path or "").startswith("/api/"):
            return jsonify({"error": "Authentication required."}), 401
        previous = login_manager.unauthorized_callback
        login_manager.unauthorized_callback = None
        try:
            return login_manager.unauthorized()
        finally:
            login_manager.unauthorized_callback = previous
