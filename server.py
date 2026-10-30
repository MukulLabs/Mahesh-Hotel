"""
Hotel Mahesh API  (FastAPI + Supabase)

Security model
--------------
* The browser NEVER talks to Supabase. Only this server does, using the
  service_role key, which lives only in Render environment variables.
* Prices, discounts and availability are computed inside the database
  (create_booking function in schema.sql). The client cannot influence them.
* No default secrets: the server refuses to start if any secret is missing/weak.
* No in-memory fallbacks: if the database is unreachable, requests FAIL
  (a guest is never shown a booking that was not saved).
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

import httpx
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from supabase import create_client

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hotel")

# ----------------------------------------------------------------------
# 1. CONFIGURATION (fail closed)
# ----------------------------------------------------------------------
def env(name: str, min_len: int = 1) -> str:
    v = os.environ.get(name, "").strip()
    if len(v) < min_len:
        raise RuntimeError(f"Environment variable {name} is required (min {min_len} chars).")
    return v


SUPABASE_URL = env("SUPABASE_URL")
SUPABASE_KEY = env("SUPABASE_KEY", 20)        # service_role key (server only!)
ADMIN_USERNAME = env("HOTEL_ADMIN_USER", 3)
ADMIN_PASSWORD = env("HOTEL_ADMIN_PASS", 12)
AUTH_SECRET = env("AUTH_SECRET_KEY", 32)
ALERT_WEBHOOK = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "https://mukullabs.github.io").split(",") if o.strip()]

if ADMIN_PASSWORD in {"mahesh@123", "password", "admin"} or AUTH_SECRET.startswith("hotel-mahesh"):
    raise RuntimeError("Known/default credentials detected. Set new secrets in Render.")

TOKEN_TTL_SECONDS = 8 * 3600
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ----------------------------------------------------------------------
# 2. APP, RATE LIMITING, CORS, HEADERS
# ----------------------------------------------------------------------
def client_ip(request: Request) -> str:
    """Real client IP behind Render's proxy: the entry appended by the proxy
    (rightmost), never the client-supplied leftmost one."""
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if len(parts) >= TRUSTED_PROXY_HOPS:
        return parts[-TRUSTED_PROXY_HOPS]
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=client_ip, default_limits=["120/minute"])

app = FastAPI(title="Hotel Mahesh API", version="3.0.0",
              docs_url=None, redoc_url=None, openapi_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/") and request.url.path not in ("/api/rooms", "/api/gallery", "/api/config"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# CORS is added last so it is the outermost layer (429/4xx responses keep CORS headers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,                      # Bearer tokens, no cookies
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

# ----------------------------------------------------------------------
# 3. HELPERS
# ----------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}


def cached(key: str, ttl: int, loader: Callable[[], Any]) -> Any:
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = loader()
    _cache[key] = (now, val)
    return val


def run(op: Callable[[], Any], what: str) -> Any:
    """Run a DB call; never leak internals to the client."""
    try:
        return op()
    except HTTPException:
        raise
    except Exception:
        log.exception("DB error while %s", what)
        raise HTTPException(503, "Service temporarily unavailable. Please try again.")


def audit(actor: str, action: str, detail: dict) -> None:
    try:
        sb.table("audit_log").insert({"actor": actor, "action": action, "detail": detail}).execute()
    except Exception:
        log.exception("audit write failed")


def alert(text: str) -> None:
    log.warning("ALERT: %s", text)
    if not ALERT_WEBHOOK:
        return
    try:
        httpx.post(ALERT_WEBHOOK, json={"text": text}, timeout=5)
    except Exception:
        log.warning("alert webhook failed")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user: str) -> str:
    payload = _b64(json.dumps({"u": user, "exp": int(time.time()) + TOKEN_TTL_SECONDS},
                              separators=(",", ":")).encode())
    sig = _b64(hmac.new(AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def current_admin(authorization: Optional[str] = Header(None)) -> str:
    bad = HTTPException(401, "Invalid or expired session.")
    if not authorization or not authorization.startswith("Bearer "):
        raise bad
    try:
        payload, sig = authorization[7:].split(".", 1)
        expected = _b64(hmac.new(AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise bad
        data = json.loads(_unb64(payload))
        if int(data["exp"]) < time.time():
            raise bad
        return str(data["u"])
    except HTTPException:
        raise
    except Exception:
        raise bad


PHONE_RE = re.compile(r"^[0-9]{10}$")
LAST4_RE = re.compile(r"^[0-9A-Za-z]{4}$")
ROOMNO_RE = re.compile(r"^[A-Za-z0-9-]{1,10}$")
UPI_RE = re.compile(r"^[A-Za-z0-9._-]{2,64}@[A-Za-z0-9]{2,32}$")
DOC_TYPES = {"Govt ID Proof", "Voter ID", "Driving Licence", "Passport", "Other Govt ID"}


def clean_name(name: str) -> str:
    n = re.sub(r"\s+", " ", name or "").strip()
    if not (2 <= len(n) <= 100) or re.search(r"[<>\x00-\x1f]", n):
        raise HTTPException(422, "Please enter a valid guest name.")
    return n


def parse_date(s: str) -> "datetime.date":
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(422, "Invalid date.")


def normalize_id_proof(raw: str, staff: bool = False) -> str:
    raw = (raw or "").strip()
    if staff and raw in ("", "Counter Walk-in"):
        return "Counter Walk-in"
    doc, _, last4 = raw.partition(":")
    doc, last4 = doc.strip(), last4.strip()
    allowed = DOC_TYPES | ({"Front Desk"} if staff else set())
    if doc not in allowed or not LAST4_RE.match(last4):
        raise HTTPException(422, "Please enter a valid ID type and last 4 characters.")
    return f"{doc}: {last4}"


RPC_ERRORS = {
    "sold_out": (409, "Sorry, this room category is fully booked for the selected dates."),
    "too_many_pending": (429, "Too many unconfirmed bookings for this number. Please call the front desk."),
    "room_not_found": (404, "Room category not found."),
    "past_date": (422, "Dates cannot be in the past."),
    "invalid_dates": (422, "Please check your dates."),
    "invalid_hours": (422, "Invalid stay duration."),
    "invalid_guests": (422, "Invalid number of guests."),
    "invalid_type": (422, "Invalid stay type."),
}


def create_booking_record(*, name, phone, room_id, booking_type, start_date, end_date,
                          hours, guests, id_proof, payment_mode, status,
                          verified_by=None, room_number=None, staff=False) -> dict:
    name = clean_name(name)
    if not PHONE_RE.match(phone or ""):
        raise HTTPException(422, "Please enter a valid 10-digit mobile number.")
    if booking_type not in ("night", "hour"):
        raise HTTPException(422, "Invalid stay type.")
    if payment_mode not in ("UPI", "Counter"):
        raise HTTPException(422, "Invalid payment option.")
    if not (1 <= guests <= 10):
        raise HTTPException(422, "Invalid number of guests.")
    d_start = parse_date(start_date)
    d_end = parse_date(end_date) if booking_type == "night" else d_start
    if booking_type == "hour" and hours not in (1, 2, 3, 6):
        raise HTTPException(422, "Invalid stay duration.")

    params = {
        "p_name": name, "p_phone": phone, "p_room_id": room_id[:50], "p_type": booking_type,
        "p_start": d_start.isoformat(), "p_end": d_end.isoformat(),
        "p_hours": hours if booking_type == "hour" else 0, "p_guests": guests,
        "p_id_proof": normalize_id_proof(id_proof, staff), "p_payment_mode": payment_mode,
        "p_status": status, "p_verified_by": verified_by, "p_room_number": room_number,
    }
    try:
        res = sb.rpc("create_booking", params).execute()
    except Exception as e:
        msg = str(e)
        for key, (code, text) in RPC_ERRORS.items():
            if key in msg:
                raise HTTPException(code, text)
        log.exception("create_booking failed")
        raise HTTPException(503, "Could not save your booking. Please try again or call the front desk.")

    row = res.data[0] if isinstance(res.data, list) and res.data else res.data
    if not row:
        raise HTTPException(503, "Could not save your booking. Please try again or call the front desk.")
    _cache.clear()
    return {"booking_id": row["o_booking_id"], "total": row["o_total"],
            "discount_applied": row["o_discount_pct"], "upi_id": row["o_upi_id"],
            "status": status, "payment_mode": payment_mode}


# ----------------------------------------------------------------------
# 4. SCHEMAS
# ----------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ConfigPayload(BaseModel):
    upi_id: str = Field(min_length=3, max_length=100)
    d2: int = Field(ge=0, le=60)
    d3: int = Field(ge=0, le=60)
    d4plus: int = Field(ge=0, le=60)
    event_full: int = Field(ge=0, le=100000)
    event_six: Optional[int] = Field(default=None, ge=0, le=100000)

    @field_validator("upi_id")
    @classmethod
    def _upi(cls, v: str) -> str:
        v = v.strip()
        if not UPI_RE.match(v):
            raise ValueError("Invalid UPI ID format")
        return v


class RoomRatesPayload(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    price: int = Field(ge=100, le=100000)
    sleeps: str = Field(default="", max_length=50)
    description: str = Field(default="", max_length=1000)
    h1: int = Field(ge=1, le=100000)
    h2: int = Field(ge=1, le=100000)
    h3: int = Field(ge=1, le=100000)
    hday: int = Field(ge=1, le=100000)

    @model_validator(mode="after")
    def _order(self):
        if not (self.h1 <= self.h2 <= self.h3 <= self.hday):
            raise ValueError("Hourly rates must not decrease: 1h <= 2h <= 3h <= day")
        return self


class StatusPayload(BaseModel):
    new_status: Literal["Confirmed", "Checked In", "Checked Out", "Cancelled"]
    room_number: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9-]{1,10}$")
    utr: Optional[str] = Field(default=None, pattern=r"^[0-9]{12}$")


TRANSITIONS = {
    "Pending": {"Confirmed", "Checked In", "Cancelled"},
    "Confirmed": {"Checked In", "Cancelled"},
    "Checked In": {"Checked Out"},
    "Checked Out": set(),
    "Cancelled": set(),
}

# ----------------------------------------------------------------------
# 5. PUBLIC ENDPOINTS
# ----------------------------------------------------------------------
@app.api_route("/api/health", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def health():
    """Keeps Supabase awake and cancels stale unpaid bookings."""
    try:
        sb.rpc("expire_stale_pending", {}).execute()
    except Exception:
        log.warning("health ping failed")
    return "ok"


@app.get("/api/config")
def get_config():
    def load():
        r = run(lambda: sb.table("hotel_config")
                .select("upi_id,d2,d3,d4plus,event_full,event_six")
                .eq("id", "global_config").limit(1).execute(), "load config")
        if not r.data:
            raise HTTPException(503, "Configuration unavailable.")
        return r.data[0]
    return cached("config", 20, load)


@app.get("/api/rooms")
def get_rooms():
    def load():
        r = run(lambda: sb.table("rooms")
                .select("id,name,price,sleeps,description,image_url,h1,h2,h3,hday")
                .order("sort_order").order("id").execute(), "load rooms")
        return r.data
    return cached("rooms", 20, load)


@app.get("/api/gallery")
def get_gallery():
    def load():
        r = run(lambda: sb.table("gallery").select("id,album,title,url")
                .order("created_at").order("id").execute(), "load gallery")
        return r.data
    return cached("gallery", 60, load)


@app.post("/api/bookings")
@limiter.limit("5/minute;30/hour")
def create_booking(
    request: Request,
    name: str = Form(..., max_length=100),
    phone: str = Form(..., max_length=20),
    room_id: str = Form(..., max_length=50),
    booking_type: str = Form(..., max_length=10),
    start_date: str = Form(..., max_length=10),
    end_date: str = Form(..., max_length=10),
    hours: int = Form(0, ge=0, le=24),
    guests: int = Form(2, ge=1, le=10),
    id_proof: str = Form(..., max_length=60),
    payment_mode: str = Form("UPI", max_length=10),
):
    return create_booking_record(
        name=name, phone=phone, room_id=room_id, booking_type=booking_type,
        start_date=start_date, end_date=end_date, hours=hours, guests=guests,
        id_proof=id_proof, payment_mode=payment_mode, status="Pending")


# ----------------------------------------------------------------------
# 6. AUTH
# ----------------------------------------------------------------------
@app.post("/api/auth/login")
@limiter.limit("5/minute;20/hour")
def login(request: Request, payload: LoginRequest):
    ok_u = hmac.compare_digest(payload.username.encode(), ADMIN_USERNAME.encode())
    ok_p = hmac.compare_digest(payload.password.encode(), ADMIN_PASSWORD.encode())
    if not (ok_u and ok_p):
        log.warning("Failed staff login from %s", client_ip(request))
        time.sleep(0.5)
        raise HTTPException(401, "Invalid username or password.")
    alert(f"Staff login: {payload.username} from {client_ip(request)}")
    return {"token": make_token(payload.username), "status": "authenticated"}


# ----------------------------------------------------------------------
# 7. STAFF ENDPOINTS (Bearer token required)
# ----------------------------------------------------------------------
@app.get("/api/bookings")
def list_bookings(user: str = Depends(current_admin)):
    r = run(lambda: sb.table("bookings").select("*")
            .order("created_at", desc=True).limit(500).execute(), "list bookings")
    return r.data


@app.post("/api/admin/bookings")
def counter_booking(
    request: Request,
    name: str = Form(..., max_length=100),
    phone: str = Form(..., max_length=20),
    room_id: str = Form(..., max_length=50),
    booking_type: str = Form(..., max_length=10),
    start_date: str = Form(..., max_length=10),
    end_date: str = Form(..., max_length=10),
    hours: int = Form(0, ge=0, le=24),
    guests: int = Form(2, ge=1, le=10),
    id_proof: str = Form("", max_length=60),
    room_number: str = Form(..., max_length=10),
    user: str = Depends(current_admin),
):
    if not ROOMNO_RE.match(room_number):
        raise HTTPException(422, "Invalid room number.")
    out = create_booking_record(
        name=name, phone=phone, room_id=room_id, booking_type=booking_type,
        start_date=start_date, end_date=end_date, hours=hours, guests=guests,
        id_proof=id_proof, payment_mode="Counter", status="Checked In",
        verified_by=user, room_number=room_number, staff=True)
    audit(user, "counter_checkin", out)
    return out


@app.patch("/api/bookings/{booking_id}/status")
def update_booking_status(booking_id: str, payload: StatusPayload, user: str = Depends(current_admin)):
    if not re.fullmatch(r"[A-Za-z0-9]{1,50}", booking_id):
        raise HTTPException(404, "Booking record not found.")
    r = run(lambda: sb.table("bookings").select("*").eq("id", booking_id).limit(1).execute(), "load booking")
    if not r.data:
        raise HTTPException(404, "Booking record not found.")
    cur = r.data[0]

    if payload.new_status not in TRANSITIONS.get(cur["status"], set()):
        raise HTTPException(409, f"Cannot change a '{cur['status']}' booking to '{payload.new_status}'.")

    upd: dict[str, Any] = {"status": payload.new_status}
    if cur["status"] == "Pending" and payload.new_status in ("Confirmed", "Checked In"):
        if cur.get("payment_mode") == "UPI" and not cur.get("utr") and not payload.utr:
            raise HTTPException(422, "Enter the 12-digit UTR from your bank before confirming a UPI booking.")
        if payload.utr:
            upd["utr"] = payload.utr
        upd["verified_by"] = user
        upd["verified_at"] = datetime.now(timezone.utc).isoformat()
    if payload.new_status == "Checked In":
        if not payload.room_number:
            raise HTTPException(422, "A room number is required to check in.")
        upd["room_number"] = payload.room_number
        upd["check_in_time"] = datetime.now(timezone.utc).isoformat()

    try:
        res = (sb.table("bookings").update(upd).eq("id", booking_id)
               .eq("status", cur["status"]).execute())
    except Exception as e:
        if "uq_bookings_utr" in str(e) or "duplicate key" in str(e):
            raise HTTPException(409, "This UTR is already linked to another booking.")
        log.exception("status update failed")
        raise HTTPException(503, "Service temporarily unavailable. Please try again.")
    if not res.data:
        raise HTTPException(409, "Booking was changed by someone else. Please refresh.")

    _cache.clear()
    audit(user, "booking_status", {"id": booking_id, "from": cur["status"], "to": payload.new_status,
                                   "utr": payload.utr, "room": payload.room_number})
    return {"status": "success", "booking": res.data[0]}


@app.post("/api/config")
def save_config(payload: ConfigPayload, user: str = Depends(current_admin)):
    r = run(lambda: sb.table("hotel_config").select("*").eq("id", "global_config").limit(1).execute(), "load config")
    old = r.data[0] if r.data else {}
    data = {
        "id": "global_config", "upi_id": payload.upi_id,
        "d2": payload.d2, "d3": payload.d3, "d4plus": payload.d4plus,
        "event_full": payload.event_full,
        "event_six": payload.event_six if payload.event_six is not None else old.get("event_six", 400),
    }
    run(lambda: sb.table("hotel_config").upsert(data).execute(), "save config")
    _cache.clear()
    audit(user, "config_update", {"old": old, "new": data})
    if old.get("upi_id") != data["upi_id"]:
        alert(f"UPI ID CHANGED by {user}: {old.get('upi_id')} -> {data['upi_id']}")
    return {"status": "success", "config": data}


@app.post("/api/rooms/{room_id}")
def update_room(room_id: str, payload: RoomRatesPayload, user: str = Depends(current_admin)):
    """Edits an EXISTING room's rates/text. Images and new rooms are managed in Supabase."""
    data = payload.model_dump()
    res = run(lambda: sb.table("rooms").update(data).eq("id", room_id).execute(), "update room")
    if not res.data:
        raise HTTPException(404, "Room not found.")
    _cache.clear()
    audit(user, "room_update", {"id": room_id, **data})
    return {"status": "saved", "room": res.data[0]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
