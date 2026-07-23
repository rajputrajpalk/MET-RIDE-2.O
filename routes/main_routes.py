import os
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint, render_template, request,
    session, redirect, url_for, flash, jsonify,
)
from bson import ObjectId
from extensions import (
    users_col, rides_col, alerts_col, notifications_col, history_col,
    login_required, socketio,
)

main_bp = Blueprint("main", __name__)


# ── Landing Page ──────────────────────────────────────────────────────────────

@main_bp.route("/")
def index():
    return render_template("index.html")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@main_bp.route("/dashboard")
@login_required
def dashboard():
    # Active rides (show available seats)
    active_rides = list(rides_col.find({"active": True}).sort("departure_time", 1).limit(20))
    for r in active_rides:
        r["_id"] = str(r["_id"])
        # Resolve rider name
        rider = users_col.find_one({"_id": ObjectId(r["rider_id"])}, {"name": 1, "rating_avg": 1})
        r["rider_name"] = rider["name"] if rider else "Unknown"

    user = users_col.find_one({"_id": ObjectId(session["user_id"])})

    return render_template(
        "dashboard.html",
        active_rides=active_rides,
        user=user,
    )


# ── Profile ───────────────────────────────────────────────────────────────────

@main_bp.route("/profile")
@login_required
def profile():
    user = users_col.find_one({"_id": ObjectId(session["user_id"])})
    return render_template("profile.html", user=user)


@main_bp.route("/profile/update", methods=["POST"])
@login_required
def update_profile():
    name       = (request.form.get("name") or "").strip()
    department = (request.form.get("department") or "").strip()
    upi_id     = (request.form.get("upi_id") or "").strip()

    update_fields = {}
    if name:
        update_fields["name"] = name
        session["name"] = name
    if department:
        update_fields["department"] = department
    if upi_id:
        update_fields["upi_id"] = upi_id

    # Handle profile picture upload
    pic = request.files.get("profile_pic")
    if pic and pic.filename:
        import uuid
        from werkzeug.utils import secure_filename
        from flask import current_app
        ext        = os.path.splitext(secure_filename(pic.filename))[1].lower()
        filename   = f"{uuid.uuid4().hex}{ext}"
        upload_dir = os.path.join(current_app.root_path, "static", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        pic.save(os.path.join(upload_dir, filename))
        update_fields["profile_pic"] = f"/static/uploads/{filename}"

    # Handle ID card upload
    id_card = request.files.get("id_card")
    if id_card and id_card.filename:
        import uuid
        from werkzeug.utils import secure_filename
        from flask import current_app
        ext        = os.path.splitext(secure_filename(id_card.filename))[1].lower()
        filename   = f"id_{uuid.uuid4().hex}{ext}"
        upload_dir = os.path.join(current_app.root_path, "static", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        id_card.save(os.path.join(upload_dir, filename))
        update_fields["id_card_url"] = f"/static/uploads/{filename}"

    if update_fields:
        users_col.update_one(
            {"_id": ObjectId(session["user_id"])},
            {"$set": update_fields},
        )
        flash("Profile updated successfully.", "success")
    else:
        flash("No changes detected.", "info")

    return redirect(url_for("main.profile"))


# ── SOS Alert ─────────────────────────────────────────────────────────────────

@main_bp.route("/sos-alert", methods=["POST"])
@login_required
def sos_alert():
    lat = request.form.get("lat")
    lng = request.form.get("lng")

    alert = {
        "user_id":   session["user_id"],
        "email":     session["email"],
        "name":      session.get("name", ""),
        "lat":       lat,
        "lng":       lng,
        "timestamp": datetime.now(timezone.utc),
        "status":    "active",
    }
    result = alerts_col.insert_one(alert)

    # Broadcast to all admins
    socketio.emit("sos_alert", {
        "alert_id":  str(result.inserted_id),
        "email":     session["email"],
        "name":      session.get("name", ""),
        "lat":       lat,
        "lng":       lng,
        "timestamp": alert["timestamp"].isoformat(),
    }, to="admins")

    return jsonify({"success": True, "message": "SOS alert sent. Help is on the way."})


# ── Notifications ─────────────────────────────────────────────────────────────

@main_bp.route("/api/ride/<ride_id>")
@login_required
def api_ride_detail(ride_id):
    try:
        ride = rides_col.find_one({"_id": ObjectId(ride_id)})
    except Exception:
        return jsonify({"error": "Invalid ride ID"}), 400
    if not ride:
        return jsonify({"error": "Not found"}), 404

    rider = users_col.find_one({"_id": ObjectId(ride["rider_id"])}, {"name": 1, "ratings": 1})
    ride["_id"]         = str(ride["_id"])
    ride["rider_name"]  = rider["name"] if rider else "Unknown"
    ratings = rider.get("ratings", []) if rider else []
    ride["rider_rating"] = round(sum(ratings) / len(ratings), 1) if ratings else None
    # [MET RIDE 2 - NEW FEATURE] Never expose the OTP through the public API
    ride.pop("created_at", None)
    ride.pop("otp", None)          # OTP is secret — delivered only via Socket.IO
    return jsonify(ride)


@main_bp.route("/api/notifications")
@login_required
def get_notifications():
    """Return persistent notifications for the current user."""
    notifs = list(notifications_col.find(
        {"recipient_id": session["user_id"]}
    ).sort("created_at", -1).limit(50))
    
    for n in notifs:
        n["_id"] = str(n["_id"])
        if "created_at" in n:
            # Explicit Z suffix — JS always interprets this as UTC correctly
            ts = n["created_at"]
            if hasattr(ts, "strftime"):
                n["created_at"] = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            else:
                n["created_at"] = str(ts).replace("+00:00", "Z")

    return jsonify(notifs)


@main_bp.route("/api/notifications/mark-read", methods=["POST"])
@login_required
def mark_notifications_read():
    """Mark all unread notifications as read for the current user."""
    notifications_col.update_many(
        {"recipient_id": session["user_id"], "is_read": False},
        {"$set": {"is_read": True}}
    )
    return jsonify({"success": True})


# ── Stats (New) ───────────────────────────────────────────────────────────────

@main_bp.route("/api/stats/active-riders")
@login_required
def stat_active_riders():
    rides = list(rides_col.find({"active": True}))
    results = []
    for r in rides:
        rider = users_col.find_one({"_id": ObjectId(r["rider_id"])}, {"name": 1})
        results.append({
            "name": rider["name"] if rider else "Unknown",
            "source": r["source"],
            "destination": r["destination"],
            "seats_available": r.get("seats_available", 0),
            "departure_time": r.get("departure_time", "N/A"),
            "ride_id": str(r["_id"])
        })
    return jsonify(results)


@main_bp.route("/api/stats/fuel-saved")
@login_required
def stat_fuel_saved():
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = today_start.replace(day=1)
    
    def get_sum(query):
        if request.args.get('user_only') == 'true':
            query["rider_id"] = session["user_id"]
        res = list(history_col.aggregate([{"$match": query}, {"$group": {"_id": None, "total": {"$sum": "$fuel_saved"}}}]))
        return round(res[0]["total"], 1) if res else 0.0

    today = get_sum({"completed_at": {"$gte": today_start}})
    week = get_sum({"completed_at": {"$gte": week_start}})
    month = get_sum({"completed_at": {"$gte": month_start}})
    all_time = get_sum({})
    
    return jsonify({
        "today": today,
        "week": week,
        "month": month,
        "all_time": all_time,
        "co2_avoided": round(all_time * 2.31, 1) # ~2.31 kg CO2 per L fuel
    })


@main_bp.route("/api/stats/online-riders")
@login_required
def stat_online_riders():
    limit_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    users = list(users_col.find({
        "$or": [
            {"is_online": True},
            {"last_seen": {"$gte": limit_time}}
        ]
    }))
    results = []
    for u in users:
        results.append({
            "name": u.get("name", "Unknown"),
            "is_online": u.get("is_online", False),
            "last_seen": u.get("last_seen").isoformat() if u.get("last_seen") else None
        })
    return jsonify(results)


@main_bp.route("/api/stats/my-rating")
@login_required
def stat_my_rating():
    user = users_col.find_one({"_id": ObjectId(session["user_id"])})
    ratings = user.get("ratings", [])
    avg = round(sum(ratings) / len(ratings), 1) if ratings else 0.0
    dist = {5:0, 4:0, 3:0, 2:0, 1:0}
    for r in ratings:
        k = int(round(r))
        if k in dist:
            dist[k] += 1
            
    rating_comments = user.get("rating_comments", [])
    latest_comment = rating_comments[-1] if rating_comments else "Great rider!"
    
    return jsonify({
        "average": avg,
        "total": len(ratings),
        "stars_5": dist[5],
        "stars_4": dist[4],
        "stars_3": dist[3],
        "stars_2": dist[2],
        "stars_1": dist[1],
        "latest_comment": latest_comment
    })


@main_bp.route("/api/profile/ride-stats")
@login_required
def profile_ride_stats():
    # Counts
    posted = rides_col.count_documents({"rider_id": session["user_id"]})
    joined = rides_col.count_documents({"accepted_riders": session["user_id"]})
    completed = rides_col.count_documents({"rider_id": session["user_id"], "active": False})
    
    # Last 5 posted
    posted_rides = list(rides_col.find({"rider_id": session["user_id"]}).sort("created_at", -1).limit(5))
    posted_list = [{"source": r["source"], "destination": r["destination"], "date": r.get("departure_time", "N/A")} for r in posted_rides]
    
    # Last 5 joined
    joined_rides = list(rides_col.find({"accepted_riders": session["user_id"]}).sort("created_at", -1).limit(5))
    joined_list = [{"source": r["source"], "destination": r["destination"], "rider_name": r.get("rider_name", "Unknown")} for r in joined_rides]

    return jsonify({ 
        "posted": posted, 
        "joined": joined, 
        "completed": completed,
        "posted_list": posted_list,
        "joined_list": joined_list
    })
