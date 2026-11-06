"""StyleKart return-support mock API, called by the Ringg voice agent.

Business endpoints (no auth; this is a dummy backend):
  GET  /customers/by-phone/{phone}   who is calling + their recent delivered items
  POST /returns/eligibility           is this item returnable? (backend decides)
  GET  /pickup-slots/{order_id}       pickup windows the agent may offer
  POST /returns                       create the return (idempotent per item)
  POST /quality-tickets               damaged/wrong item that can't be returned
  POST /callbacks                     book a callback when anything fails
  GET  /refunds/{order_id}            read-only refund status

Admin endpoints for testing and evals:
  POST /admin/reset   GET /admin/state/{phone}   POST /admin/map-phone
  POST /admin/clock   GET /admin/events

Emails (app/mailer.py) go out through Brevo in a background task, so they never
slow down or break a response. Their links open the pages in app/pages.py.

Every response carries a `say` field: a short Hinglish line the agent can read
out as-is. Errors use the same shape: {"detail": {"code", "say"}}.
"""

import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import clock, mailer, notify, pages, policy
from .db import get_conn, tx
from .phones import normalize_phone
from .seed import reset_data
from .slots import available_slots, describe_slot
from .speech import amount_text, delivered_text, spell_id

SLOW_CREATE_SECONDS = float(os.environ.get("SLOW_CREATE_SECONDS", "5"))
MAX_ITEMS_LISTED = 5


@asynccontextmanager
async def lifespan(_app: FastAPI):
    conn = get_conn()
    if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        reset_data()
    yield


app = FastAPI(
    title="StyleKart Return Support API",
    version="1.0.0",
    description="Mock e-commerce backend for the StyleKart Ringg voice agent.",
    lifespan=lifespan,
)
app.include_router(pages.router)


# ---------------------------------------------------------------- helpers

def queue_email(tasks: BackgroundTasks, customer: dict, kind: str, build) -> bool:
    """Build an email now (this creates its links) and send it after the response.

    `build` returns (subject, html, text). Any error is recorded, never raised.
    """
    try:
        subject, html, text = build()
    except Exception as exc:
        try:
            mailer.record(customer.get("customer_id"), customer["email"], f"({kind})", kind,
                          "failed", f"build error: {type(exc).__name__}: {exc}"[:300])
        except Exception:
            pass
        return False
    tasks.add_task(mailer.send_email, customer.get("customer_id"), customer["email"],
                   customer.get("full_name") or customer.get("first_name", ""), subject, html, text, kind)
    return True


def log_event(endpoint: str, request: dict | None, status: int, response: dict | None) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO events (at, endpoint, request, status, response) VALUES (?, ?, ?, ?, ?)",
            (clock.now_ist().isoformat(), endpoint, json.dumps(request or {}),
             status, json.dumps(response or {}, ensure_ascii=False)),
        )


def fail(endpoint: str, request: dict | None, status: int, code: str, say: str, **extra):
    detail = {"code": code, "say": say, **extra}
    log_event(endpoint, request, status, {"detail": detail})
    raise HTTPException(status, detail)


def ok(endpoint: str, request: dict | None, body: dict) -> dict:
    log_event(endpoint, request, 200, body)
    return body


def load_item(endpoint: str, req: dict, order_id: str, item_id: str, phone: str | None) -> dict:
    """Fetch an item with its order and owner; enforce that it belongs to the caller."""
    row = get_conn().execute(
        """SELECT i.*, o.customer_id, o.payment_mode, o.behaviour,
                  c.phone AS owner_phone, c.address_short, c.pincode, c.first_name,
                  c.full_name, c.email
           FROM items i JOIN orders o ON o.id = i.order_id
           JOIN customers c ON c.id = o.customer_id
           WHERE i.id = ? AND i.order_id = ?""",
        (item_id.strip().upper(), order_id.strip().upper()),
    ).fetchone()
    if row is None:
        fail(endpoint, req, 404, "ITEM_NOT_FOUND", "Yeh item is order mein nahi mila.")
    item = dict(row)
    if phone and normalize_phone(phone) != item["owner_phone"]:
        fail(endpoint, req, 403, "NOT_OWNER", "Yeh order aapke number par registered nahi hai.")
    return item


def existing_return(item_id: str) -> dict | None:
    row = get_conn().execute("SELECT * FROM returns WHERE item_id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def refund_eta_text(payment_mode: str) -> str:
    if payment_mode == "cod":
        return ("Cash on delivery order hai, isliye refund ke liye bank details chahiye. "
                "Humne aapke registered email par ek link bheja hai. Details milne ke 5 se 7 din mein refund aa jayega.")
    return "Pickup ke baad 5 se 7 din mein refund original payment method mein aa jayega."


def return_body(ret: dict, item: dict, already_existed: bool) -> dict:
    pickup = describe_slot(ret["slot_id"])
    cod = item["payment_mode"] == "cod"
    return {
        "return_id": ret["id"],
        "return_id_spoken": spell_id(ret["id"]),
        "already_existed": already_existed,
        "item_name": item["name"],
        "pickup_text": pickup,
        "address_short": item["address_short"],
        "refund_amount_text": amount_text(ret["refund_amount"]),
        "refund_eta_text": refund_eta_text(item["payment_mode"]),
        "cod_link_emailed": cod,
        "email_masked": mailer.mask_email(item["email"]),
        "say": (f"Aapka return book ho gaya hai. Return ID hai {spell_id(ret['id'])}. "
                f"Pickup {pickup}, {item['address_short']} wale address par hoga."),
    }


# ---------------------------------------------------------------- health

@app.get("/")
def root():
    return {"service": "stylekart-returns", "status": "ok", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok", "time_ist": clock.now_ist().isoformat(), "clock_frozen": clock.is_frozen()}


# ---------------------------------------------------------------- 1. customer lookup

@app.get("/customers/by-phone/{phone}")
def customer_by_phone(phone: str):
    ep, req = "GET /customers/by-phone", {"phone": phone}
    conn = get_conn()
    cust = conn.execute("SELECT * FROM customers WHERE phone = ?", (normalize_phone(phone),)).fetchone()
    if cust is None:
        return ok(ep, req, {
            "found": False,
            "first_name_hi": None,
            "say": "Is number par koi StyleKart account nahi mila. Kya aap apna registered mobile number bata sakte hain?",
        })

    today = clock.today_ist()
    rows = conn.execute(
        """SELECT i.id AS item_id, i.order_id, i.name, i.status, i.delivered_on, o.payment_mode
           FROM items i JOIN orders o ON o.id = i.order_id
           WHERE o.customer_id = ?
           ORDER BY COALESCE(i.delivered_on, '9999-12-31') DESC, i.id""",
        (cust["id"],),
    ).fetchall()

    items = []
    for r in rows[:MAX_ITEMS_LISTED]:
        if r["status"] == "delivered":
            when = delivered_text(datetime.fromisoformat(r["delivered_on"]).date(), today)
        else:
            when = "abhi deliver nahi hua (raste mein hai)"
        items.append({
            "order_id": r["order_id"],
            "item_id": r["item_id"],
            "item_name": r["name"],
            "status": r["status"],
            "delivered_on_text": when,
            "payment_mode": r["payment_mode"],
        })

    summary = "; ".join(f"{n}) {it['item_name']}, {it['delivered_on_text']}" for n, it in enumerate(items, 1))
    return ok(ep, req, {
        "found": True,
        "customer_id": cust["id"],
        "first_name": cust["first_name"],
        "first_name_hi": cust["first_name_hi"],
        "full_name": cust["full_name"],
        "email_masked": mailer.mask_email(cust["email"]),
        "item_count": len(items),
        "items": items,
        "items_summary": summary,
        "say": f"Namaste {cust['first_name']} ji. Aapke recent items: {summary}.",
    })


# ---------------------------------------------------------------- 2. eligibility

class EligibilityIn(BaseModel):
    order_id: str = Field(examples=["SK1001"])
    item_id: str = Field(examples=["SK1001-1"])
    phone: str | None = Field(default=None, description="Caller's number; if sent, must own the order.")


@app.post("/returns/eligibility")
def eligibility(body: EligibilityIn):
    ep, req = "POST /returns/eligibility", body.model_dump()
    item = load_item(ep, req, body.order_id, body.item_id, body.phone)
    if item["behaviour"] == "eligibility_500":
        fail(ep, req, 500, "UPSTREAM_ERROR", "Abhi system se jaankari nahi mil pa rahi hai.")

    ret = existing_return(item["id"])
    result = policy.check(item, ret, clock.today_ist())
    return ok(ep, req, {
        "eligible": result.eligible,
        "reason_code": result.reason_code,
        "days_left": result.days_left,
        "days_past": result.days_past,
        "existing_return_status": result.existing_return_status,
        "item_name": item["name"],
        "say": result.say,
    })


# ---------------------------------------------------------------- 3. pickup slots

@app.get("/pickup-slots/{order_id}")
def pickup_slots(order_id: str):
    ep, req = "GET /pickup-slots", {"order_id": order_id}
    row = get_conn().execute(
        """SELECT c.address_short, c.pincode FROM orders o JOIN customers c ON c.id = o.customer_id
           WHERE o.id = ?""",
        (order_id.strip().upper(),),
    ).fetchone()
    if row is None:
        fail(ep, req, 404, "ORDER_NOT_FOUND", "Yeh order nahi mila.")

    slots = available_slots(row["pincode"])
    if not slots:
        return ok(ep, req, {
            "slots_available": False,
            "slots": [],
            "address_short": row["address_short"],
            "say": "Maaf kijiye, aapke area mein agle 3 din pickup available nahi hai. Main aapke liye callback book kar sakti hoon.",
        })
    options = ", ".join(s["slot_text"] for s in slots[:3])
    return ok(ep, req, {
        "slots_available": True,
        "slots": slots,
        "address_short": row["address_short"],
        "say": f"Pickup ke liye yeh time available hain: {options}. Aapko kaunsa time theek rahega?",
    })


# ---------------------------------------------------------------- 4. create return

class ReturnIn(BaseModel):
    order_id: str = Field(examples=["SK1001"])
    item_id: str = Field(examples=["SK1001-1"])
    reason: str = Field(min_length=2, max_length=200, examples=["size issue"])
    slot_id: str = Field(examples=["2026-11-07_evening"])
    phone: str | None = None


@app.post("/returns")
def create_return(body: ReturnIn, tasks: BackgroundTasks):
    ep, req = "POST /returns", body.model_dump()
    item = load_item(ep, req, body.order_id, body.item_id, body.phone)

    # Idempotent: a repeat call (e.g. after a timeout) returns the same return.
    ret = existing_return(item["id"])
    if ret is not None:
        return ok(ep, req, return_body(ret, item, already_existed=True))

    # Critical gate: never create a return the policy doesn't allow.
    result = policy.check(item, None, clock.today_ist())
    if not result.eligible:
        fail(ep, req, 409, result.reason_code, result.say)

    valid = {s["slot_id"]: s for s in available_slots(item["pincode"])}
    if body.slot_id not in valid:
        fail(ep, req, 422, "SLOT_UNAVAILABLE", "Yeh pickup time available nahi hai.",
             available_slots=[s["slot_text"] for s in valid.values()])

    with tx() as conn:
        # Re-check inside the transaction so two simultaneous calls can't both insert.
        ret = existing_return(item["id"])
        if ret is None:
            seq = conn.execute("SELECT COUNT(*) FROM returns").fetchone()[0]
            ret = {
                "id": f"RT{48201 + seq}",
                "order_id": item["order_id"],
                "item_id": item["id"],
                "reason": body.reason.strip(),
                "slot_id": body.slot_id,
                "status": "pickup_scheduled",
                "refund_amount": item["price"],
                "created_at": clock.now_ist().isoformat(),
            }
            conn.execute("INSERT INTO returns VALUES (:id, :order_id, :item_id, :reason, :slot_id, "
                         ":status, :refund_amount, :created_at)", ret)
            already = False
        else:
            already = True

    # Test hook: the record is saved, but the reply is slow enough to look like
    # a timeout. A retry must return this same return, never a second one.
    if not already:
        queue_email(tasks, item, "return_booked",
                    lambda: notify.return_booked(ret, item, mailer.public_base_url()))

    if item["behaviour"] == "slow_create" and not already:
        time.sleep(SLOW_CREATE_SECONDS)

    return ok(ep, req, return_body(ret, item, already_existed=already))


# ---------------------------------------------------------------- quality ticket

class QualityTicketIn(BaseModel):
    order_id: str
    item_id: str
    issue: str = Field(min_length=2, max_length=300, examples=["item arrived torn"])
    phone: str | None = None


@app.post("/quality-tickets")
def quality_ticket(body: QualityTicketIn, tasks: BackgroundTasks):
    ep, req = "POST /quality-tickets", body.model_dump()
    item = load_item(ep, req, body.order_id, body.item_id, body.phone)
    with tx() as conn:
        seq = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        tid = f"QT{70101 + seq}"
        conn.execute("INSERT INTO tickets VALUES (?, 'quality', ?, ?, ?, ?, ?)",
                     (tid, item["owner_phone"], item["order_id"], item["id"],
                      body.issue.strip(), clock.now_ist().isoformat()))
    queue_email(tasks, item, "quality_ticket",
                lambda: notify.quality_ticket(tid, item, body.issue.strip(), mailer.public_base_url()))
    return ok(ep, req, {
        "ticket_id": tid,
        "ticket_id_spoken": spell_id(tid),
        "photo_link_emailed": True,
        "email_masked": mailer.mask_email(item["email"]),
        "say": (f"Maine aapki complaint register kar di hai, ticket number {spell_id(tid)}. "
                "Item ki photo upload karne ke liye aapke registered email par link bheja hai. "
                "Team 48 ghante mein contact karegi."),
    })


# ---------------------------------------------------------------- 5. callback

class CallbackIn(BaseModel):
    phone: str
    topic: str = Field(min_length=2, max_length=200, examples=["return pickup not available"])
    preferred_time: str | None = Field(default=None, examples=["kal subah"])


@app.post("/callbacks")
def callback(body: CallbackIn, tasks: BackgroundTasks):
    ep, req = "POST /callbacks", body.model_dump()
    phone = normalize_phone(body.phone)
    if not phone:
        fail(ep, req, 422, "PHONE_REQUIRED", "Callback ke liye mobile number chahiye.")
    when = body.preferred_time.strip() if body.preferred_time else "agle 24 ghante mein"
    with tx() as conn:
        seq = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        cid = f"CB{70101 + seq}"
        conn.execute("INSERT INTO tickets VALUES (?, 'callback', ?, NULL, NULL, ?, ?)",
                     (cid, phone, f"{body.topic.strip()} | when: {when}", clock.now_ist().isoformat()))
    cust = get_conn().execute("SELECT id AS customer_id, * FROM customers WHERE phone = ?", (phone,)).fetchone()
    if cust is not None:
        cust = dict(cust)
        queue_email(tasks, cust, "callback",
                    lambda: notify.callback_booked(cid, cust["first_name"], body.topic.strip(), when))
    return ok(ep, req, {
        "callback_id": cid,
        "callback_text": when,
        "confirmation_emailed": cust is not None,
        "email_masked": mailer.mask_email(cust["email"]) if cust else None,
        "say": f"Theek hai, hamari team {when} aapko call karegi.",
    })


# ---------------------------------------------------------------- 6. refund status

@app.get("/refunds/{order_id}")
def refund_status(order_id: str):
    ep, req = "GET /refunds", {"order_id": order_id}
    conn = get_conn()
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id.strip().upper(),)).fetchone()
    if order is None:
        fail(ep, req, 404, "ORDER_NOT_FOUND", "Yeh order nahi mila.")
    rets = conn.execute(
        "SELECT r.*, i.name FROM returns r JOIN items i ON i.id = r.item_id WHERE r.order_id = ?",
        (order["id"],),
    ).fetchall()
    if not rets:
        return ok(ep, req, {"has_return": False, "returns": [],
                            "say": "Is order par koi return book nahi hai, isliye refund pending nahi hai."})

    out, lines = [], []
    for r in rets:
        amount = amount_text(r["refund_amount"])
        if r["status"] == "refunded":
            text = f"{r['name']} ka {amount} ka refund ho chuka hai, original payment method mein."
        elif r["status"] == "picked_up":
            text = f"{r['name']} pick up ho gaya hai. {amount} ka refund 5 se 7 din mein aayega."
        else:
            text = (f"{r['name']} ka pickup {describe_slot(r['slot_id'])} scheduled hai. "
                    f"Pickup ke baad {amount} ka refund 5 se 7 din mein aayega.")
        out.append({"return_id": r["id"], "status": r["status"], "refund_status_text": text})
        lines.append(text)
    return ok(ep, req, {"has_return": True, "returns": out, "say": " ".join(lines)})


# ---------------------------------------------------------------- admin

@app.post("/admin/reset")
def admin_reset():
    reset_data()
    return {"reset": True, "today_ist": clock.today_ist().isoformat()}


@app.get("/admin/state/{phone}")
def admin_state(phone: str):
    conn = get_conn()
    cust = conn.execute("SELECT * FROM customers WHERE phone = ?", (normalize_phone(phone),)).fetchone()
    if cust is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "say": "No customer on this number."})
    orders = [dict(o) for o in conn.execute("SELECT * FROM orders WHERE customer_id = ?", (cust["id"],))]
    for o in orders:
        o["items"] = [dict(i) for i in conn.execute("SELECT * FROM items WHERE order_id = ?", (o["id"],))]
    order_ids = [o["id"] for o in orders] or [""]
    marks = ",".join("?" * len(order_ids))
    returns = [dict(r) for r in conn.execute(f"SELECT * FROM returns WHERE order_id IN ({marks})", order_ids)]
    tickets = [dict(t) for t in conn.execute("SELECT * FROM tickets WHERE phone = ?", (cust["phone"],))]
    emails = [dict(e) for e in conn.execute("SELECT * FROM emails WHERE customer_id = ? ORDER BY id",
                                            (cust["id"],))]
    customer = dict(cust)
    customer["email"] = mailer.mask_email(customer["email"])  # never expose the full address
    return {"customer": customer, "orders": orders, "returns": returns, "tickets": tickets, "emails": emails}


class MapPhoneIn(BaseModel):
    phone: str = Field(examples=["+917505062257"])
    customer_id: str = Field(examples=["C04"])


@app.post("/admin/map-phone")
def admin_map_phone(body: MapPhoneIn):
    """Point your real number at any seed customer before a test call."""
    phone = normalize_phone(body.phone)
    with tx() as conn:
        target = conn.execute("SELECT * FROM customers WHERE id = ?", (body.customer_id.upper(),)).fetchone()
        if target is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "say": "Unknown customer_id."})
        # Whoever held this number before is parked on a dummy number.
        conn.execute("UPDATE customers SET phone = '+91000000' || substr(id, 2) WHERE phone = ? AND id != ?",
                     (phone, target["id"]))
        conn.execute("UPDATE customers SET phone = ? WHERE id = ?", (phone, target["id"]))
    return {"mapped": True, "phone": phone, "customer_id": target["id"], "first_name": target["first_name"]}


class ClockIn(BaseModel):
    now: datetime | None = Field(default=None, examples=["2026-11-06T23:50:00"],
                                 description="India time to freeze at; null returns to the real clock.")


@app.post("/admin/clock")
def admin_clock(body: ClockIn):
    """Freeze time for time-of-day tests. Call /admin/reset afterwards so seed dates follow."""
    clock.freeze(body.now)
    return {"now_ist": clock.now_ist().isoformat(), "frozen": clock.is_frozen()}


@app.get("/admin/events")
def admin_events(limit: int = 50):
    rows = get_conn().execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (min(limit, 500),)).fetchall()
    out = []
    for r in rows:
        e = dict(r)
        e["request"] = json.loads(e["request"] or "{}")
        e["response"] = json.loads(e["response"] or "{}")
        out.append(e)
    return {"events": out}
