import os
from pymongo import MongoClient, ASCENDING, DESCENDING, GEOSPHERE
from dotenv import load_dotenv

# Load environment variables (fallback to localhost if not set in .env)
load_dotenv()

# Database Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = "MET_RIDE_2"

def connect_db():
    """
    Connects to the MongoDB instance and returns the database object.
    Uses MONGO_URI from environment variables or defaults to localhost.
    """
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Test connection
        client.admin.command('ping')
        db = client[DB_NAME]
        return db
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return None

def init_indexes(db):
    """
    Creates necessary collections and indexes for optimize querying.
    Collections are defined via their schemas documented below.
    """
    print("⏳ Initializing database collections and indexes...")

    # 1. USERS COLLECTION
    # Schema:
    # {
    #   "_id": ObjectId,
    #   "email": String (Unique, Indexed),
    #   "password_hash": String,
    #   "name": String,
    #   "phone": String,
    #   "role": String (Enum: "driver", "passenger", "admin"),
    #   "verification_status": String (Enum: "pending", "approved", "rejected"),
    #   "id_card_path": String (URL/Path to uploaded ID),
    #   "created_at": ISODate
    # }
    db.users.create_index([("email", ASCENDING)], unique=True)
    print("  - 'users' indexes created.")

    # 2. RIDES COLLECTION
    # Schema:
    # {
    #   "_id": ObjectId,
    #   "driver_id": ObjectId (Ref: users),
    #   "route": { 
    #       "type": "LineString" or "Point", 
    #       "coordinates": [[lng1, lat1], [lng2, lat2]] 
    #   },
    #   "start_location_name": String,
    #   "end_location_name": String,
    #   "departure_time": ISODate,
    #   "seats_available": Integer,
    #   "status": String (Enum: "scheduled", "active", "completed", "cancelled"),
    #   "created_at": ISODate
    # }
    # 2dsphere index for geospatial searches on the route/starting point
    db.rides.create_index([("route", GEOSPHERE)])
    # Index for fast filtering by status
    db.rides.create_index([("status", ASCENDING)])
    db.rides.create_index([("driver_id", ASCENDING)])
    print("  - 'rides' geospatial and status indexes created.")

    # 3. REQUESTS COLLECTION
    # Schema:
    # {
    #   "_id": ObjectId,
    #   "ride_id": ObjectId (Ref: rides),
    #   "passenger_id": ObjectId (Ref: users),
    #   "status": String (Enum: "pending", "approved", "rejected"),
    #   "requested_seats": Integer,
    #   "created_at": ISODate
    # }
    db.requests.create_index([("ride_id", ASCENDING), ("passenger_id", ASCENDING)], unique=True)
    print("  - 'requests' indexes created.")

    # 4. MESSAGES COLLECTION
    # Schema:
    # {
    #   "_id": ObjectId,
    #   "room_id": ObjectId (Ref: rides - unique chat per ride),
    #   "sender_id": ObjectId (Ref: users),
    #   "content": String,
    #   "timestamp": ISODate
    # }
    db.messages.create_index([("room_id", ASCENDING), ("timestamp", ASCENDING)])
    print("  - 'messages' indexes created.")

    # 5. NOTIFICATIONS COLLECTION
    # Schema:
    # {
    #   "_id": ObjectId,
    #   "user_id": ObjectId (Ref: users),
    #   "type": String (Enum: "booking", "approval", "cancellation", "system"),
    #   "content": String,
    #   "is_read": Boolean,
    #   "timestamp": ISODate
    # }
    # TTL Index: Auto-delete notifications older than 30 days (2592000 seconds)
    db.notifications.create_index([("timestamp", ASCENDING)], expireAfterSeconds=2592000)
    db.notifications.create_index([("user_id", ASCENDING), ("is_read", ASCENDING)])
    print("  - 'notifications' TTL and user indexes created.")

    # 6. SOS_ALERTS COLLECTION
    # Schema:
    # {
    #   "_id": ObjectId,
    #   "user_id": ObjectId (Ref: users),
    #   "ride_id": ObjectId (Ref: rides, optional),
    #   "location": { "type": "Point", "coordinates": [lng, lat] },
    #   "status": String (Enum: "active", "resolved"),
    #   "resolved_by": ObjectId (Ref: users),
    #   "timestamp": ISODate,
    #   "resolution_time": ISODate
    # }
    db.sos_alerts.create_index([("status", ASCENDING)])
    db.sos_alerts.create_index([("location", GEOSPHERE)])
    print("  - 'sos_alerts' geospatial and status indexes created.")

    # 7. RATINGS COLLECTION
    # Schema:
    # {
    #   "_id": ObjectId,
    #   "ride_id": ObjectId (Ref: rides),
    #   "reviewer_id": ObjectId (Ref: users),
    #   "reviewee_id": ObjectId (Ref: users),
    #   "score": Integer (1-5),
    #   "review": String,
    #   "timestamp": ISODate
    # }
    db.ratings.create_index([("reviewee_id", ASCENDING)])
    db.ratings.create_index([("ride_id", ASCENDING), ("reviewer_id", ASCENDING)], unique=True)
    print("  - 'ratings' indexes created.")

    print("✅ All collections and indexes initialized successfully.")

if __name__ == "__main__":
    print("🚀 Initializing MET RIDE 2 Database Configuration...")
    db_instance = connect_db()
    if db_instance is not None:
        init_indexes(db_instance)
        print("\n✅ MET RIDE 2 Database Connected Successfully")
    else:
        print("\n❌ Failed to connect to MET RIDE 2 Database. Ensure MongoDB Compass is running on localhost:27017 or check MONGO_URI in .env")
