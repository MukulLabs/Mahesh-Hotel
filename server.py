import os
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
from supabase import create_client, Client

app = FastAPI(title="Hotel Mahesh Cloud Backend", version="1.0.0")

# Enable CORS for frontends (local or live hosted website)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- CONFIGURATION -----------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres.cuamqcialyoehjxpagje:N0fle8N5ZCJxVsvE@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
)
SUPABASE_URL = "https://cuamqcialyoehjxpagje.supabase.co"
SUPABASE_KEY = "sb_publishable_tgzfLLlBQgPWfXlThaUV4w_KmlPsrYu"
BUCKET_NAME = "Mahesh Hotel Assets"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# ----------------- SCHEMAS -----------------
class RoomUpdate(BaseModel):
    name: str
    price: int
    sleeps: str
    description: str
    image_url: str
    h1: int
    h2: int
    h3: int
    hday: int

class SettingsUpdate(BaseModel):
    d2: int = 20
    d3: int = 25
    d4plus: int = 30
    event_full: int = 1000
    event_six: int = 400

# ----------------- ROOMS API -----------------
@app.get("/api/rooms")
def list_rooms():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM rooms ORDER BY price ASC;")
        rooms = cur.fetchall()
    conn.close()
    return rooms

@app.post("/api/rooms/{room_id}")
def update_room(room_id: str, room: RoomUpdate):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
        INSERT INTO rooms (id, name, price, sleeps, description, image_url, h1, h2, h3, hday)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            price = EXCLUDED.price,
            sleeps = EXCLUDED.sleeps,
            description = EXCLUDED.description,
            image_url = EXCLUDED.image_url,
            h1 = EXCLUDED.h1,
            h2 = EXCLUDED.h2,
            h3 = EXCLUDED.h3,
            hday = EXCLUDED.hday;
        """, (room_id, room.name, room.price, room.sleeps, room.description, room.image_url, room.h1, room.h2, room.h3, room.hday))
        conn.commit()
    conn.close()
    return {"status": "success", "room_id": room_id}

# ----------------- SETTINGS / CONFIGURATION API -----------------
@app.get("/api/config")
def get_config():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM settings;")
        settings = dict(cur.fetchall())
    conn.close()
    return {
        "d2": int(settings.get("d2", 20)),
        "d3": int(settings.get("d3", 25)),
        "d4plus": int(settings.get("d4plus", 30)),
        "event_full": int(settings.get("event_full", 1000)),
        "event_six": int(settings.get("event_six", 400))
    }

@app.post("/api/config")
def update_config(conf: SettingsUpdate):
    conn = get_db()
    with conn.cursor() as cur:
        for k, v in conf.model_dump().items():
            cur.execute("""
            INSERT INTO settings (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
            """, (k, str(v)))
        conn.commit()
    conn.close()
    return {"status": "success", "config": conf}

# ----------------- IMAGE / ASSET UPLOADER -----------------
@app.post("/api/upload")
async def upload_asset(file: UploadFile = File(...)):
    """Uploads room photos or receipts to Supabase Storage and returns a permanent public link"""
    content = await file.read()
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    file_path = f"rooms/{int(datetime.now().timestamp())}_{file.filename}"
    
    supabase.storage.from_(BUCKET_NAME).upload(
        path=file_path,
        file=content,
        file_options={"content-type": file.content_type or "image/jpeg", "upsert": "true"}
    )
    public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_path)
    return {"url": public_url}

# ----------------- BOOKING ENGINE -----------------
@app.post("/api/bookings")
async def create_booking(
    name: str = Form(...),
    phone: str = Form(...),
    room_id: str = Form(...),
    booking_type: str = Form(...), # 'night' or 'hour'
    start_date: str = Form(...),
    end_date: Optional[str] = Form(None),
    hours: int = Form(0),
    guests: int = Form(2),
    id_proof: Optional[str] = Form(None),
    id_file: Optional[UploadFile] = File(None)
):
    conn = get_db()
    with conn.cursor() as cur:
        # 1. Fetch room details
        cur.execute("SELECT * FROM rooms WHERE id = %s;", (room_id,))
        room = cur.fetchone()
        if not room:
            conn.close()
            raise HTTPException(status_code=404, detail="Room not found")

        # 2. Upload document if attached
        doc_url = None
        if id_file:
            content = await id_file.read()
            fpath = f"documents/{phone}_{int(datetime.now().timestamp())}_{id_file.filename}"
            supabase.storage.from_(BUCKET_NAME).upload(
                path=fpath,
                file=content,
                file_options={"content-type": id_file.content_type or "application/octet-stream", "upsert": "true"}
            )
            doc_url = supabase.storage.from_(BUCKET_NAME).get_public_url(fpath)

        # 3. Fetch pricing rules
        cur.execute("SELECT key, value FROM settings;")
        settings = dict(cur.fetchall())
        d2 = int(settings.get("d2", 20))
        d3 = int(settings.get("d3", 25))
        d4 = int(settings.get("d4plus", 30))

        discount_pct = 0
        if booking_type == "hour":
            if hours == 1: total = room["h1"]
            elif hours == 2: total = room["h2"]
            elif hours == 3: total = room["h3"]
            else: total = room["hday"]
        else:
            d_start = datetime.strptime(start_date, "%Y-%m-%d")
            d_end = datetime.strptime(end_date, "%Y-%m-%d")
            nights = max(1, (d_end - d_start).days)
            base_total = nights * room["price"]
            
            if nights == 2: discount_pct = d2
            elif nights == 3: discount_pct = d3
            elif nights >= 4: discount_pct = d4
            
            total = int(base_total * (1 - (discount_pct / 100.0)))

        booking_id = f"HM-{int(datetime.now().timestamp())}"
        
        # 4. Save reservation
        cur.execute("""
        INSERT INTO bookings (
            id, guest_name, phone, room_name, booking_type, start_date, end_date, 
            hours, guests, total, discount_pct, status, document_url
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending', %s);
        """, (
            booking_id, name, phone, room["name"], booking_type,
            start_date, end_date or start_date, hours, guests,
            total, discount_pct, doc_url or id_proof
        ))
        conn.commit()
    conn.close()

    return {
        "booking_id": booking_id,
        "total": total,
        "discount_applied": discount_pct,
        "document_url": doc_url,
        "status": "Pending"
    }

@app.get("/api/bookings")
def get_all_bookings():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM bookings ORDER BY created_at DESC;")
        bookings = cur.fetchall()
    conn.close()
    return bookings

@app.patch("/api/bookings/{booking_id}/status")
def update_status(booking_id: str, new_status: str):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("UPDATE bookings SET status = %s WHERE id = %s;", (new_status, booking_id))
        conn.commit()
    conn.close()
    return {"status": "updated", "id": booking_id, "new_status": new_status}