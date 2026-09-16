import math
import os
import uuid
import secrets
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort
from flask_login import (LoginManager, login_user, logout_user, login_required,
                          current_user, UserMixin)

from models import (db, init_db, Config, Room, Faculty, Program, Enrollment,
                     Section, LabGroup, Subject, TeachingAssignment, ScheduledClass,
                     AdminUser)
from scheduler import run_scheduler
import export as exp
import csv_import
from validators import normalize_room_name, RoomNameError
from sqlalchemy import func

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Phase 1 deployment config — everything below is read from environment
# variables so the SAME codebase can be deployed once per paying institution
# just by setting different env vars (no code changes per customer).
#
#   DATABASE_URL       sqlite:///instance/timetable.db  (default) or a
#                       Postgres URL for a more durable production deploy
#   SECRET_KEY          random value used to sign session cookies — set a
#                       real one in production, or a random one is generated
#                       each boot (fine for local dev, NOT for prod: sessions
#                       won't survive a restart if you don't set this)
#   INSTITUTION_NAME    shown as the session name on first run
#   ADMIN_USERNAME      login username created on first run (default: admin)
#   ADMIN_PASSWORD      login password created on first run — REQUIRED in
#                       production; if unset, a random one is generated and
#                       printed to the server log ONCE so you can retrieve it
# ---------------------------------------------------------------------------
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///timetable.db")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
init_db(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."


@login_manager.user_loader
def load_user(user_id):
    return AdminUser.query.get(int(user_id))


def init_admin_from_env():
    """Create the first admin login from env vars, once, on startup."""
    with app.app_context():
        if AdminUser.query.count() > 0:
            return
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD")
        generated = False
        if not password:
            password = secrets.token_urlsafe(9)
            generated = True
        user = AdminUser(username=username)
        user.set_password(password)
        db.session.add(user)

        institution = os.environ.get("INSTITUTION_NAME")
        if institution:
            cfg = Config.query.first()
            if cfg:
                cfg.session_name = institution

        db.session.commit()
        if generated:
            print("=" * 70)
            print(f"  No ADMIN_PASSWORD set — generated one for first login:")
            print(f"  Username: {username}")
            print(f"  Password: {password}")
            print("  Set ADMIN_PASSWORD as an env var to control this yourself.")
            print("=" * 70)


init_admin_from_env()


def get_config():
    return Config.query.first()


# --------------------------------------------------------------------- auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        user = AdminUser.query.filter_by(username=request.form.get("username", "").strip()).first()
        if user and user.check_password(request.form.get("password", "")):
            login_user(user)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))
        flash("Incorrect username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("login"))


@app.route("/account/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not current_user.check_password(current):
            flash("Current password is incorrect.", "danger")
        elif len(new) < 8:
            flash("New password must be at least 8 characters.", "danger")
        elif new != confirm:
            flash("New password and confirmation don't match.", "danger")
        else:
            current_user.set_password(new)
            db.session.commit()
            flash("Password changed.", "success")
            return redirect(url_for("dashboard"))
    return render_template("change_password.html")


@app.before_request
def require_login():
    """Every route requires login except the login page and static files."""
    # "api.api_login" is the JSON login endpoint (see api_routes.py): it must
    # stay reachable without a session, otherwise React could never sign in.
    allowed = {"login", "static", "api.api_login"}
    if request.endpoint not in allowed and not current_user.is_authenticated:
        return login_manager.unauthorized()


# ---------------------------------------------------------------- dashboard
@app.route("/")
def dashboard():
    cfg = get_config()
    counts = {
        "rooms": Room.query.count(),
        "faculty": Faculty.query.count(),
        "programs": Program.query.count(),
        "enrollments": Enrollment.query.count(),
        "sections": Section.query.count(),
        "subjects": Subject.query.count(),
        "assignments": TeachingAssignment.query.count(),
        "scheduled": ScheduledClass.query.count(),
    }
    return render_template("dashboard.html", cfg=cfg, counts=counts)


# ------------------------------------------------------------------ config
@app.route("/config", methods=["GET", "POST"])
def config_page():
    cfg = get_config()
    if request.method == "POST":
        cfg.session_name = request.form["session_name"]
        cfg.max_section_size = int(request.form["max_section_size"])
        cfg.max_lab_group_size = int(request.form["max_lab_group_size"])
        cfg.working_days = request.form["working_days"]
        cfg.periods = request.form["periods"]
        cfg.break_after_periods = int(request.form["break_after_periods"]) if request.form["break_after_periods"] else 0
        cfg.max_consecutive_teaching = int(request.form["max_consecutive_teaching"])
        db.session.commit()
        flash("Configuration saved.", "success")
        return redirect(url_for("config_page"))
    return render_template("config.html", cfg=cfg)


# ------------------------------------------------------------------- rooms
@app.route("/rooms", methods=["GET", "POST"])
def rooms_page():
    if request.method == "POST":
        try:
            name = normalize_room_name(request.form["name"])
        except RoomNameError as ex:
            flash(str(ex), "danger")
            return redirect(url_for("rooms_page"))
        if Room.query.filter_by(name=name).first():
            flash(f"Room '{name}' already exists — not adding a duplicate.", "warning")
            return redirect(url_for("rooms_page"))
        r = Room(
            name=name,
            room_type=request.form["room_type"],
            capacity=int(request.form["capacity"]),
            equipment_count=int(request.form["equipment_count"]) if request.form.get("equipment_count") else None,
        )
        db.session.add(r)
        db.session.commit()
        flash(f"Room '{r.name}' added.", "success")
        return redirect(url_for("rooms_page"))
    rooms = Room.query.order_by(Room.room_type, Room.name).all()
    return render_template("rooms.html", rooms=rooms)


@app.route("/rooms/<int:room_id>/delete", methods=["POST"])
def delete_room(room_id):
    r = Room.query.get_or_404(room_id)
    db.session.delete(r)
    db.session.commit()
    flash("Room deleted.", "info")
    return redirect(url_for("rooms_page"))


# ---------------------------------------------------------------- faculty
@app.route("/faculty", methods=["GET", "POST"])
def faculty_page():
    if request.method == "POST":
        f = Faculty(
            name=request.form["name"],
            department=request.form.get("department", ""),
            faculty_type=request.form["faculty_type"],
            weekly_max_hours=int(request.form["weekly_max_hours"]),
        )
        db.session.add(f)
        db.session.commit()
        flash(f"Faculty '{f.name}' added.", "success")
        return redirect(url_for("faculty_page"))
    faculty = Faculty.query.order_by(Faculty.name).all()
    load_rows = db.session.query(TeachingAssignment.faculty_id,
                                  func.coalesce(func.sum(TeachingAssignment.periods_per_week), 0)) \
        .group_by(TeachingAssignment.faculty_id).all()
    faculty_load = {fid: total for fid, total in load_rows}
    return render_template("faculty.html", faculty=faculty, faculty_load=faculty_load)


@app.route("/faculty/<int:fid>/delete", methods=["POST"])
def delete_faculty(fid):
    f = Faculty.query.get_or_404(fid)
    db.session.delete(f)
    db.session.commit()
    flash("Faculty deleted.", "info")
    return redirect(url_for("faculty_page"))


@app.route("/faculty/<int:fid>/availability", methods=["GET", "POST"])
def faculty_availability(fid):
    f = Faculty.query.get_or_404(fid)
    cfg = get_config()
    days = cfg.day_list()
    periods = cfg.period_list()
    if request.method == "POST":
        selected = request.form.getlist("unavailable")  # list of "day:period_idx"
        f.unavailable_slots = ",".join(selected)
        db.session.commit()
        flash(f"Availability updated for {f.name}.", "success")
        return redirect(url_for("faculty_page"))
    unavail = f.unavailable_set()
    return render_template("faculty_availability.html", f=f, days=days, periods=periods, unavail=unavail)


# --------------------------------------------------------------- programs
@app.route("/programs", methods=["GET", "POST"])
def programs_page():
    if request.method == "POST":
        p = Program(name=request.form["name"], department=request.form.get("department", ""))
        db.session.add(p)
        db.session.commit()
        flash(f"Program '{p.name}' added.", "success")
        return redirect(url_for("programs_page"))
    programs = Program.query.order_by(Program.name).all()
    return render_template("programs.html", programs=programs)


@app.route("/programs/<int:pid>/delete", methods=["POST"])
def delete_program(pid):
    p = Program.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    flash("Program deleted.", "info")
    return redirect(url_for("programs_page"))


# ------------------------------------------------------------ enrollments
def split_evenly(total, n):
    base = total // n
    rem = total % n
    sizes = [base + 1] * rem + [base] * (n - rem)
    return sizes


def letters():
    import string
    for c in string.ascii_uppercase:
        yield c


@app.route("/enrollments", methods=["GET", "POST"])
def enrollments_page():
    cfg = get_config()
    if request.method == "POST":
        program_id = int(request.form["program_id"])
        year_label = request.form["year_label"]
        total_students = int(request.form["total_students"])

        e = Enrollment(program_id=program_id, year_label=year_label, total_students=total_students)
        db.session.add(e)
        db.session.flush()  # get e.id

        # --- auto-generate sections ---
        max_sec = cfg.max_section_size
        n_sections = max(1, math.ceil(total_students / max_sec))
        sizes = split_evenly(total_students, n_sections)
        prog = Program.query.get(program_id)
        base_name = f"{prog.name}-{year_label}".replace(" ", "")
        created_sections = []
        for size, letter in zip(sizes, letters()):
            sec = Section(enrollment_id=e.id, name=f"{base_name}-{letter}", student_count=size)
            db.session.add(sec)
            created_sections.append(sec)
        db.session.flush()

        # --- auto-generate lab groups per section ---
        max_lab = cfg.max_lab_group_size
        for sec in created_sections:
            n_groups = max(1, math.ceil(sec.student_count / max_lab))
            gsizes = split_evenly(sec.student_count, n_groups)
            for i, gsize in enumerate(gsizes, start=1):
                lg = LabGroup(section_id=sec.id, name=f"{sec.name}-G{i}", student_count=gsize)
                db.session.add(lg)

        db.session.commit()
        flash(f"Enrollment added: {n_sections} section(s) auto-generated.", "success")
        return redirect(url_for("enrollments_page"))

    enrollments = Enrollment.query.all()
    programs = Program.query.order_by(Program.name).all()
    return render_template("enrollments.html", enrollments=enrollments, programs=programs)


@app.route("/enrollments/<int:eid>/delete", methods=["POST"])
def delete_enrollment(eid):
    e = Enrollment.query.get_or_404(eid)
    db.session.delete(e)
    db.session.commit()
    flash("Enrollment (and its sections/lab groups) deleted.", "info")
    return redirect(url_for("enrollments_page"))


@app.route("/enrollments/<int:eid>/sections")
def view_sections(eid):
    e = Enrollment.query.get_or_404(eid)
    sections = Section.query.filter_by(enrollment_id=eid).all()
    lab_groups = {s.id: LabGroup.query.filter_by(section_id=s.id).all() for s in sections}
    return render_template("sections.html", enrollment=e, sections=sections, lab_groups=lab_groups)


# ------------------------------------------------------------------ subjects
@app.route("/subjects", methods=["GET", "POST"])
def subjects_page():
    if request.method == "POST":
        s = Subject(
            code=request.form.get("code", ""),
            name=request.form["name"],
            enrollment_id=int(request.form["enrollment_id"]),
            credits=int(request.form.get("credits") or 0) or None,
            theory_hours_per_week=int(request.form["theory_hours_per_week"]) if request.form.get("theory_hours_per_week") else None,
            practical_hours_per_week=int(request.form["practical_hours_per_week"]) if request.form.get("practical_hours_per_week") else None,
            practical_block_length=int(request.form["practical_block_length"]) if request.form.get("practical_block_length") else 2,
        )
        db.session.add(s)
        db.session.commit()
        flash(f"Subject '{s.name}' added.", "success")
        return redirect(url_for("subjects_page"))
    subjects = Subject.query.all()
    enrollments = Enrollment.query.all()
    return render_template("subjects.html", subjects=subjects, enrollments=enrollments)


@app.route("/subjects/<int:sid>/delete", methods=["POST"])
def delete_subject(sid):
    s = Subject.query.get_or_404(sid)
    db.session.delete(s)
    db.session.commit()
    flash("Subject deleted.", "info")
    return redirect(url_for("subjects_page"))


# ------------------------------------------------------------ assignments
@app.route("/assignments", methods=["GET", "POST"])
def assignments_page():
    if request.method == "POST":
        session_type = request.form["session_type"]
        faculty_id = int(request.form["faculty_id"])
        periods_per_week = int(request.form["periods_per_week"])
        block_length = int(request.form["block_length"])

        if block_length < 1 or block_length > periods_per_week:
            flash(f"Block length ({block_length}) can't exceed periods/week ({periods_per_week}).", "danger")
            return redirect(url_for("assignments_page"))

        fac = Faculty.query.get_or_404(faculty_id)
        prior_total = db.session.query(func.coalesce(func.sum(TeachingAssignment.periods_per_week), 0)) \
            .filter_by(faculty_id=faculty_id).scalar()

        if session_type == "theory":
            a = TeachingAssignment(
                faculty_id=faculty_id, subject_id=int(request.form["subject_id"]),
                session_type="theory", section_id=int(request.form["section_id"]),
                periods_per_week=periods_per_week, block_length=block_length,
            )
            db.session.add(a)
            added_hours = periods_per_week
        else:
            lab_group_id = int(request.form["lab_group_id"])
            a = TeachingAssignment(
                faculty_id=faculty_id, subject_id=int(request.form["subject_id"]),
                session_type="practical", lab_group_id=lab_group_id,
                periods_per_week=periods_per_week, block_length=block_length,
            )
            db.session.add(a)
            added_hours = periods_per_week
        db.session.commit()

        new_total = prior_total + added_hours
        msg = f"Teaching assignment added. {fac.name}'s weekly load is now {new_total} hrs (was {prior_total})."
        category = "success"
        if fac.weekly_max_hours and new_total > fac.weekly_max_hours:
            msg += f" ⚠ This exceeds their configured max of {fac.weekly_max_hours} hrs/week."
            category = "warning"
        flash(msg, category)
        return redirect(url_for("assignments_page"))

    assignments = TeachingAssignment.query.all()
    faculty = Faculty.query.order_by(Faculty.name).all()
    subjects = Subject.query.all()
    sections = Section.query.all()
    lab_groups = LabGroup.query.all()

    # current weekly load per faculty, for display in the dropdown
    load_rows = db.session.query(TeachingAssignment.faculty_id,
                                  func.coalesce(func.sum(TeachingAssignment.periods_per_week), 0)) \
        .group_by(TeachingAssignment.faculty_id).all()
    faculty_load = {fid: total for fid, total in load_rows}

    subjects_json = {
        s.id: {
            "theory": s.theory_hours_per_week, "practical": s.practical_hours_per_week,
            "block": s.practical_block_length or 2,
        } for s in subjects
    }

    return render_template("assignments.html", assignments=assignments, faculty=faculty,
                            subjects=subjects, sections=sections, lab_groups=lab_groups,
                            faculty_load=faculty_load, subjects_json=subjects_json)


@app.route("/assignments/<int:aid>/delete", methods=["POST"])
def delete_assignment(aid):
    a = TeachingAssignment.query.get_or_404(aid)
    db.session.delete(a)
    db.session.commit()
    flash("Assignment deleted.", "info")
    return redirect(url_for("assignments_page"))


# ------------------------------------------------------------------ import
SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")


@app.route("/import")
def import_page():
    return render_template("import.html")


@app.route("/import/rooms", methods=["POST"])
def import_rooms():
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("Choose a rooms CSV file first.", "warning")
        return redirect(url_for("import_page"))
    counts, errors = csv_import.import_rooms_csv(file)
    flash(f"Rooms import: {counts['created']} created, {counts['updated']} updated.", "success")
    if errors:
        flash("Some rows had problems: " + " | ".join(errors[:10]), "danger")
    return redirect(url_for("import_page"))


@app.route("/import/workload", methods=["POST"])
def import_workload():
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("Choose a workload CSV file first.", "warning")
        return redirect(url_for("import_page"))
    cfg = get_config()
    counts, errors = csv_import.import_workload_csv(file, cfg)
    summary = ", ".join(f"{v} {k}" for k, v in counts.items()) or "nothing new"
    flash(f"Workload import: {summary}.", "success")
    if errors:
        flash("Some rows had problems: " + " | ".join(errors[:10]), "danger")
    return redirect(url_for("import_page"))


@app.route("/import/sample/<kind>")
def import_sample(kind):
    fname = {"rooms": "rooms_sample.csv", "workload": "workload_sample.csv"}.get(kind)
    if not fname:
        abort(404)
    path = os.path.join(SAMPLE_DIR, fname)
    return send_file(path, as_attachment=True, download_name=fname, mimetype="text/csv")


# ------------------------------------------------------------------ overview
@app.route("/overview")
def overview_page():
    enrollments = Enrollment.query.all()
    sections_by_enrollment = {e.id: Section.query.filter_by(enrollment_id=e.id).all() for e in enrollments}
    lab_groups_by_section = {s.id: LabGroup.query.filter_by(section_id=s.id).all()
                              for secs in sections_by_enrollment.values() for s in secs}

    faculty = Faculty.query.order_by(Faculty.name).all()
    assignments_by_faculty = {f.id: TeachingAssignment.query.filter_by(faculty_id=f.id).all() for f in faculty}
    load_rows = db.session.query(TeachingAssignment.faculty_id,
                                  func.coalesce(func.sum(TeachingAssignment.periods_per_week), 0)) \
        .group_by(TeachingAssignment.faculty_id).all()
    faculty_load = {fid: total for fid, total in load_rows}

    return render_template("overview.html", enrollments=enrollments,
                            sections_by_enrollment=sections_by_enrollment,
                            lab_groups_by_section=lab_groups_by_section,
                            faculty=faculty, assignments_by_faculty=assignments_by_faculty,
                            faculty_load=faculty_load)


# --------------------------------------------------------------- scheduler
@app.route("/schedule/run", methods=["POST"])
def run_schedule():
    cfg = get_config()
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
        flash(f"Scheduling failed: {message}", "danger")
        return redirect(url_for("dashboard"))

    run_id = uuid.uuid4().hex[:10]
    ScheduledClass.query.delete()
    for p in placements:
        db.session.add(ScheduledClass(
            assignment_id=p["assignment_id"], day=p["day"], start_period=p["start_period"],
            length=p["length"], room_id=p["room_id"], run_id=run_id,
        ))
    db.session.commit()
    flash(f"Timetable generated ({status}). {len(placements)} class blocks placed.", "success")
    return redirect(url_for("timetable_home"))


# --------------------------------------------------------------- timetable
@app.route("/timetable")
def timetable_home():
    sections = Section.query.all()
    faculty = Faculty.query.order_by(Faculty.name).all()
    rooms = Room.query.order_by(Room.name).all()
    has_schedule = ScheduledClass.query.count() > 0
    return render_template("timetable_home.html", sections=sections, faculty=faculty,
                            rooms=rooms, has_schedule=has_schedule)


def _cfg_days_periods():
    cfg = get_config()
    return cfg, cfg.day_list(), cfg.period_list()


def cell_text_for(sc):
    a = sc.assignment
    subj = a.subject.name if a.subject else "?"
    fac = a.faculty.name if a.faculty else "?"
    room = sc.room.name if sc.room else "?"
    group = a.group_label()
    css = "cell-theory" if a.session_type == "theory" else "cell-practical"
    kind = "Theory" if a.session_type == "theory" else "Lab"
    return (f"<div class='{css}'><strong>{subj}</strong> <span class='text-muted'>({kind})</span><br>"
            f"{fac}<br><span class='text-muted'>{group} | Room {room}</span></div>")


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


@app.route("/timetable/<view>/<int:obj_id>")
def timetable_view(view, obj_id):
    cfg, days, periods = _cfg_days_periods()
    title = view_title(view, obj_id)
    classes = get_view_classes(view, obj_id)
    day_rows = exp.build_lane_rows(classes, days, periods, cell_text_for)
    extra = None
    if view == "faculty":
        total = db.session.query(func.coalesce(func.sum(TeachingAssignment.periods_per_week), 0)) \
            .filter_by(faculty_id=obj_id).scalar()
        fac = Faculty.query.get_or_404(obj_id)
        extra = f"Weekly teaching load: {total} hrs" + (f" (max {fac.weekly_max_hours} hrs)" if fac.weekly_max_hours else "")
    return render_template("timetable_view.html", title=title, days=days, periods=periods,
                            day_rows=day_rows, view=view, obj_id=obj_id, extra=extra)


@app.route("/export/<view>/<int:obj_id>/<fmt>")
def export_view(view, obj_id, fmt):
    cfg, days, periods = _cfg_days_periods()
    title = view_title(view, obj_id)
    classes = get_view_classes(view, obj_id)
    grid = exp.build_grid(classes, days, periods, cell_text_plain)

    if fmt == "csv":
        data = exp.export_csv(grid, days, periods)
        return (data, 200, {
            "Content-Type": "text/csv",
            "Content-Disposition": f"attachment; filename={title.replace(' ', '_')}.csv",
        })
    if fmt == "html":
        data = exp.export_html(grid, days, periods, title=title)
        return (data, 200, {"Content-Type": "text/html"})
    if fmt == "xlsx":
        buf = exp.export_xlsx(grid, days, periods, title=title)
        return send_file(buf, as_attachment=True, download_name=f"{title.replace(' ', '_')}.xlsx",
                          mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    abort(404)


@app.route("/timetable/free")
def free_faculty_view():
    cfg, days, periods = _cfg_days_periods()
    faculty = Faculty.query.order_by(Faculty.name).all()
    selected_day = request.args.get("day", days[0] if days else None)

    if ScheduledClass.query.count() == 0:
        flash("No timetable has been generated yet — everyone will show as free. Generate one first.", "warning")

    # busy[(faculty_id, period_idx)] = "Subject · Group · Room X" for the selected day
    busy = {}
    rows = ScheduledClass.query.join(TeachingAssignment).filter(ScheduledClass.day == selected_day).all()
    for sc in rows:
        a = sc.assignment
        room_name = sc.room.name if sc.room else "?"
        label = f"{a.subject.name} · {a.group_label()} · Room {room_name}"
        for p in range(sc.start_period, sc.start_period + sc.length):
            busy[(a.faculty_id, p)] = label

    return render_template("free_faculty.html", days=days, periods=periods, faculty=faculty,
                            selected_day=selected_day, busy=busy,
                            break_after=cfg.break_after_periods)


# ------------------------------------------------------------------ api layer
# Additive JSON connectivity for the React frontend (see api_routes.py).
# Registers /api/* routes only; every Jinja route above is unchanged.
from api_routes import init_api
init_api(app, login_manager)


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5050)
