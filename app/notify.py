"""What each email says, and the one-time links inside them.

Emails are written in English (unlike the Hinglish `say` lines, which are spoken),
with a plain-text copy for clients that don't render HTML. Each one states that
StyleKart is a demo brand.
"""

import secrets
from datetime import date
from html import escape

from . import clock
from .db import tx
from .speech import PERIODS, amount_text

DEMO_NOTE = ("StyleKart is a demo brand used to test a voice support agent. "
             "No real order, payment or pickup exists.")

def create_link(kind: str, ref_id: str) -> str:
    """Store a new random token for this return/ticket and return it."""
    token = secrets.token_urlsafe(16)
    with tx() as conn:
        conn.execute("INSERT INTO links (token, kind, ref_id, created_at) VALUES (?, ?, ?, ?)",
                     (token, kind, ref_id, clock.now_ist().isoformat()))
    return token


def link_url(base_url: str, token: str) -> str:
    return f"{base_url}/l/{token}"


def hour_text(h: int) -> str:
    return f"{h % 12 or 12} {'am' if h < 12 else 'pm'}"


def slot_english(slot_id: str) -> str:
    """'2026-11-07_evening' -> 'Saturday, 7 November, 4 pm to 7 pm'."""
    day_s, _, period = slot_id.partition("_")
    try:
        day = date.fromisoformat(day_s)
        p = PERIODS[period]
    except (ValueError, KeyError):
        return slot_id
    return f"{day.strftime('%A')}, {day.day} {day.strftime('%B')}, {hour_text(p['start'])} to {hour_text(p['end'])}"


def amount_english(rupees: int) -> str:
    return "Rs " + amount_text(rupees).replace(" rupaye", "")


# ---------------------------------------------------------------- layout

def _html(title: str, greeting: str, rows: list[tuple[str, str]], paragraphs: list[str],
          buttons: list[tuple[str, str]]) -> str:
    table = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#6b7280">{escape(k)}</td>'
        f'<td style="padding:6px 0;font-weight:600">{escape(v)}</td></tr>' for k, v in rows)
    paras = "".join(f'<p style="margin:0 0 14px">{escape(p)}</p>' for p in paragraphs)
    btns = "".join(
        f'<p style="margin:0 0 12px"><a href="{escape(url)}" style="display:inline-block;background:#111827;'
        f'color:#ffffff;text-decoration:none;padding:11px 18px;border-radius:8px;font-weight:600">'
        f'{escape(label)}</a></p>' for label, url in buttons)
    return f"""<!doctype html>
<html><body style="margin:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;color:#111827">
<div style="max-width:560px;margin:0 auto;padding:24px 16px">
  <div style="background:#ffffff;border-radius:12px;padding:28px">
    <p style="margin:0 0 4px;font-size:13px;letter-spacing:.08em;color:#6b7280">STYLEKART SUPPORT</p>
    <h1 style="margin:0 0 18px;font-size:22px">{escape(title)}</h1>
    <p style="margin:0 0 14px">{escape(greeting)}</p>
    {f'<table style="border-collapse:collapse;margin:0 0 18px;font-size:15px">{table}</table>' if rows else ''}
    {paras}{btns}
  </div>
  <p style="font-size:12px;color:#6b7280;margin:16px 4px 0">{escape(DEMO_NOTE)}</p>
</div></body></html>"""


def _text(title: str, greeting: str, rows: list[tuple[str, str]], paragraphs: list[str],
          buttons: list[tuple[str, str]]) -> str:
    lines = [title, "", greeting, ""]
    lines += [f"{k}: {v}" for k, v in rows]
    if rows:
        lines.append("")
    for p in paragraphs:
        lines += [p, ""]
    for label, url in buttons:
        lines += [f"{label}: {url}", ""]
    lines += ["--", DEMO_NOTE]
    return "\n".join(lines)


def _build(title, greeting, rows, paragraphs, buttons) -> tuple[str, str]:
    return (_html(title, greeting, rows, paragraphs, buttons),
            _text(title, greeting, rows, paragraphs, buttons))


# ---------------------------------------------------------------- emails

def return_booked(ret: dict, item: dict, base_url: str) -> tuple[str, str, str]:
    """Subject, HTML and text for a new return. COD returns also get a bank-details link."""
    cod = item["payment_mode"] == "cod"
    buttons = [("View your return", link_url(base_url, create_link("return_status", ret["id"])))]
    paragraphs = []
    if cod:
        buttons.insert(0, ("Add bank details for your refund",
                           link_url(base_url, create_link("bank_details", ret["id"]))))
        paragraphs.append("This was a cash on delivery order, so we need your bank details to send the refund. "
                          "The refund reaches your account 5 to 7 days after we receive them.")
    else:
        paragraphs.append("The refund goes back to your original payment method 5 to 7 days after pickup.")
    rows = [("Return ID", ret["id"]), ("Item", item["name"]),
            ("Pickup", slot_english(ret["slot_id"])), ("Address", item["address_short"]),
            ("Refund amount", amount_english(ret["refund_amount"]))]
    subject = f"Your StyleKart return {ret['id']} is booked"
    return (subject, *_build(f"Return {ret['id']} is booked", f"Hi {item['first_name']},", rows,
                             ["Please keep the item packed with its tags for the pickup.", *paragraphs],
                             buttons))


def quality_ticket(ticket_id: str, item: dict, issue: str, base_url: str) -> tuple[str, str, str]:
    url = link_url(base_url, create_link("photo_upload", ticket_id))
    subject = f"Upload photos for your StyleKart complaint {ticket_id}"
    return (subject, *_build(f"Complaint {ticket_id} is registered", f"Hi {item['first_name']},",
                             [("Ticket", ticket_id), ("Item", item["name"]), ("Issue", issue)],
                             ["Please upload a few clear photos of the item. "
                              "Our team will contact you within 48 hours."],
                             [("Upload photos", url)]))


def callback_booked(callback_id: str, first_name: str, topic: str, when: str) -> tuple[str, str, str]:
    subject = f"StyleKart will call you back ({callback_id})"
    return (subject, *_build("We'll call you back", f"Hi {first_name},",
                             [("Reference", callback_id), ("About", topic), ("When", when)],
                             ["Our support team will call you on your registered mobile number."], []))
