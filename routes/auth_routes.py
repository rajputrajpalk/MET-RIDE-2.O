import os
import random
import string
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint, render_template, request,
    session, redirect, url_for, flash, jsonify, current_app,
)
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import users_col

auth_bp = Blueprint("auth", __name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _generate_otp(length=6):
    return "".join(random.choices(string.digits, k=length))


def _send_otp_email(app, email, otp):
    """Attempt to send OTP via Flask-Mail; fall back to console log."""
    try:
        from flask_mail import Message
        mail = app.extensions.get("mail")
        if mail and app.config.get("MAIL_USERNAME"):
            msg = Message(
                subject="MET Ride — Your OTP Code",
                recipients=[email],
                body=(
                    f"Your One-Time Password for MET Ride registration is:\n\n"
                    f"  {otp}\n\n"
                    f"This code expires in 10 minutes. Do not share it with anyone."
                ),
            )
            mail.send(msg)
            return True
    except Exception as exc:
        current_app.logger.warning(f"Email send failed: {exc}")
    # Dev fallback — print to terminal
    print(f"\n{'='*40}\n  MET Ride OTP for {email}: {otp}\n{'='*40}\n")
    return False


# ── Routes ────────────────────────────────────────────────────────────────────

@auth_bp.route("/login")
def login_page():
    if "user_id" in session:
        return redirect(url_for("main.dashboard"))
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login_page"))


@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    data     = request.get_json(force=True)
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password are required."}), 400

    user = users_col.find_one({"email": email})
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"success": False, "message": "Invalid email or password."}), 401

    # Populate session
    session.permanent = True
    session["user_id"]  = str(user["_id"])
    session["email"]    = user["email"]
    session["name"]     = user.get("name", email.split("@")[0])
    session["is_admin"] = user.get("is_admin", False)
    session["role"]     = user.get("role", "user")

    redirect_url = url_for("admin.admin_dashboard") if session["is_admin"] else url_for("main.dashboard")
    return jsonify({"success": True, "redirect": redirect_url})


@auth_bp.route("/api/register", methods=["POST"])
def api_register():
    """Step 1 — validate email, generate OTP, send email."""
    data  = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    name  = (data.get("name") or "").strip()

    if not email or not name:
        return jsonify({"success": False, "message": "Name and email are required."}), 400

    # Enforce MET BKC email domain
    allowed_domains = ["met.edu", "metbkc.ac.in", "metropolitanuniversity.edu.in"]
    if not any(email.endswith(f"@{d}") for d in allowed_domains):
        return jsonify({
            "success": False,
            "message": "Only MET BKC college email addresses are allowed.",
        }), 400

    if users_col.find_one({"email": email}):
        return jsonify({"success": False, "message": "An account with this email already exists."}), 409

    otp     = _generate_otp()
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)

    # Store pending registration in session (server-side only)
    session["pending_reg"] = {
        "email":   email,
        "name":    name,
        "otp":     otp,
        "expires": expires.isoformat(),
    }

    email_sent = _send_otp_email(current_app._get_current_object(), email, otp)
    msg = "OTP sent to your email." if email_sent else "OTP printed to server console (dev mode)."
    return jsonify({"success": True, "message": msg, "dev_otp": otp if not email_sent else None})


@auth_bp.route("/api/verify-otp", methods=["POST"])
def api_verify_otp():
    """Step 2 — verify OTP, create user with hashed password."""
    data     = request.get_json(force=True)
    otp_in   = (data.get("otp") or "").strip()
    password = data.get("password") or ""

    pending = session.get("pending_reg")
    if not pending:
        return jsonify({"success": False, "message": "No pending registration. Please start over."}), 400

    # Check expiry
    expires = datetime.fromisoformat(pending["expires"])
    if datetime.now(timezone.utc) > expires:
        session.pop("pending_reg", None)
        return jsonify({"success": False, "message": "OTP expired. Please register again."}), 400

    if otp_in != pending["otp"]:
        return jsonify({"success": False, "message": "Incorrect OTP."}), 400

    if len(password) < 8:
        return jsonify({"success": False, "message": "Password must be at least 8 characters."}), 400

    # Create user
    result = users_col.insert_one({
        "email":       pending["email"],
        "name":        pending["name"],
        "password":    generate_password_hash(password),
        "role":        "user",
        "is_admin":    False,
        "is_verified": False,   # Admin verifies ID card later
        "institute":   "MET BKC",
        "department":  "",
        "profile_pic": None,
        "upi_id":      None,
        "id_card_url": None,
        "ratings":     [],
        "created_at":  datetime.now(timezone.utc),
    })

    session.pop("pending_reg", None)

    # Auto-login
    session["user_id"]  = str(result.inserted_id)
    session["email"]    = pending["email"]
    session["name"]     = pending["name"]
    session["is_admin"] = False
    session["role"]     = "user"

    return jsonify({"success": True, "redirect": url_for("main.dashboard")})
