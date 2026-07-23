from flask import (
    Blueprint, render_template, request,
    session, redirect, url_for, flash, jsonify,
)
from bson import ObjectId
from extensions import (
    users_col, rides_col, alerts_col, history_col, notifications_col,
    admin_required, super_admin_required, socketio,
)
from datetime import datetime, timezone

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@admin_required
def admin_dashboard():
    # Join admin room for SOS broadcasts
    return render_template("admin_dashboard.html")


@admin_bp.route("/api/stats")
@admin_required
def api_stats():
    total_users  = users_col.count_documents({})
    verified     = users_col.count_documents({"is_verified": True})
    active_rides = rides_col.count_documents({"active": True})
    total_rides  = rides_col.count_documents({}) + history_col.count_documents({})
    sos_active   = alerts_col.count_documents({"status": "active"})

    fuel_agg = list(history_col.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$fuel_saved"}}}
    ]))
    fuel_saved = round(fuel_agg[0]["total"], 2) if fuel_agg else 0.0

    return jsonify({
        "total_users":  total_users,
        "verified":     verified,
        "active_rides": active_rides,
        "total_rides":  total_rides,
        "sos_active":   sos_active,
        "fuel_saved":   fuel_saved,
    })


@admin_bp.route("/api/users")
@admin_required
def api_users():
    page  = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    skip  = (page - 1) * limit
    query = {}
    search = request.args.get("search", "").strip()
    if search:
        import re
        query["$or"] = [
            {"email": {"$regex": re.escape(search), "$options": "i"}},
            {"name":  {"$regex": re.escape(search), "$options": "i"}},
        ]

    users = list(
        users_col.find(query, {"password": 0})
                 .sort("created_at", -1)
                 .skip(skip)
                 .limit(limit)
    )
    for u in users:
        u["_id"] = str(u["_id"])
        ratings = u.get("ratings", [])
        u["avg_rating"] = round(sum(ratings) / len(ratings), 1) if ratings else None
    total = users_col.count_documents(query)
    return jsonify({"users": users, "total": total, "page": page})


@admin_bp.route("/api/verify-user/<user_id>", methods=["POST"])
@admin_required
def api_verify_user(user_id):
    try:
        users_col.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"is_verified": True}},
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


@admin_bp.route("/api/alerts")
@admin_required
def api_alerts():
    alerts = list(alerts_col.find().sort("timestamp", -1).limit(50))
    for a in alerts:
        a["_id"]       = str(a["_id"])
        a["timestamp"] = a["timestamp"].isoformat() if hasattr(a["timestamp"], "isoformat") else str(a["timestamp"])
    return jsonify(alerts)


@admin_bp.route("/api/resolve-alert/<alert_id>", methods=["POST"])
@admin_required
def api_resolve_alert(alert_id):
    try:
        alerts_col.update_one(
            {"_id": ObjectId(alert_id)},
            {"$set": {"status": "resolved"}},
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


@admin_bp.route("/api/rides")
@admin_required
def api_rides():
    rides = list(rides_col.find().sort("created_at", -1).limit(50))
    for r in rides:
        r["_id"] = str(r["_id"])
        rider = users_col.find_one({"_id": ObjectId(r["rider_id"])}, {"name": 1, "email": 1})
        r["rider_name"]  = rider["name"]  if rider else "Unknown"
        r["rider_email"] = rider["email"] if rider else ""
    return jsonify(rides)


# ── Audit Log ─────────────────────────────────────────────────────────────────

@admin_bp.route("/api/ride-logs")
@admin_required
def api_ride_logs():
    query = {}
    status = request.args.get("status")
    if status and status != "all":
        query["active"] = (status == "active")

    rides = list(rides_col.find(query).sort("created_at", -1))
    # Mix with history
    if not status or status == "completed":
        history = list(history_col.find().sort("completed_at", -1))
        rides.extend(history)
        
    for r in rides:
        r["_id"] = str(r["_id"])
        rider = users_col.find_one({"_id": ObjectId(r["rider_id"])}, {"name": 1, "email": 1})
        r["rider_name"] = rider["name"] if rider else "Unknown"
        r["rider_email"] = rider["email"] if rider else ""
        if "created_at" in r: r["created_at"] = r["created_at"].isoformat()
        if "completed_at" in r: r["completed_at"] = r["completed_at"].isoformat()
        
    return jsonify(rides)


# ── Role Management ───────────────────────────────────────────────────────────

@admin_bp.route("/admin-list", methods=["GET"])
@admin_required
def api_admin_list():
    admins = list(users_col.find({"role": {"$in": ["admin", "super_admin"]}}, {"password": 0}))
    for a in admins:
        a["_id"] = str(a["_id"])
    return jsonify(admins)


@admin_bp.route("/search-user", methods=["POST"])
@admin_required
def api_search_user():
    email = request.json.get("email", "").strip().lower()
    user = users_col.find_one({"email": email})
    if user:
        return jsonify({
            "found": True,
            "name": user.get("name"),
            "email": user.get("email"),
            "role": user.get("role", "user"),
            "user_id": str(user["_id"])
        })
    return jsonify({"found": False})


@admin_bp.route("/grant-admin", methods=["POST"])
@admin_required
def api_grant_admin():
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    password = data.get("password", "")
    confirm_password = data.get("confirm_password", "")
    
    if password != confirm_password:
        return jsonify({"success": False, "message": "Passwords do not match."}), 400
    if len(password) < 8:
        return jsonify({"success": False, "message": "Password must be at least 8 characters."}), 400
        
    if len(password) < 8:
        return jsonify({"success": False, "message": "Password must be at least 8 characters."}), 400
        
    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
        
    if user.get("role") == "super_admin":
        return jsonify({"success": False, "message": "Cannot modify a super admin."}), 400

    from werkzeug.security import generate_password_hash
    hashed_password = generate_password_hash(password)
    
    users_col.update_one(
        {"_id": user["_id"]}, 
        {"$set": {"role": "admin", "is_admin": True, "password": hashed_password}}
    )
    
    # Optional update session if same user
    if str(user["_id"]) == session.get("user_id"):
        session["role"] = "admin"
        session["is_admin"] = True
    
    # Notify user
    notif_entry = {
        "recipient_id": str(user["_id"]),
        "type":         "admin_granted",
        "message":      f"You have been granted Admin access on MET Ride by {session.get('name')}.",
        "is_read":      False,
        "created_at":   datetime.now(timezone.utc),
    }
    notifications_col.insert_one(notif_entry)
    
    # Emit socket
    unread_count = notifications_col.count_documents({"recipient_id": str(user["_id"]), "is_read": False})
    socketio.emit("new_notification", {"count": unread_count}, to=str(user["_id"]))
    
    return jsonify({"success": True, "message": f"Admin access granted to {user.get('name')}"})


@admin_bp.route("/revoke-admin", methods=["POST"])
@super_admin_required
def api_revoke_admin():
    data = request.get_json(force=True)
    user_id = data.get("user_id")

    if user_id == session["user_id"]:
        return jsonify({"success": False, "message": "You cannot revoke your own admin rights."}), 400
        
    target = users_col.find_one({"_id": ObjectId(user_id)})
    if not target or target.get("role") == "super_admin":
        return jsonify({"success": False, "message": "Cannot revoke Super Admin or user not found."}), 403
        
    users_col.update_one({"_id": ObjectId(user_id)}, {"$set": {"role": "user", "is_admin": False}})
    return jsonify({"success": True, "message": "Done"})
