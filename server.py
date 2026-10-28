import os
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, status, Header, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="Hotel Mahesh API", version="2.5.0", docs_url=None, redoc_url=None, openapi_url=None)

# 1. CORS CONFIGURATION
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://mukullabs.github.io",
        "https://hotelmahesh.in",
        "https://www.hotelmahesh.in"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# 2. ENVIRONMENT VARIABLES
ADMIN_USERNAME = os.getenv("HOTEL_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("HOTEL_ADMIN_PASS", "mahesh@123")
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "hotel-mahesh-sasaram-secure-key-2026")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# 3. SUPABASE CLIENT INITIALIZATION
supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Connected to Supabase PostgreSQL Database successfully.")
    except Exception as e:
        print(f"Supabase connection warning: {e}")

# In-memory fallbacks if Supabase env keys are temporarily missing
state_config = {
    "upi_id": "hotelmahesh@upi",
    "d2": 20,
    "d3": 25,
    "d4plus": 30,
    "event_full": 1000,
    "event_six": 400
}
state_rooms: List[Dict[str, Any]] = []
state_gallery: List[Dict[str, Any]] = []
state_bookings: List[Dict[str, Any]] = []

# 4. TOKEN CRYPTOGRAPHY
def generate_token(username: str) -> str:
    expiry = (datetime.utcnow() + timedelta(days=2)).strftime("%Y%m%d%H%M")
    raw = f"{username}:{expiry}:{AUTH_SECRET_KEY}".encode("utf-8")
    sig = hashlib.sha256(raw).hexdigest()
    return f"{username}.{expiry}.{sig}"

def verify_admin_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization token.")
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

# 5. DATA MODELS
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

class RoomPayload(BaseModel):
    name: str
    price: int
    sleeps: str
    description: str
    image_url: str
    h1: int
    h2: int
    h3: int
    hday: int

class GalleryPayload(BaseModel):
    id: str
    album: str
    title: str
    url: str

# 6. API ENDPOINTS
@app.get("/api/health")
def health():
    return {"status": "ok", "database": "connected" if supabase else "fallback", "time": datetime.utcnow().isoformat()}

@app.post("/api/auth/login")
def login(payload: LoginRequest):
    user_ok = hmac.compare_digest(payload.username.encode("utf-8"), ADMIN_USERNAME.encode("utf-8"))
    pass_ok = hmac.compare_digest(payload.password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8"))
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")
    token = generate_token(payload.username)
    return {"token": token, "status": "authenticated"}

# CONFIGURATION ENDPOINTS
@app.get("/api/config")
def get_config():
    if supabase:
        try:
            res = supabase.table("hotel_config").select("*").eq("id", 1).execute()
            if res.data:
                return res.data[0]
        except Exception as e:
            print(f"Error reading config from Supabase: {e}")
    return state_config

@app.post("/api/config")
def save_config(payload: ConfigPayload, user: str = Depends(verify_admin_token)):
    global state_config
    state_config = payload.dict()
    if supabase:
        try:
            data = payload.dict()
            data["id"] = 1
            supabase.table("hotel_config").upsert(data).execute()
        except Exception as e:
            print(f"Error saving config to Supabase: {e}")
    return {"status": "success", "config": state_config}

# ROOMS ENDPOINTS
@app.get("/api/rooms")
def get_rooms():
    if supabase:
        try:
            res = supabase.table("rooms").select("*").execute()
            if res.data and len(res.data) > 0:
                return res.data
        except Exception as e:
            print(f"Error reading rooms from Supabase: {e}")
    return state_rooms

@app.post("/api/rooms/{room_id}")
def save_room(room_id: str, payload: RoomPayload, user: str = Depends(verify_admin_token)):
    room_data = payload.dict()
    room_data["id"] = room_id
    if supabase:
        try:
            supabase.table("rooms").upsert(room_data).execute()
            return {"status": "persisted", "room": room_data}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Supabase database error: {e}")
    
    # In-memory fallback
    for idx, r in enumerate(state_rooms):
        if r["id"] == room_id:
            state_rooms[idx] = room_data
            return {"status": "updated", "room": room_data}
    state_rooms.append(room_data)
    return {"status": "created", "room": room_data}

# GALLERY ENDPOINTS (Persists Drive Photos)
@app.get("/api/gallery")
def get_gallery():
    if supabase:
        try:
            res = supabase.table("gallery").select("*").order("created_at", desc=False).execute()
            if res.data and len(res.data) > 0:
                return res.data
        except Exception as e:
            print(f"Error fetching gallery from Supabase: {e}")
    return state_gallery

@app.post("/api/gallery")
def add_gallery_item(payload: GalleryPayload, user: str = Depends(verify_admin_token)):
    item = payload.dict()
    if supabase:
        try:
            supabase.table("gallery").upsert(item).execute()
            return {"status": "saved_to_database", "item": item}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to persist photo in Supabase: {e}")
    state_gallery.append(item)
    return {"status": "saved_in_memory", "item": item}

@app.delete("/api/gallery/{item_id}")
def delete_gallery_item(item_id: str, user: str = Depends(verify_admin_token)):
    if supabase:
        try:
            supabase.table("gallery").delete().eq("id", item_id).execute()
            return {"status": "deleted_from_database"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete photo from Supabase: {e}")
    global state_gallery
    state_gallery = [g for g in state_gallery if g["id"] != item_id]
    return {"status": "deleted_from_memory"}

# BOOKINGS ENDPOINTS
@app.get("/api/bookings")
def get_bookings(user: str = Depends(verify_admin_token)):
    if supabase:
        try:
            res = supabase.table("bookings").select("*").order("created_at", desc=True).execute()
            return res.data
        except Exception as e:
            print(f"Error fetching bookings from Supabase: {e}")
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
    # Lookup room price either from Supabase or fallback
    room = None
    if supabase:
        try:
            r_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
            if r_res.data:
                room = r_res.data[0]
        except Exception:
            pass
    if not room:
        room = next((r for r in state_rooms if r["id"] == room_id), {"name": "Deluxe Room", "price": 2200, "h1": 600, "h2": 1000, "h3": 1300, "hday": 1500})

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
    new_booking = {
        "id": booking_id,
        "guest_name": name,
        "phone": phone,
        "room_id": room_id,
        "room_name": room.get("name", "Standard Room"),
        "booking_type": booking_type,
        "start_date": start_date,
        "end_date": end_date,
        "hours": hours,
        "guests": guests,
        "document_url": id_proof,
        "total": total,
        "discount_pct": discount_pct,
        "status": "Pending",
        "room_number": None,
        "check_in_time": None,
        "created_at": datetime.utcnow().isoformat()
    }

    if supabase:
        try:
            supabase.table("bookings").insert(new_booking).execute()
        except Exception as e:
            print(f"Error persisting booking in Supabase: {e}")
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

    if supabase:
        try:
            res = supabase.table("bookings").update(update_data).eq("id", booking_id).execute()
            if res.data:
                return {"status": "success", "booking": res.data[0]}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database update failed: {e}")

    for b in state_bookings:
        if str(b["id"]) == str(booking_id):
            b.update(update_data)
            return {"status": "success", "booking": b}

    raise HTTPException(status_code=404, detail="Booking record not found.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
