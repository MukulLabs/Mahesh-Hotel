import os
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, status, Depends, Header, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Brute-force protection libraries
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Supabase Client Import
try:
    from supabase import create_client, Client
except ImportError:
    create_client = None
    Client = Any

# ==========================================
# 1. INITIALIZATION & SECURITY SETUP
# ==========================================
limiter = Limiter(key_func=get_remote_address)

# Disabled auto-generated docs in production to prevent schema scraping
app = FastAPI(
    title="Hotel Mahesh API",
    version="2.3.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Strict CORS: only allow authorized frontend domains
ALLOWED_ORIGINS = [
    "https://mukullabs.github.io",
    "https://hotelmahesh.com",
    "https://www.hotelmahesh.com",
    "https://hotelmahesh.in",
    "https://www.hotelmahesh.in",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ==========================================
# 2. CREDENTIALS & SUPABASE INITIALIZATION
# ==========================================
ADMIN_USERNAME = os.getenv("HOTEL_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("HOTEL_ADMIN_PASS", "mahesh@123")
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "hotel-mahesh-sasaram-secure-key-2026")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase_client: Optional[Client] = None
if create_client and SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Connected to Supabase successfully.")
    except Exception as e:
        print(f"Warning: Failed to connect to Supabase: {e}")

# In-Memory Default State (fallback buffer)
state_config = {
    "id": "global_config",
    "upi_id": "hotelmahesh@upi",
    "d2": 20,
    "d3": 25,
    "d4plus": 30,
    "event_full": 1000,
    "event_six": 400
}

state_rooms = [
    {
        "id": "deluxe_ac",
        "name": "Executive AC Deluxe Room",
        "price": 2200,
        "sleeps": "Sleeps 2 Guests · 1 King Bed",
        "description": "Air-conditioned premium suite featuring smart TV, ambient panel lighting, and marble en-suite bathroom.",
        "image_url": "https://i.ibb.co/bMSbr9QM/Whats-App-Image-2026-10-27-at-19-21-40-3.jpg",
        "h1": 600, "h2": 1000, "h3": 1300, "hday": 1500
    },
    {
        "id": "family_suite",
        "name": "Presidential Family Suite",
        "price": 3500,
        "sleeps": "Sleeps 4 to 5 Guests · 2 Queen Beds",
        "description": "Spacious dual double-bed family accommodation with high ceilings, full cooling, and luggage wardrobe.",
        "image_url": "https://i.ibb.co/gb3bvk0M/Whats-App-Image-2026-10-27-at-19-21-40-1.jpg",
        "h1": 1000, "h2": 1800, "h3": 2400, "hday": 3000
    },
    {
        "id": "standard_nonac",
        "name": "Classic Comfort Room",
        "price": 1400,
        "sleeps": "Sleeps 2 Guests · 1 Double Bed",
        "description": "Clean, budget-conscious transit room with ceiling fan, writing table, and hot water shower.",
        "image_url": "https://i.ibb.co/fdzW1t3j/Whats-App-Image-2026-10-27-at-19-21-40.jpg",
        "h1": 400, "h2": 700, "h3": 900, "hday": 1200
    }
]

state_gallery = [
    {"id": "g_1", "album": "rooms", "title": "Executive Room Interior", "url": "https://i.ibb.co/bMSbr9QM/Whats-App-Image-2026-10-27-at-19-21-40-3.jpg"},
    {"id": "g_2", "album": "rooms", "title": "Deluxe AC Room Bedding", "url": "https://i.ibb.co/tpbTddBH/Whats-App-Image-2026-10-27-at-19-21-40-2.jpg"},
    {"id": "g_3", "album": "rooms", "title": "Family Suite Luxury Setup", "url": "https://i.ibb.co/gb3bvk0M/Whats-App-Image-2026-10-27-at-19-21-40-1.jpg"},
    {"id": "g_4", "album": "rooms", "title": "Standard Room Bedding", "url": "https://i.ibb.co/fdzW1t3j/Whats-App-Image-2026-10-27-at-19-21-40.jpg"},
    {"id": "g_5", "album": "premises", "title": "Corridor & Reception Desk", "url": "https://i.ibb.co/kgsSKf4n/Whats-App-Image-2026-10-27-at-19-21-39-2.jpg"},
    {"id": "g_6", "album": "premises", "title": "Main Building Entrance", "url": "https://i.ibb.co/MDZv48NY/Whats-App-Image-2026-10-27-at-19-21-39-1.jpg"},
    {"id": "g_7", "album": "banquets", "title": "Banquet Hall Stage Area", "url": "https://i.ibb.co/wZwzHKgD/Whats-App-Image-2026-10-27-at-19-21-39.jpg"},
    {"id": "g_8", "album": "banquets", "title": "Event Dining Arrangement", "url": "https://i.ibb.co/YF1tbmc4/Whats-App-Image-2026-10-27-at-19-21-38-2.jpg"},
    {"id": "g_9", "album": "premises", "title": "Hotel Mahesh Exterior Facade", "url": "https://i.ibb.co/bRFQsxcz/Whats-App-Image-2026-10-27-at-19-21-38-1.jpg"},
    {"id": "g_10", "album": "premises", "title": "Evening Property Lighting", "url": "https://i.ibb.co/sdZZrnSR/Whats-App-Image-2026-10-27-at-19-21-38.jpg"}
]

state_bookings: List[Dict[str, Any]] = []

# ==========================================
# 3. HELPER & SECURITY FUNCTIONS
# ==========================================
def generate_token(username: str) -> str:
    expiry = (datetime.utcnow() + timedelta(days=2)).strftime("%Y%m%d%H%M")
    raw = f"{username}:{expiry}:{AUTH_SECRET_KEY}".encode("utf-8")
    sig = hashlib.sha256(raw).hexdigest()
    return f"{username}.{expiry}.{sig}"

def verify_admin_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed authorization header."
        )
    token = authorization.split(" ")[1]
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError
        user, expiry, sig = parts
        expected_raw = f"{user}:{expiry}:{AUTH_SECRET_KEY}".encode("utf-8")
        expected_sig = hashlib.sha256(expected_raw).hexdigest()
        
        if not hmac.compare_digest(sig, expected_sig):
            raise HTTPException(status_code=401, detail="Invalid token signature.")
        if datetime.utcnow().strftime("%Y%m%d%H%M") > expiry:
            raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
        return user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")

def sanitize_id_proof(raw_proof: str) -> str:
    """Masks Government ID numbers to comply with DPDP privacy guidelines."""
    if not raw_proof:
        return "Not Provided"
    parts = raw_proof.split(":")
    if len(parts) > 1:
        doc_type = parts[0].strip()
        val = parts[1].strip()
        last4 = val[-4:] if len(val) >= 4 else val
        return f"{doc_type}: Ending in {last4}"
    
    val = raw_proof.strip()
    last4 = val[-4:] if len(val) >= 4 else val
    return f"ID Ending in {last4}"

# ==========================================
# 4. REQUEST SCHEMAS
# ==========================================
class LoginRequest(BaseModel):
    username: str
    password: str

class ConfigPayload(BaseModel):
    upi_id: str
    d2: int
    d3: int
    d4plus: int
    event_full: int
    event_six: int

class RoomRatesPayload(BaseModel):
    name: str
    price: int
    sleeps: str
    description: str
    h1: int
    h2: int
    h3: int
    hday: int

# ==========================================
# 5. API ENDPOINTS
# ==========================================
from fastapi.responses import PlainTextResponse

# Minimal 2-character response: consumes 2 bytes, never exceeds size limits
@app.get("/api/health", response_class=PlainTextResponse)
@app.head("/api/health")
def health():
    return "ok"

# Rate-limited login (Max 5 attempts per minute)
@app.post("/api/auth/login")
@limiter.limit("5/minute")
def login(request: Request, payload: LoginRequest):
    user_ok = hmac.compare_digest(payload.username.encode("utf-8"), ADMIN_USERNAME.encode("utf-8"))
    pass_ok = hmac.compare_digest(payload.password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8"))
    
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")
    
    token = generate_token(payload.username)
    return {"token": token, "status": "authenticated"}

# --- CONFIG (Supabase Database Persisted) ---
@app.get("/api/config")
def get_config():
    if supabase_client:
        try:
            res = supabase_client.table("hotel_config").select("*").eq("id", "global_config").execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
        except Exception as e:
            print(f"Supabase config read error: {e}")
    return state_config

@app.post("/api/config")
def save_config(payload: ConfigPayload, user: str = Depends(verify_admin_token)):
    global state_config
    data = payload.dict()
    data["id"] = "global_config"
    state_config = data
    if supabase_client:
        try:
            supabase_client.table("hotel_config").upsert(data).execute()
        except Exception as e:
            print(f"Supabase config save error: {e}")
    return {"status": "success", "config": state_config}

# --- ROOMS (Supabase Database Persisted) ---
@app.get("/api/rooms")
def get_rooms():
    if supabase_client:
        try:
            res = supabase_client.table("rooms").select("*").execute()
            if res.data and len(res.data) > 0:
                return res.data
        except Exception as e:
            print(f"Supabase rooms read error: {e}")
    return state_rooms

@app.post("/api/rooms/{room_id}")
def update_room_specifications(room_id: str, payload: RoomRatesPayload, user: str = Depends(verify_admin_token)):
    """Allows staff to edit rates, names, and descriptions while keeping the image managed in the database."""
    existing_img = "https://images.unsplash.com/photo-1566665797739-1674de7a421a?auto=format&fit=crop&w=800&q=80"
    
    # Preserve existing database image URL
    if supabase_client:
        try:
            res = supabase_client.table("rooms").select("image_url").eq("id", room_id).execute()
            if res.data and len(res.data) > 0:
                existing_img = res.data[0].get("image_url", existing_img)
        except Exception as e:
            print(f"Supabase check image error: {e}")
    else:
        for r in state_rooms:
            if r["id"] == room_id:
                existing_img = r.get("image_url", existing_img)
                break

    data = payload.dict()
    data["id"] = room_id
    data["image_url"] = existing_img

    # Update memory
    found = False
    for idx, r in enumerate(state_rooms):
        if r["id"] == room_id:
            state_rooms[idx] = data
            found = True
            break
    if not found:
        state_rooms.append(data)

    # Persist to Supabase
    if supabase_client:
        try:
            supabase_client.table("rooms").upsert(data).execute()
        except Exception as e:
            print(f"Supabase room save error: {e}")

    return {"status": "saved", "room": data}

# --- GALLERY (Read-Only from Database API) ---
@app.get("/api/gallery")
def get_gallery():
    """Returns photos stored in the Supabase 'gallery' table."""
    if supabase_client:
        try:
            res = supabase_client.table("gallery").select("*").order("created_at", desc=False).execute()
            if res.data and len(res.data) > 0:
                return res.data
        except Exception as e:
            print(f"Supabase gallery read error: {e}")
    return state_gallery

# --- BOOKINGS (Supabase Database Persisted) ---
@app.get("/api/bookings")
def get_bookings(user: str = Depends(verify_admin_token)):
    if supabase_client:
        try:
            res = supabase_client.table("bookings").select("*").order("created_at", desc=True).execute()
            return res.data
        except Exception as e:
            print(f"Supabase read error: {e}")
    return state_bookings

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
    room = next((r for r in state_rooms if r["id"] == room_id), state_rooms[0])
    total = 0
    discount_pct = 0

    if booking_type == "hour":
        if hours == 1:
            total = room.get("h1", 600)
        elif hours == 2:
            total = room.get("h2", 1000)
        elif hours == 3:
            total = room.get("h3", 1300)
        else:
            total = room.get("hday", 1500)
    else:
        try:
            d_start = datetime.strptime(start_date, "%Y-%m-%d")
            d_end = datetime.strptime(end_date, "%Y-%m-%d")
            nights = max(1, (d_end - d_start).days)
        except Exception:
            nights = 1
            
        base = nights * room.get("price", 2200)
        if nights == 2:
            discount_pct = state_config.get("d2", 20)
        elif nights == 3:
            discount_pct = state_config.get("d3", 25)
        elif nights >= 4:
            discount_pct = state_config.get("d4plus", 30)
        total = round(base * (1 - (discount_pct / 100)))

    booking_id = f"HM{int(datetime.utcnow().timestamp())}"
    safe_document_ref = sanitize_id_proof(id_proof)

    new_booking = {
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
        "document_url": safe_document_ref,
        "total": total,
        "discount_pct": discount_pct,
        "status": "Pending",
        "room_number": None,
        "check_in_time": None,
        "created_at": datetime.utcnow().isoformat()
    }
    
    if supabase_client:
        try:
            supabase_client.table("bookings").insert(new_booking).execute()
        except Exception as e:
            print(f"Supabase insert error: {e}")
            state_bookings.insert(0, new_booking)
    else:
        state_bookings.insert(0, new_booking)

    return {"booking_id": booking_id, "total": total, "discount_applied": discount_pct}

@app.patch("/api/bookings/{booking_id}/status")
def update_booking_status(
    booking_id: str,
    new_status: str,
    room_number: Optional[str] = None,
    check_in_time: Optional[str] = None,
    user: str = Depends(verify_admin_token)
):
    update_data = {"status": new_status}
    if room_number:
        update_data["room_number"] = room_number
    if check_in_time:
        update_data["check_in_time"] = check_in_time

    if supabase_client:
        try:
            res = supabase_client.table("bookings").update(update_data).eq("id", booking_id).execute()
            if res.data:
                return {"status": "success", "booking": res.data[0]}
        except Exception as e:
            print(f"Supabase update error: {e}")

    for b in state_bookings:
        if str(b["id"]) == str(booking_id):
            b.update(update_data)
            return {"status": "success", "booking": b}
            
    raise HTTPException(status_code=404, detail="Booking record not found.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
