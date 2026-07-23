import os
from functools import wraps
from flask import session, redirect, url_for, flash
from pymongo import MongoClient
from flask_socketio import SocketIO

# ── MongoDB ──────────────────────────────────────────────────────────────────
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["MET_RIDE_DB"]

# Collections
users_col         = db["users"]
rides_col         = db["rides"]
history_col       = db["ride_history"]
alerts_col        = db["alerts"]
notifications_col = db["notifications"]
payments_col      = db["payments"]
cancellations_col = db["cancellations"]

# ── SocketIO ─────────────────────────────────────────────────────────────────
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading", logger=False, engineio_logger=False)


# ── Auth Decorators ───────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login_page"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login_page"))
        if not session.get("is_admin") and session.get("role") not in ["admin", "super_admin"]:
            flash("Admin access only.", "danger")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)
    return decorated


def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login_page"))
        if session.get("role") != "super_admin":
            flash("Super Admin access only.", "danger")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)
    return decorated
