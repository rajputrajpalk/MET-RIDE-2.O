import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from extensions import socketio, db, users_col
from werkzeug.security import generate_password_hash

# ── Blueprints ────────────────────────────────────────────────────────────────
from routes.auth_routes  import auth_bp
from routes.main_routes  import main_bp
from routes.ride_routes  import ride_bp
from routes.admin_routes import admin_bp


from datetime import timedelta

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY")
    if not app.secret_key:
        raise RuntimeError(
            "SECRET_KEY is not set. Add it to your .env file."
        )

    # ── Session security ──────────────────────────────────────────────────────
    app.config["PERMANENT_SESSION_LIFETIME"]  = timedelta(days=7)
    app.config["SESSION_COOKIE_SAMESITE"]     = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"]     = True

    # ── Mail ─────────────────────────────────────────────────────────────────
    app.config["MAIL_SERVER"]         = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    app.config["MAIL_PORT"]           = int(os.environ.get("MAIL_PORT", 587))
    app.config["MAIL_USE_TLS"]        = os.environ.get("MAIL_USE_TLS", "True") == "True"
    app.config["MAIL_USERNAME"]       = os.environ.get("MAIL_USERNAME", "")
    app.config["MAIL_PASSWORD"]       = os.environ.get("MAIL_PASSWORD", "")
    app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", "")

    from flask_mail import Mail
    mail = Mail(app)
    app.extensions["mail"] = mail  # make accessible in blueprints

    # ── Blueprints ────────────────────────────────────────────────────────────
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(ride_bp)
    app.register_blueprint(admin_bp)

    # ── SocketIO ─────────────────────────────────────────────────────────────
    socketio.init_app(app)

    # ── Register all Socket.IO handlers (routes/socket_handlers.py) ──────────
    from routes.socket_handlers import register_handlers
    register_handlers(app)

    # ── Ensure super-admin exists in DB ───────────────────────────────────────
    with app.app_context():
        _seed_super_admin()

    # ── MongoDB index for geolocation ─────────────────────────────────────────
    try:
        from extensions import rides_col
        rides_col.create_index([("current_location", "2dsphere")], background=True)
    except Exception:
        pass

    # ── Ensure uploads folder exists ──────────────────────────────────────────
    import pathlib
    pathlib.Path(app.root_path, "static", "uploads").mkdir(parents=True, exist_ok=True)

    return app


def _seed_super_admin():
    """Create the super-admin account from environment variables if it doesn't exist."""
    email    = os.environ.get("SUPER_ADMIN_EMAIL")
    password = os.environ.get("SUPER_ADMIN_PASSWORD")
    if not email or not password:
        return
    existing = users_col.find_one({"email": email})
    if not existing:
        users_col.insert_one({
            "email":        email,
            "password":     generate_password_hash(password),
            "name":         "Super Admin",
            "role":         "super_admin",
            "is_admin":     True,
            "is_verified":  True,
            "institute":    "MET BKC",
            "department":   "Administration",
            "profile_pic":  None,
            "upi_id":       None,
            "id_card_url":  None,
            "ratings":      [],
        })

# ── Entry Point ───────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    socketio.run(
        app,
        debug=True,
        host="0.0.0.0",
        port=5000,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
