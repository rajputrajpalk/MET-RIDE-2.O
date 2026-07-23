# OTP generation
import secrets
import random
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint, render_template, request,
    session, redirect, url_for, flash, jsonify,
)
from bson import ObjectId
from extensions import (
    users_col, rides_col, history_col, notifications_col,
    payments_col, cancellations_col,
    login_required, socketio,
)

ride_bp = Blueprint("ride", __name__)


# ── Post a Ride ───────────────────────────────────────────────────────────────

@ride_bp.route("/post-ride")
@login_required
def post_ride_page():
    return render_template("post_ride.html")


@ride_bp.route("/api/post-ride", methods=["POST"])
@login_required
def api_post_ride():
    data = request.get_json(force=True)

    required = ["source", "destination", "departure_time", "seats", "vehicle_type"]
    for field in required:
        if not data.get(field):
            return jsonify({"success": False, "message": f"'{field}' is required."}), 400

    try:
        seats = int(data["seats"])
        assert 1 <= seats <= 8
    except (ValueError, AssertionError):
        return jsonify({"success": False, "message": "Seats must be between 1 and 8."}), 400

    is_free = bool(data.get("is_free", False))
    price   = 0 if is_free else float(data.get("price", 0))

    ride = {
        "rider_id":        session["user_id"],
        "vehicle_type":    data["vehicle_type"],
        "seats":           seats,
        "seats_available": seats,
        "source":          data["source"],
        "destination":     data["destination"],
        "route_stops":     data.get("route_stops", []),
        "departure_time":  data["departure_time"],
        "current_location": None,
        "requests":        [],
        "accepted_riders": [],
        "active":          True,
        "fuel_saved":      0.0,
        "price":           price,
        "is_free":         is_free,
        "created_at":      datetime.now(timezone.utc),
    }
    result = rides_col.insert_one(ride)
    return jsonify({"success": True, "ride_id": str(result.inserted_id)})


# ── Request a Ride ────────────────────────────────────────────────────────────

@ride_bp.route("/request-ride")
@login_required
def request_ride_page():
    active_rides = list(rides_col.find(
        {"active": True, "seats_available": {"$gt": 0}}
    ).sort("departure_time", 1))
    for r in active_rides:
        r["_id"] = str(r["_id"])
        rider = users_col.find_one({"_id": ObjectId(r["rider_id"])}, {"name": 1})
        r["rider_name"] = rider["name"] if rider else "Unknown"
    return render_template("request_ride.html", rides=active_rides)


@ride_bp.route("/api/request-ride/<ride_id>", methods=["POST"])
@login_required
def api_request_ride(ride_id):
    try:
        ride = rides_col.find_one({"_id": ObjectId(ride_id)})
    except Exception:
        return jsonify({"success": False, "message": "Invalid ride ID."}), 400

    if not ride:
        return jsonify({"success": False, "message": "Ride not found."}), 404

    if not ride.get("active"):
        return jsonify({"success": False, "message": "This ride is no longer active."}), 400

    if ride.get("seats_available", 0) <= 0:
        return jsonify({"success": False, "message": "No seats available."}), 400

    if ride["rider_id"] == session["user_id"]:
        return jsonify({"success": False, "message": "You cannot request your own ride."}), 400

    # Check if already requested
    existing = [r for r in ride.get("requests", []) if r["requester_id"] == session["user_id"]]
    if existing:
        return jsonify({"success": False, "message": "You have already requested this ride."}), 409

    req_entry = {
        "requester_id": session["user_id"],
        "name":         session.get("name", ""),
        "email":        session["email"],
        "status":       "pending",
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    rides_col.update_one(
        {"_id": ObjectId(ride_id)},
        {"$push": {"requests": req_entry}},
    )

    # Notify ride owner via Notification System
    notif_msg = f"{session.get('name', 'Someone')} wants to join your ride from {ride['source']} to {ride['destination']}."
    notif_entry = {
        "recipient_id": ride["rider_id"],
        "type":         "join_request",
        "message":      notif_msg,
        "ride_id":      str(ride["_id"]),
        "from_user_id": session["user_id"],
        "is_read":      False,
        "created_at":   datetime.now(timezone.utc),
    }
    notifications_col.insert_one(notif_entry)

    # Emit Socket event for real-time badge update
    unread_count = notifications_col.count_documents({"recipient_id": ride["rider_id"], "is_read": False})
    socketio.emit("new_notification", {"count": unread_count}, to=ride["rider_id"])

    return jsonify({"success": True, "message": "Ride request sent."})


# ── Accept / Reject a Request ─────────────────────────────────────────────────

@ride_bp.route("/api/respond-request/<ride_id>/<requester_id>/<action>", methods=["POST"])
@login_required
def api_respond_request(ride_id, requester_id, action):
    """URL-based wrapper called by the notification bell Accept/Reject buttons.
    Delegates to api_accept_ride with action injected so both routes share logic."""
    from flask import g
    # Temporarily override the JSON body so api_accept_ride reads the right action
    import io, json as _json
    fake_body = _json.dumps({"action": action}).encode()
    request.environ["wsgi.input"]         = io.BytesIO(fake_body)
    request.environ["CONTENT_TYPE"]       = "application/json"
    request.environ["CONTENT_LENGTH"]     = str(len(fake_body))
    request._cached_json = ({"action": action}, {"action": action})
    return api_accept_ride(ride_id, requester_id)


@ride_bp.route("/api/accept-ride/<ride_id>/<requester_id>", methods=["POST"])
@login_required
def api_accept_ride(ride_id, requester_id):
    data   = request.get_json(force=True)
    action = data.get("action", "accept")  # "accept" | "reject"

    try:
        ride = rides_col.find_one({"_id": ObjectId(ride_id)})
    except Exception:
        return jsonify({"success": False, "message": "Invalid ride ID."}), 400

    if not ride or ride["rider_id"] != session["user_id"]:
        return jsonify({"success": False, "message": "Unauthorized."}), 403

    new_status = "accepted" if action == "accept" else "rejected"

    rides_col.update_one(
        {"_id": ObjectId(ride_id), "requests.requester_id": requester_id},
        {"$set": {"requests.$.status": new_status}},
    )

    # Generate 4-digit OTP on acceptance
    if action == "accept":
        otp_code = str(random.randint(1000, 9999))  # 4-digit OTP
        rides_col.update_one(
            {"_id": ObjectId(ride_id)},
            {
                "$inc":  {"seats_available": -1},
                "$push": {"accepted_riders": requester_id},
                "$set":  {
                    "otp":          otp_code,
                    "otp_verified": False,
                    "otp_for":      requester_id,
                    "status":       "active",
                },
            },
        )

    # Create notification for the requester
    rider_name = session.get("name", "Rider")
    notif_msg  = f"Your request for {ride.get('source')} → {ride.get('destination')} was {new_status} by {rider_name}."
    notif_type = f"request_{new_status}"

    # Resolve rider vehicle info for passenger confirmation
    vehicle_info = ride.get("vehicle_type", "Vehicle")

    notif_entry = {
        "recipient_id": requester_id,
        "type":         notif_type,
        "message":      notif_msg,
        "ride_id":      ride_id,
        "from_user_id": session["user_id"],
        "is_read":      False,
        "created_at":   datetime.now(timezone.utc),
    }
    notifications_col.insert_one(notif_entry)

    # Notify via SocketIO
    unread_count = notifications_col.count_documents({"recipient_id": requester_id, "is_read": False})
    socketio.emit("new_notification", {"count": unread_count}, to=requester_id)

    if action == "accept":
        # [MET RIDE 2 - NEW FEATURE] Emit ride_accepted WITH OTP only to the passenger's private room
        socketio.emit("ride_accepted", {
            "ride_id":      ride_id,
            "rider_name":   session.get("name", "Rider"),
            "rider_id":     session.get("user_id"),
            "vehicle_info": vehicle_info,
            "otp":          otp_code,   # Shown ONLY to passenger
            "message":      f"{session.get('name', 'The driver')} accepted your ride request! Your ride is confirmed."
        }, to=requester_id)   # to passenger's personal room only

    return jsonify({"success": True, "status": new_status})


# ── Active Ride Page ─────────────────────────────────────────────────────────

@ride_bp.route("/ride/active/<ride_id>")
@login_required
def active_ride_page(ride_id):
    """Dedicated active-ride screen — shows OTP input (driver) or OTP + live map (passenger)."""
    try:
        ride = rides_col.find_one({"_id": ObjectId(ride_id)})
    except Exception:
        flash("Invalid ride ID.", "danger")
        return redirect(url_for("main.dashboard"))
    if not ride:
        flash("Ride not found.", "danger")
        return redirect(url_for("main.dashboard"))

    user_id = session["user_id"]
    is_driver    = ride["rider_id"] == user_id
    is_passenger = user_id in ride.get("accepted_riders", [])

    if not is_driver and not is_passenger:
        flash("You are not part of this ride.", "warning")
        return redirect(url_for("main.dashboard"))

    # Never send the raw OTP to the template — only the passenger receives it via Socket
    ride["_id"] = str(ride["_id"])
    ride.pop("otp", None)
    ride.pop("created_at", None)

    return render_template(
        "active_ride.html",
        ride=ride,
        is_driver=is_driver,
        is_passenger=is_passenger,
    )


# ── OTP Verification (Driver submits the 4-digit code) ────────────────────────

@ride_bp.route("/api/verify-otp/<ride_id>", methods=["POST"])
@login_required
def api_verify_otp(ride_id):
    """Driver submits the 4-digit OTP received verbally from passenger."""
    data   = request.get_json(force=True)
    otp_in = str(data.get("otp", "")).strip()

    if not otp_in:
        return jsonify({"success": False, "message": "OTP is required."}), 400

    try:
        ride = rides_col.find_one({"_id": ObjectId(ride_id)})
    except Exception:
        return jsonify({"success": False, "message": "Invalid ride ID."}), 400

    if not ride:
        return jsonify({"success": False, "message": "Ride not found."}), 404

    if ride["rider_id"] != session["user_id"]:
        return jsonify({"success": False, "message": "Only the driver can verify the OTP."}), 403

    if ride.get("otp_verified"):
        return jsonify({"success": True, "message": "Already verified.", "already_verified": True})

    stored_otp = ride.get("otp", "")
    if not stored_otp or otp_in != stored_otp:
        return jsonify({"success": False, "message": "Incorrect OTP. Ask your passenger again."}), 400

    # Mark verified + set status to in_progress
    rides_col.update_one(
        {"_id": ObjectId(ride_id)},
        {"$set": {"otp_verified": True, "status": "in_progress"}},
    )

    # Emit to ride room (driver + passenger both hear this)
    passenger_id = ride.get("otp_for", "")
    verified_ts  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    socketio.emit("otp_verified", {
        "ride_id":     ride_id,
        "rider_name":  session.get("name", "Driver"),
        "verified_at": verified_ts,
    }, to=f"ride_{ride_id}")

    # Also push directly to passenger's personal room
    if passenger_id:
        socketio.emit("otp_verified", {
            "ride_id":     ride_id,
            "rider_name":  session.get("name", "Driver"),
            "verified_at": verified_ts,
        }, to=passenger_id)
        # Emit ride_started for passenger UI transition
        socketio.emit("ride_started", {
            "ride_id":    ride_id,
            "rider_name": session.get("name", "Driver"),
        }, to=passenger_id)

    return jsonify({"success": True, "message": "OTP verified! Live tracking is now active."})


# ── Ride Location Polling Endpoint ────────────────────────────────────────────

@ride_bp.route("/api/ride-location/<ride_id>")
@login_required
def api_get_ride_location(ride_id):
    """Return the driver's last known location for passenger map polling (every 4 s)."""
    # Try the in-memory cache first (fastest path)
    from routes.socket_handlers import get_last_location
    cached = get_last_location(ride_id)
    if cached:
        return jsonify({"success": True, **cached})

    # Fall back to DB
    try:
        ride = rides_col.find_one(
            {"_id": ObjectId(ride_id)},
            {"current_location": 1, "rider_id": 1, "otp_verified": 1},
        )
    except Exception:
        return jsonify({"success": False, "message": "Invalid ride ID."}), 400

    if not ride:
        return jsonify({"success": False, "message": "Ride not found."}), 404

    loc = ride.get("current_location")
    if not loc or not loc.get("coordinates"):
        return jsonify({"success": False, "message": "No location data yet."}), 404

    lng, lat = loc["coordinates"]
    return jsonify({
        "success":    True,
        "lat":        lat,
        "lng":        lng,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


# ── Legacy OTP Verification Route (kept for backward compat) ──────────────────

@ride_bp.route("/ride/verify-otp", methods=["POST"])
@login_required
def api_verify_ride_otp():
    """Driver submits the OTP they received verbally from the passenger."""
    data    = request.get_json(force=True)
    ride_id = data.get("ride_id", "").strip()
    otp_in  = str(data.get("otp", "")).strip()

    if not ride_id or not otp_in:
        return jsonify({"success": False, "message": "ride_id and otp are required."}), 400

    try:
        ride = rides_col.find_one({"_id": ObjectId(ride_id)})
    except Exception:
        return jsonify({"success": False, "message": "Invalid ride ID."}), 400

    if not ride:
        return jsonify({"success": False, "message": "Ride not found."}), 404

    # Only the driver (rider_id) may submit the OTP
    if ride["rider_id"] != session["user_id"]:
        return jsonify({"success": False, "message": "Only the driver can verify the OTP."}), 403

    if ride.get("otp_verified"):
        return jsonify({"success": True, "message": "Already verified.", "already_verified": True})

    stored_otp = ride.get("otp", "")
    if not stored_otp or otp_in != stored_otp:
        return jsonify({"success": False, "message": "Incorrect OTP. Ask your passenger again."}), 400

    # Mark verified in DB
    rides_col.update_one(
        {"_id": ObjectId(ride_id)},
        {"$set": {"otp_verified": True}}
    )

    # Emit otp_verified to the ride room — both driver AND passenger hear this
    passenger_id = ride.get("otp_for", "")
    socketio.emit("otp_verified", {
        "ride_id":     ride_id,
        "rider_name":  session.get("name", "Driver"),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }, to=f"ride_{ride_id}")

    # Also notify the passenger directly via their personal room in case they missed the room event
    if passenger_id:
        socketio.emit("otp_verified", {
            "ride_id":     ride_id,
            "rider_name":  session.get("name", "Driver"),
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }, to=passenger_id)

    return jsonify({"success": True, "message": "OTP verified! Live tracking is now active."})


# [MET RIDE 2 - NEW FEATURE] OTP Status Query (driver page-load restore)
@ride_bp.route("/api/ride/<ride_id>/otp-status")
@login_required
def api_otp_status(ride_id):
    """Returns otp_verified status for a ride — used by driver to restore widget state on reload."""
    try:
        ride = rides_col.find_one(
            {"_id": ObjectId(ride_id)},
            {"otp_verified": 1, "rider_id": 1, "otp_for": 1, "accepted_riders": 1}
        )
    except Exception:
        return jsonify({"error": "Invalid ride ID"}), 400
    if not ride:
        return jsonify({"error": "Not found"}), 404

    user_id     = session["user_id"]
    is_driver   = ride["rider_id"] == user_id
    is_passenger = user_id in ride.get("accepted_riders", [])

    return jsonify({
        "otp_verified": ride.get("otp_verified", False),
        "is_driver":    is_driver,
        "is_passenger": is_passenger,
    })


# ── Complete a Ride ───────────────────────────────────────────────────────────

@ride_bp.route("/api/complete-ride/<ride_id>", methods=["POST"])
@login_required
def api_complete_ride(ride_id):
    try:
        ride = rides_col.find_one({"_id": ObjectId(ride_id)})
    except Exception:
        return jsonify({"success": False, "message": "Invalid ride ID."}), 400

    if not ride or ride["rider_id"] != session["user_id"]:
        return jsonify({"success": False, "message": "Unauthorized."}), 403

    if not ride.get("active"):
        return jsonify({"success": False, "message": "Ride is already completed."}), 400

    # Calculate fuel saved (rough estimate: 0.05 L/km per passenger)
    accepted_count = len(ride.get("accepted_riders", []))
    fuel_saved     = round(accepted_count * 0.05 * 10, 2)  # assume avg 10 km

    # Archive
    archived = dict(ride)
    archived["active"]      = False
    archived["completed_at"] = datetime.now(timezone.utc)
    archived["fuel_saved"]  = fuel_saved
    history_col.insert_one(archived)

    # Mark original as inactive
    rides_col.update_one(
        {"_id": ObjectId(ride_id)},
        {"$set": {"active": False, "fuel_saved": fuel_saved}},
    )

    return jsonify({"success": True, "fuel_saved": fuel_saved})


# ── My Ride History ───────────────────────────────────────────────────────────

@ride_bp.route("/api/rides/my-history")
@login_required
def api_my_history():
    user_id = session["user_id"]
    
    # Query: User is the rider OR user is in accepted_riders
    query = {
        "$or": [
            {"rider_id": user_id},
            {"accepted_riders": user_id}
        ]
    }
    
    my_rides = list(rides_col.find(query).sort("created_at", -1))
    
    for r in my_rides:
        r["_id"] = str(r["_id"])
        # Resolve rider name if not the current user
        if r["rider_id"] != user_id:
            rider = users_col.find_one({"_id": ObjectId(r["rider_id"])}, {"name": 1})
            r["rider_name"] = rider["name"] if rider else "Unknown"
        else:
            r["rider_name"] = "You"
            
        # Clean up Mongo fields
        r.pop("created_at", None)
        r.pop("completed_at", None)
        
    return jsonify(my_rides)


# ── Rate a Rider ──────────────────────────────────────────────────────────────

@ride_bp.route("/api/rate-rider/<rider_id>", methods=["POST"])
@login_required
def api_rate_rider(rider_id):
    data   = request.get_json(force=True)
    rating = data.get("rating")
    try:
        rating = float(rating)
        assert 1.0 <= rating <= 5.0
    except (TypeError, ValueError, AssertionError):
        return jsonify({"success": False, "message": "Rating must be between 1 and 5."}), 400

    users_col.update_one(
        {"_id": ObjectId(rider_id)},
        {"$push": {"ratings": rating}},
    )
    return jsonify({"success": True})


# ── Nearby & Upcoming Rides (Auto-Suggestion) ─────────────────────────────────

@ride_bp.route("/api/rides/nearby", methods=["POST"])
@login_required
def api_rides_nearby():
    data = request.get_json(force=True)
    lat = float(data.get("lat"))
    lng = float(data.get("lng"))
    radius_km = float(data.get("radius_km", 5))
    
    max_distance_meters = radius_km * 1000
    
    nearby_rides = list(rides_col.find({
        "active": True,
        "seats_available": {"$gt": 0},
        "current_location": {
            "$nearSphere": {
                "$geometry": {
                    "type": "Point",
                    "coordinates": [lng, lat]
                },
                "$maxDistance": max_distance_meters
            }
        }
    }).limit(5))
    
    for r in nearby_rides:
        r["_id"] = str(r["_id"])
        rider = users_col.find_one({"_id": ObjectId(r["rider_id"])}, {"name": 1})
        r["rider_name"] = rider["name"] if rider else "Unknown"
        r.pop("created_at", None)
        
    return jsonify(nearby_rides)


@ride_bp.route("/api/rides/upcoming")
@login_required
def api_rides_upcoming():
    upcoming_rides = list(rides_col.find({
        "active": True,
        "seats_available": {"$gt": 0},
    }).sort("created_at", -1).limit(5))
    
    for r in upcoming_rides:
        r["_id"] = str(r["_id"])
        rider = users_col.find_one({"_id": ObjectId(r["rider_id"])}, {"name": 1})
        r["rider_name"] = rider["name"] if rider else "Unknown"
        r.pop("created_at", None)
        
    return jsonify(upcoming_rides)


# ── Payments ──────────────────────────────────────────────────────────────────

@ride_bp.route("/api/payment/process", methods=["POST"])
@login_required
def api_payment_process():
    data = request.get_json(force=True)
    import uuid
    tx_ref = "MET-" + uuid.uuid4().hex[:8].upper()
    
    payment = {
        "ride_id": data.get("ride_id"),
        "payer_id": session["user_id"],
        "rider_id": data.get("rider_id", "dummy"),
        "amount": data.get("amount", 0),
        "method": data.get("method"),
        "status": "completed",
        "transaction_ref": tx_ref,
        "created_at": datetime.now(timezone.utc)
    }
    payments_col.insert_one(payment)
    return jsonify({"success": True, "transaction_ref": tx_ref, "message": "Payment successful."})


# ── Cancel & Refund ───────────────────────────────────────────────────────────

@ride_bp.route("/api/rides/cancel", methods=["POST"])
@login_required
def api_rides_cancel():
    data = request.get_json(force=True)
    ride_id = data.get("ride_id")
    reason = data.get("reason", "")
    reason_text = data.get("reason_text", "")
    
    ride = rides_col.find_one({"_id": ObjectId(ride_id)})
    if not ride:
        return jsonify({"success": False, "message": "Not found."}), 404
        
    is_rider = ride["rider_id"] == session["user_id"]
    is_passenger = session["user_id"] in ride.get("accepted_riders", [])
    
    if not is_rider and not is_passenger:
        return jsonify({"success": False, "message": "Unauthorized."}), 403
        
    refund_issued = False
    payment = payments_col.find_one({"ride_id": ride_id, "payer_id": session["user_id"]})
    if payment:
        payments_col.update_one({"_id": payment["_id"]}, {"$set": {"status": "refunded"}})
        refund_issued = True
        
    cancellations_col.insert_one({
        "ride_id": ride_id,
        "cancelled_by": session["user_id"],
        "role": "rider" if is_rider else "passenger",
        "reason": reason,
        "reason_text": reason_text,
        "refund_issued": refund_issued,
        "cancelled_at": datetime.now(timezone.utc)
    })
    
    if is_rider:
        rides_col.update_one({"_id": ObjectId(ride_id)}, {"$set": {"active": False, "cancelled": True, "cancel_reason": reason}})
        for p_id in ride.get("accepted_riders", []):
            notifications_col.insert_one({
                "recipient_id": p_id,
                "type": "ride_cancelled",
                "message": f"Your ride to {ride.get('destination')} was cancelled by the rider.",
                "is_read": False,
                "created_at": datetime.now(timezone.utc)
            })
            socketio.emit("new_notification", {"count": 1}, to=p_id)
            if refund_issued:
                notifications_col.insert_one({
                    "recipient_id": p_id,
                    "type": "refund_issued",
                    "message": f"Your ₹{payment.get('amount')} payment for {ride.get('source')} has been refunded. Ref: {payment.get('transaction_ref')}",
                    "is_read": False,
                    "created_at": datetime.now(timezone.utc)
                })
                socketio.emit("new_notification", {"count": 1}, to=p_id)
        socketio.emit("ride_cancelled", {"ride_id": ride_id}, to=ride_id)
        
    else:
        # Passenger
        rides_col.update_one(
            {"_id": ObjectId(ride_id)}, 
            {"$pull": {"accepted_riders": session["user_id"]}, "$inc": {"seats_available": 1}}
        )
        notifications_col.insert_one({
            "recipient_id": ride["rider_id"],
            "type": "passenger_cancelled",
            "message": f"{session.get('name', 'A passenger')} cancelled their seat for {ride.get('destination')}.",
            "is_read": False,
            "created_at": datetime.now(timezone.utc)
        })
        socketio.emit("new_notification", {"count": 1}, to=ride["rider_id"])
        
    return jsonify({"success": True, "message": "Cancelled successfully."})
