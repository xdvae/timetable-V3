import os
import secrets
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, send_file, abort
from flask_login import LoginManager, current_user

from models import db, init_db, Config, AdminUser
from helpers import (_cfg_days_periods, cell_text_plain, get_view_classes,
                     view_title)
import export as exp

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
# No login_view: the React SPA owns the /login page. Unauthenticated /api/*
# callers get JSON 401 via the unauthorized handler in api_routes.py; other
# unauthenticated requests get a plain 401 (React guards its own routes and
# redirects to /login?next= client-side).


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


# --------------------------------------------------------------------- auth
@app.before_request
def require_login():
    """Every backend route requires login except the API login and static files."""
    # "api.api_login" is the JSON login endpoint (see api_routes.py): it must
    # stay reachable without a session, otherwise React could never sign in.
    # "serve_react" is the React SPA shell (see below): it must stay public
    # so logged-out users can load the sign-in page; React guards its own
    # routes client-side via RequireAuth.
    allowed = {"static", "serve_react", "api.api_login"}
    if request.endpoint not in allowed and not current_user.is_authenticated:
        return login_manager.unauthorized()


# ------------------------------------------------------------------ import
SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")


@app.route("/import/sample/<kind>")
def import_sample(kind):
    fname = {"rooms": "rooms_sample.csv", "workload": "workload_sample.csv"}.get(kind)
    if not fname:
        abort(404)
    path = os.path.join(SAMPLE_DIR, fname)
    return send_file(path, as_attachment=True, download_name=fname, mimetype="text/csv")


# --------------------------------------------------------------- timetable
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


# ------------------------------------------------------- React SPA serving
# Production serves the React frontend from this same Flask process
# (Option A: single origin, so the session cookie keeps working with no
# CORS). `npm run build` inside frontend/ produces frontend/dist/, which is
# git-ignored by design. During development the Vite dev server proxies
# /api to Flask instead, so a missing dist/ only affects direct browser
# hits here — never the API, export, or sample-download routes, which are
# concrete rules and always take precedence over this catch-all.
DIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")


@app.route("/", defaults={"path": ""}, methods=["GET"])
@app.route("/<path:path>", methods=["GET"])
def serve_react(path):
    """Serve the React production build with SPA fallback."""
    if (request.path or "").startswith("/api/"):
        abort(404)  # unmatched API URLs stay machine-readable (see init_api)
    if not os.path.isdir(DIST_DIR):
        abort(404)
    base = os.path.abspath(DIST_DIR)
    target = os.path.abspath(os.path.join(base, path))
    if path and target.startswith(base + os.sep) and os.path.isfile(target):
        return send_file(target)
    index = os.path.join(base, "index.html")
    if os.path.isfile(index):
        return send_file(index)
    abort(404)


# ------------------------------------------------------------------ api layer
# JSON API for the React frontend (see api_routes.py). Registers /api/*
# routes; the download routes above (export + sample CSVs) stay on Flask
# because React calls them directly as same-origin downloads.
from api_routes import init_api
init_api(app, login_manager)


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5050)
