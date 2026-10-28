import os
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status, Header, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Initialize FastAPI
app = FastAPI(
    title="Hotel Mahesh API",
    description="Production backend for Hotel Mahesh (Sasaram, Bihar)",
    version="2.0.0"
)

# -------------------------------------------------------------
# 1. CORS CONFIGURATION (Enables seamless GitHub Pages requests)
# -------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permits requests from GitHub Pages & custom domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------
# 2. ENVIRONMENT SECRETS & SUPABASE SETUP
# -------------------------------------------------------------
ADMIN_USERNAME = os.getenv("HOTEL_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("HOTEL_ADMIN_PASS", "mahesh@123")
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "hotel-mahesh-sasaram-secure-key-2026")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", os.getenv("SUPABASE_KEY", ""))

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client, Client
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Warning: Supabase client initialization error: {e}")

# In-Memory Backup Datastore (Ensures zero downtime if Supabase is initializing)
IN_MEMORY_CONFIG = {
    "upi_id": "hotelmahesh@upi",
    "d2": 20,
    "d3": 25,
    "d4plus": 30,
    "event_full": 1000,
    "event_six": 400
}

IN_MEMORY_ROOMS: List[Dict[str, Any]] = [
    {
        "id": "deluxe_ac",
        "name": "Executive AC Deluxe Room",
        "price": 2200,
        "sleeps": "Sleeps 2 Guests · 1 King Bed",
        "description": "Air-conditioned premium suite featuring smart TV, ambient panel lighting, and marble en-suite bathroom.",
        "image_url": "https://images.unsplash.com/photo-1611892440504-42a792e24d32?auto=format&fit=crop&w=800&q=80",
        "h1": 600, "h2": 1000, "h3": 1300, "hday": 1500
    },
    {
        "id": "family_suite",
        "name": "Presidential Family Suite",
        "price": 3500,
        "sleeps": "Sleeps 4 to 5 Guests · 2 Queen Beds",
        "description": "Spacious dual double-bed family accommodation with high ceilings, full cooling, and luggage wardrobe.",
        "image_url": "https://images.unsplash.com/photo-1590490360182-c33d57733427?auto=format&fit=crop&w=800&q=80",
        "h1": 1000, "h2": 1800, "h3": 2400, "hday": 3000
    },
    {
        "id": "standard_nonac",
        "name": "Classic Comfort Room",
        "price": 1400,
        "sleeps": "Sleeps 2 Guests · 1 Double Bed",
        "description": "Clean, budget-conscious transit room with ceiling fan, writing table, and hot water shower.",
        "image_url": "https://images.unsplash.com/photo-1566665797739-1674de7a421a?auto=format&fit=crop&w=800&q=80",
        "h1": 400, "h2": 700, "h3": 900, "hday": 1200
    }
]

IN_MEMORY_GALLERY: List[Dict[str, Any]] = [
    {"id": "g1", "album": "rooms", "title": "Deluxe Suite Bed", "url": "https://images.unsplash.com/photo-1611892440504-42a792e24d32?auto=format&fit=crop&w=800&q=80"},
    {"id": "g2", "album": "rooms", "title": "Family Room Interior", "url": "https://images.unsplash.com/photo-1590490360182-c33d57733427?auto=format&fit=crop&w=800&q=80"},
    {"id": "g3", "album": "banquets", "title": "Grand Wedding Mandap", "url": "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?auto=format&fit=crop&w=800&q=80"},
    {"id": "g4", "album": "banquets", "title": "Reception Dining Hall", "url": "https://images.unsplash.com/photo-1511795409834-ef04bbd61622?auto=format&fit=crop&w=800&q=80"},
    {"id": "g5", "album": "premises", "title": "Hotel Reception & Desk", "url": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=800&q=80"},
    {"id": "g6", "album": "premises", "title": "Exterior Ambience", "url": "https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?auto=format&fit=crop&w=800&q=80"}
]

IN_MEMORY_BOOKINGS: List[Dict[str, Any]] = []

# -------------------------------------------------------------
# 3. SECURITY & CRYPTOGRAPHIC TOKEN DEPENDENCY
# -------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str

class ConfigModel(BaseModel):
    upi_id: str
    d2: int
    d3: int
    d4plus: int
    event_full: int
    event_six: int

class RoomModel(BaseModel):
    name: str
    price: int
    sleeps: str
    description: str
    image_url: str
    h1: int
    h2: int
    h3: int
    hday: int

class GalleryModel(BaseModel):
    id: str
    title: str
    album: str
    url: str

def generate_token(username: str) -> str:
    expiry = (datetime.utcnow() + timedelta(hours=24)).strftime("%Y%m%d%H")
    sig = hashlib.sha256(f"{username}:{expiry}:{AUTH_SECRET_KEY}".encode("utf-8")).hexdigest()
    return f"{username}.{expiry}.{sig}"

def require_admin(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header."
        )
    token = authorization.split(" ")[1]
    try:
        user, expiry, sig = token.split(".")
        expected_sig = hashlib.sha256(f"{user}:{expiry}:{AUTH_SECRET_KEY}".encode("utf-8")).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError("Signature mismatch")
        if datetime.utcnow().strftime("%Y%m%d%H") > expiry:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
        return user
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token.")

# -------------------------------------------------------------
# 4. AUTHENTICATION ROUTE
# -------------------------------------------------------------
@app.post("/api/auth/login")
def login(creds: LoginRequest):
    user_ok = hmac.compare_digest(creds.username.strip().encode("utf-8"), ADMIN_USERNAME.strip().encode("utf-8"))
    pass_ok = hmac.compare_digest(creds.password.strip().encode("utf-8"), ADMIN_PASSWORD.strip().encode("utf-8"))
    
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")
    
    token = generate_token(creds.username.strip())
    return {"token": token, "status": "authenticated"}

# -------------------------------------------------------------
# 5. CONFIGURATION ENDPOINTS
# -------------------------------------------------------------
@app.get("/api/config")
def get_config():
    if supabase:
        try:
            res = supabase.table("config").select("*").eq("id", "global").execute()
            if res.data:
                return res.data[0]
        except Exception as e:
            print("Supabase config query error:", e)
    return IN_MEMORY_CONFIG

@app.post("/api/config")
def update_config(payload: ConfigModel, user: str = Depends(require_admin)):
    global IN_MEMORY_CONFIG
    data = payload.dict()
    IN_MEMORY_CONFIG = data
    if supabase:
        try:
            supabase.table("config").upsert({"id": "global", **data}).execute()
        except Exception as e:
            print("Supabase config upsert error:", e)
    return {"status": "success", "config": data}

# -------------------------------------------------------------
# 6. ROOMS ENDPOINTS
# -------------------------------------------------------------
@app.get("/api/rooms")
def get_rooms():
    if supabase:
        try:
            res = supabase.table("rooms").select("*").execute()
            if res.data and len(res.data) > 0:
                return res.data
        except Exception as e:
            print("Supabase rooms query error:", e)
    return IN_MEMORY_ROOMS

@app.post("/api/rooms/{room_id}")
def save_room(room_id: str, payload: RoomModel, user: str = Depends(require_admin)):
    room_dict = payload.dict()
    room_dict["id"] = room_id
    
    # Update in-memory
    idx = next((i for i, r in enumerate(IN_MEMORY_ROOMS) if r["id"] == room_id), None)
    if idx is not None:
        IN_MEMORY_ROOMS[idx] = room_dict
    else:
        IN_MEMORY_ROOMS.append(room_dict)
        
    if supabase:
        try:
            supabase.table("rooms").upsert(room_dict).execute()
        except Exception as e:
            print("Supabase room upsert error:", e)
    return {"status": "success", "room": room_dict}

# -------------------------------------------------------------
# 7. GALLERY ENDPOINTS
# -------------------------------------------------------------
@app.get("/api/gallery")
def get_gallery():
    if supabase:
        try:
            res = supabase.table("gallery").select("*").execute()
            if res.data and len(res.data) > 0:
                return res.data
        except Exception as e:
            print("Supabase gallery query error:", e)
    return IN_MEMORY_GALLERY

@app.post("/api/gallery")
def add_gallery_photo(photo: GalleryModel, user: str = Depends(require_admin)):
    photo_dict = photo.dict()
    IN_MEMORY_GALLERY.append(photo_dict)
    if supabase:
        try:
            supabase.table("gallery").insert(photo_dict).execute()
        except Exception as e:
            print("Supabase gallery insert error:", e)
    return {"status": "success", "photo": photo_dict}

@app.delete("/api/gallery/{photo_id}")
def delete_gallery_photo(photo_id: str, user: str = Depends(require_admin)):
    global IN_MEMORY_GALLERY
    IN_MEMORY_GALLERY = [p for p in IN_MEMORY_GALLERY if p["id"] != photo_id]
    if supabase:
        try:
            supabase.table("gallery").delete().eq("id", photo_id).execute()
        except Exception as e:
            print("Supabase gallery delete error:", e)
    return {"status": "deleted", "id": photo_id}

# -------------------------------------------------------------
# 8. BOOKINGS ENDPOINTS (Reservation Engine)
# -------------------------------------------------------------
@app.get("/api/bookings")
def get_bookings(user: str = Depends(require_admin)):
    if supabase:
        try:
            res = supabase.table("bookings").select("*").order("created_at", desc=True).execute()
            if res.data:
                return res.data
        except Exception as e:
            print("Supabase bookings query error:", e)
    return IN_MEMORY_BOOKINGS

@app.post("/api/bookings")
def create_booking(
    name: str = Form(...),
    phone: str = Form(...),
    room_id: str = Form(...),
    booking_type: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    hours: int = Form(0),
    guests: int = Form(2),
    id_proof: str = Form(...)
):
    # Lookup room
    room = next((r for r in IN_MEMORY_ROOMS if r["id"] == room_id), IN_MEMORY_ROOMS[0])
    
    # Calculate price
    discount_pct = 0
    total = 0
    if booking_type == "night":
        try:
            d1 = datetime.strptime(start_date, "%Y-%m-%d")
            d2 = datetime.strptime(end_date, "%Y-%m-%d")
            nights = max(1, (d2 - d1).days)
        except Exception:
            nights = 1
        base_total = nights * room["price"]
        if nights == 2:
            discount_pct = IN_MEMORY_CONFIG["d2"]
        elif nights == 3:
            discount_pct = IN_MEMORY_CONFIG["d3"]
        elif nights >= 4:
            discount_pct = IN_MEMORY_CONFIG["d4plus"]
        total = round(base_total * (1 - (discount_pct / 100)))
    else:
        if hours == 1:
            total = room["h1"]
        elif hours == 2:
            total = room["h2"]
        elif hours == 3:
            total = room["h3"]
        else:
            total = room["hday"]

    booking_id = f"HM{int(datetime.utcnow().timestamp())}"
    record = {
        "id": booking_id,
        "guest_name": name,
        "phone": phone,
        "room_id": room_id,
        "room_name": room["name"],
        "booking_type": booking_type,
        "start_date": start_date,
        "end_date": end_date,
        "hours": hours,
        "guests": guests,
        "total": total,
        "discount_pct": discount_pct,
        "document_url": id_proof,
        "status": "Pending",
        "room_number": "",
        "check_in_time": "",
        "created_at": datetime.utcnow().isoformat()
    }
    
    IN_MEMORY_BOOKINGS.insert(0, record)
    if supabase:
        try:
            supabase.table("bookings").insert(record).execute()
        except Exception as e:
            print("Supabase booking insert error:", e)

    return {
        "status": "created",
        "booking_id": booking_id,
        "total": total,
        "discount_applied": discount_pct
    }

@app.patch("/api/bookings/{booking_id}/status")
def update_booking_status(
    booking_id: str,
    new_status: str,
    room_number: Optional[str] = None,
    check_in_time: Optional[str] = None,
    user: str = Depends(require_admin)
):
    update_data = {"status": new_status}
    if room_number:
        update_data["room_number"] = room_number
    if check_in_time:
        update_data["check_in_time"] = check_in_time

    # Update in-memory
    for b in IN_MEMORY_BOOKINGS:
        if str(b["id"]) == str(booking_id):
            b.update(update_data)
            break

    if supabase:
        try:
            supabase.table("bookings").update(update_data).eq("id", booking_id).execute()
        except Exception as e:
            print("Supabase booking update error:", e)

    return {"status": "updated", "booking_id": booking_id, "data": update_data}

@app.get("/")
def health_check():
    return {"hotel": "Hotel Mahesh", "status": "online", "version": "2.0.0"}