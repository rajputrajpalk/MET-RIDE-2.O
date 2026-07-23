"""
socket_handlers.py — MET Ride 2 Socket.IO Event Handlers
All real-time socket events are registered here and imported in app.py.
"""
from datetime import datetime, timezone

from flask import session, request as flask_request
from flask_socketio import join_room, emit
from bson import ObjectId

from extensions import socketio, rides_col, users_col

# ── In-memory store for last known rider location (ride_id → {lat, lng, ts}) ──
# This avoids a DB read on every poll request.
_rider_locations: dict = {}


def get_last_location(ride_id: str):
    """Returns (lat, lng, updated_at) or None."""
    return _rider_locations.get(ride_id)


def register_handlers(app):
    """Called once from app.py after socketio.init_app(app)."""

    # ─────────────────────────────────────────────────────────────────────────
    # Connection lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    @socketio.on("connect")
    def handle_connect():
        user_id = session.get("user_id")
        if user_id:
            join_room(user_id)
            try:
                users_col.update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": {
                        "last_seen": datetime.now(timezone.utc),
                        "is_online": True,
                    }},
                )
            except Exception:
                pass

    @socketio.on("disconnect")
    def handle_disconnect():
        user_id = session.get("user_id")
        if user_id:
            try:
                users_col.update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": {
                        "is_online": False,
                        "last_seen": datetime.now(timezone.utc),
                    }},
                )
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # Room joins
    # ─────────────────────────────────────────────────────────────────────────

    @socketio.on("join_user_room")
    def handle_join_user_room(data):
        user_id = data.get("user_id")
        if user_id:
            join_room(f"user_{user_id}")

    @socketio.on("join_admin_room")
    def handle_join_admin_room():
        join_room("admins")

    @socketio.on("join_ride")
    def handle_join_ride(data):
        ride_id = data.get("ride_id")
        if ride_id:
            join_room(ride_id)
            emit("system_message", {"text": "You joined the ride chat."}, to=flask_request.sid)

    @socketio.on("join_ride_room")
    def handle_join_ride_room(data):
        """Join the dedicated tracking room for OTP + live location events."""
        ride_id = data.get("ride_id")
        if ride_id:
            room = f"ride_{ride_id}"
            join_room(room)
            emit(
                "system_message",
                {"text": f"Joined live tracking room for ride {ride_id[-6:]}."},
                to=flask_request.sid,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Chat
    # ─────────────────────────────────────────────────────────────────────────

    @socketio.on("send_message")
    def handle_send_message(data):
        ride_id  = data.get("ride_id")
        message  = (data.get("message") or "").strip()
        username = data.get("username", "Anonymous")
        if ride_id and message:
            emit("receive_message", {
                "username":  username,
                "message":   message,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }, to=ride_id)

    @socketio.on("user_typing")
    def handle_user_typing(data):
        ride_id  = data.get("ride_id")
        username = data.get("username", "Someone")
        if ride_id:
            emit("user_typing", {"username": username}, to=ride_id, include_self=False)

    # ─────────────────────────────────────────────────────────────────────────
    # Location sharing
    # ─────────────────────────────────────────────────────────────────────────

    @socketio.on("update_location")
    def handle_update_location_legacy(data):
        """Legacy event kept for backward compatibility with existing frontend code."""
        ride_id = data.get("ride_id")
        lat     = data.get("lat")
        lng     = data.get("lng")
        if not (ride_id and lat is not None and lng is not None):
            return
        try:
            rides_col.update_one(
                {"_id": ObjectId(ride_id)},
                {"$set": {"current_location": {"type": "Point", "coordinates": [lng, lat]}}},
            )
        except Exception:
            pass
        emit("location_updated", {"ride_id": ride_id, "lat": lat, "lng": lng}, to=ride_id)

    @socketio.on("location_update")
    def handle_location_update(data):
        """Primary OTP-gated GPS stream — driver emits every 5 s after OTP verified."""
        ride_id = data.get("ride_id")
        lat     = data.get("lat")
        lng     = data.get("lng")
        if not (ride_id and lat is not None and lng is not None):
            return

        # Security: only relay location when OTP is verified
        try:
            ride = rides_col.find_one(
                {"_id": ObjectId(ride_id)},
                {"otp_verified": 1, "rider_id": 1},
            )
        except Exception:
            return

        if not ride or not ride.get("otp_verified"):
            return  # silently drop unverified updates

        # Persist to DB
        try:
            rides_col.update_one(
                {"_id": ObjectId(ride_id)},
                {"$set": {"current_location": {"type": "Point", "coordinates": [lng, lat]}}},
            )
        except Exception:
            pass

        # Cache in memory for fast polling
        _rider_locations[ride_id] = {
            "lat": lat,
            "lng": lng,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        # Broadcast to ride room (passengers + driver)
        emit(
            "driver_location",
            {"ride_id": ride_id, "lat": lat, "lng": lng},
            to=f"ride_{ride_id}",
            include_self=False,
        )

    @socketio.on("send_location")
    def handle_send_location(data):
        """Legacy snapshot-based location, kept for compatibility."""
        ride_id = data.get("ride_id")
        lat     = data.get("lat")
        lng     = data.get("lng")
        if ride_id and lat is not None and lng is not None:
            try:
                rides_col.update_one(
                    {"_id": ObjectId(ride_id)},
                    {"$push": {"route_snapshot": {
                        "lat": lat, "lng": lng,
                        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }}},
                )
            except Exception:
                pass
            emit("receive_location", {"lat": lat, "lng": lng, "ride_id": ride_id}, to=ride_id)

    @socketio.on("request_pickup")
    def handle_request_pickup(data):
        ride_id   = data.get("ride_id")
        lat       = data.get("lat")
        lng       = data.get("lng")
        user_name = data.get("user_name", "Passenger")
        if ride_id:
            emit(
                "passenger_confirmed",
                {"user_name": user_name, "lat": lat, "lng": lng, "ride_id": ride_id},
                to=ride_id,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Ride lifecycle signals
    # ─────────────────────────────────────────────────────────────────────────

    @socketio.on("ride_completed_signal")
    def handle_ride_completed(data):
        ride_id = data.get("ride_id")
        if ride_id:
            # Clean up in-memory location cache
            _rider_locations.pop(ride_id, None)
            emit("ride_completed", {"ride_id": ride_id}, to=ride_id)

    @socketio.on("ride_accepted_ack")
    def handle_ride_accepted_ack(data):
        ride_id = data.get("ride_id")
        if ride_id:
            join_room(ride_id)
