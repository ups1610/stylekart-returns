"""The pages that emailed links open: /l/{token}.

  return_status  read-only view of a return
  bank_details   form for COD refunds; only the last 4 account digits are stored
  photo_upload   image upload for a quality ticket; only file metadata is stored

Tokens are random and unguessable, so the pages need no login.
"""

import re
from html import escape

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import HTMLResponse

from . import clock
from .db import get_conn, tx
from .notify import DEMO_NOTE, amount_english, slot_english

router = APIRouter(include_in_schema=False)

IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTOS = 5
STATUS_TEXT = {"pickup_scheduled": "Pickup scheduled", "picked_up": "Picked up", "refunded": "Refunded"}


def page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · StyleKart</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f3f4f6; --card:#fff; --fg:#111827; --muted:#6b7280; --line:#e5e7eb;
           --btn:#111827; --btn-fg:#fff; --err:#b91c1c; --ok:#047857; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#0b0f19; --card:#161b26; --fg:#f3f4f6; --muted:#9ca3af;
           --line:#2a3140; --btn:#f3f4f6; --btn-fg:#111827; --err:#f87171; --ok:#34d399; }} }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  main {{ max-width:520px; margin:0 auto; padding:24px 16px; }}
  .card {{ background:var(--card); border-radius:12px; padding:24px; }}
  .eyebrow {{ margin:0 0 4px; font-size:13px; letter-spacing:.08em; color:var(--muted); }}
  h1 {{ margin:0 0 16px; font-size:22px; }}
  dl {{ display:grid; grid-template-columns:auto 1fr; gap:8px 16px; margin:0 0 16px; }}
  dt {{ color:var(--muted); }} dd {{ margin:0; font-weight:600; }}
  label {{ display:block; margin:0 0 14px; font-weight:600; }}
  input {{ display:block; width:100%; margin-top:6px; padding:10px; font:inherit; color:inherit;
           background:transparent; border:1px solid var(--line); border-radius:8px; }}
  button {{ background:var(--btn); color:var(--btn-fg); border:0; border-radius:8px; padding:11px 18px;
            font:inherit; font-weight:600; cursor:pointer; }}
  .err {{ color:var(--err); }} .ok {{ color:var(--ok); font-weight:600; }}
  .note {{ font-size:13px; color:var(--muted); margin:16px 4px 0; }}
</style></head>
<body><main><div class="card"><p class="eyebrow">STYLEKART SUPPORT</p><h1>{escape(title)}</h1>{body}</div>
<p class="note">{escape(DEMO_NOTE)}</p></main></body></html>"""
    return HTMLResponse(html, status_code=status)


def not_found() -> HTMLResponse:
    return page("Link not found", "<p>This link is invalid or has expired.</p>", 404)


def load_link(token: str, kind: str | None = None) -> dict | None:
    row = get_conn().execute("SELECT * FROM links WHERE token = ?", (token,)).fetchone()
    if row is None or (kind and row["kind"] != kind):
        return None
    return dict(row)


def mark_used(token: str) -> None:
    with tx() as conn:
        conn.execute("UPDATE links SET used_at = COALESCE(used_at, ?) WHERE token = ?",
                     (clock.now_ist().isoformat(), token))


def details(rows: list[tuple[str, str]]) -> str:
    return "<dl>" + "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in rows) + "</dl>"


def load_return(return_id: str) -> dict | None:
    row = get_conn().execute(
        """SELECT r.*, i.name AS item_name, o.payment_mode, c.address_short
           FROM returns r JOIN items i ON i.id = r.item_id JOIN orders o ON o.id = r.order_id
           JOIN customers c ON c.id = o.customer_id WHERE r.id = ?""", (return_id,)).fetchone()
    return dict(row) if row else None


def bank_on_file(return_id: str) -> dict | None:
    row = get_conn().execute("SELECT * FROM bank_details WHERE return_id = ?", (return_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- views

def return_status_view(return_id: str) -> HTMLResponse:
    ret = load_return(return_id)
    if ret is None:
        return not_found()
    rows = [("Return ID", ret["id"]), ("Item", ret["item_name"]),
            ("Status", STATUS_TEXT.get(ret["status"], ret["status"])),
            ("Pickup", slot_english(ret["slot_id"])), ("Address", ret["address_short"]),
            ("Refund", amount_english(ret["refund_amount"]))]
    if ret["payment_mode"] == "cod":
        bank = bank_on_file(ret["id"])
        rows.append(("Bank details", f"Received (account ending {bank['account_last4']})" if bank
                     else "Not received yet. Use the link in your email."))
    return page(f"Return {ret['id']}", details(rows))


def bank_form(token: str, ret: dict, error: str = "", values: dict | None = None) -> HTMLResponse:
    v = values or {}
    err = f'<p class="err" role="alert">{escape(error)}</p>' if error else ""
    body = f"""<p>Return <strong>{escape(ret['id'])}</strong> for {escape(ret['item_name'])}:
refund of {escape(amount_english(ret['refund_amount']))}. Enter the account the refund should go to.</p>{err}
<form method="post" action="/l/{escape(token)}/bank">
  <label>Account holder name<input name="account_holder" required minlength="2" maxlength="80"
         autocomplete="name" value="{escape(v.get('account_holder', ''))}"></label>
  <label>Account number<input name="account_number" required inputmode="numeric" pattern="[0-9]{{9,18}}"
         autocomplete="off" value=""></label>
  <label>IFSC code<input name="ifsc" required maxlength="11" autocapitalize="characters"
         placeholder="e.g. HDFC0001234" value="{escape(v.get('ifsc', ''))}"></label>
  <button type="submit">Submit bank details</button>
</form>
<p class="note">Demo only: please don't enter real bank details. Only the last 4 digits are kept.</p>"""
    return page("Bank details for your refund", body, 422 if error else 200)


def bank_view(token: str, return_id: str) -> HTMLResponse:
    ret = load_return(return_id)
    if ret is None:
        return not_found()
    bank = bank_on_file(return_id)
    if bank:
        return page("Bank details received",
                    f'<p class="ok">Thanks, we have your bank details for return {escape(return_id)}.</p>'
                    + details([("Account holder", bank["account_holder"]),
                               ("Account", f"ending {bank['account_last4']}"), ("IFSC", bank["ifsc"])])
                    + "<p>The refund reaches your account in 5 to 7 days.</p>")
    return bank_form(token, ret)


def photo_form(token: str, ticket_id: str, error: str = "", status: int = 200) -> HTMLResponse:
    count = get_conn().execute("SELECT COUNT(*) FROM uploads WHERE ticket_id = ?", (ticket_id,)).fetchone()[0]
    err = f'<p class="err" role="alert">{escape(error)}</p>' if error else ""
    done = f'<p class="ok">{count} photo{"s" if count != 1 else ""} received.</p>' if count else ""
    form = "" if count >= MAX_PHOTOS else f"""
<form method="post" action="/l/{escape(token)}/photo" enctype="multipart/form-data">
  <label>Photo of the item<input type="file" name="photo" accept="image/*" required></label>
  <button type="submit">Upload</button>
</form>"""
    body = (f"<p>Complaint <strong>{escape(ticket_id)}</strong>. Upload up to {MAX_PHOTOS} clear photos "
            f"of the item (images up to 5 MB each).</p>{done}{err}{form}")
    return page("Upload photos", body, status)


# ---------------------------------------------------------------- routes

@router.get("/l/{token}", response_class=HTMLResponse)
def open_link(token: str):
    link = load_link(token)
    if link is None:
        return not_found()
    if link["kind"] == "return_status":
        return return_status_view(link["ref_id"])
    if link["kind"] == "bank_details":
        return bank_view(token, link["ref_id"])
    return photo_form(token, link["ref_id"])


@router.post("/l/{token}/bank", response_class=HTMLResponse)
def submit_bank(token: str, account_holder: str = Form(""), account_number: str = Form(""),
                ifsc: str = Form("")):
    link = load_link(token, "bank_details")
    ret = load_return(link["ref_id"]) if link else None
    if ret is None:
        return not_found()
    if bank_on_file(ret["id"]):
        return bank_view(token, ret["id"])

    holder = " ".join(account_holder.split())
    number = re.sub(r"\s", "", account_number)
    code = ifsc.strip().upper()
    error = ""
    if not 2 <= len(holder) <= 80:
        error = "Please enter the account holder's name."
    elif not number.isdigit() or not 9 <= len(number) <= 18:
        error = "The account number should be 9 to 18 digits."
    elif not IFSC_RE.match(code):
        error = "The IFSC code should look like HDFC0001234 (11 characters)."
    if error:
        return bank_form(token, ret, error, {"account_holder": holder, "ifsc": code})

    with tx() as conn:
        conn.execute("INSERT OR IGNORE INTO bank_details VALUES (?, ?, ?, ?, ?)",
                     (ret["id"], holder, number[-4:], code, clock.now_ist().isoformat()))
    mark_used(token)
    return bank_view(token, ret["id"])


@router.post("/l/{token}/photo", response_class=HTMLResponse)
async def submit_photo(token: str, photo: UploadFile | None = File(None)):
    link = load_link(token, "photo_upload")
    if link is None:
        return not_found()
    ticket_id = link["ref_id"]
    count = get_conn().execute("SELECT COUNT(*) FROM uploads WHERE ticket_id = ?", (ticket_id,)).fetchone()[0]
    if count >= MAX_PHOTOS:
        return photo_form(token, ticket_id, f"You have already uploaded {MAX_PHOTOS} photos.", 422)
    if photo is None or not photo.filename:
        return photo_form(token, ticket_id, "Please choose a photo to upload.", 422)
    if not (photo.content_type or "").startswith("image/"):
        return photo_form(token, ticket_id, "Only image files can be uploaded.", 422)

    size = 0
    while chunk := await photo.read(64 * 1024):
        size += len(chunk)
        if size > MAX_PHOTO_BYTES:
            return photo_form(token, ticket_id, "That photo is larger than 5 MB.", 422)
    if size == 0:
        return photo_form(token, ticket_id, "That file is empty.", 422)

    with tx() as conn:
        conn.execute("INSERT INTO uploads (ticket_id, filename, content_type, size_bytes, created_at) "
                     "VALUES (?, ?, ?, ?, ?)",
                     (ticket_id, photo.filename[:200], photo.content_type, size, clock.now_ist().isoformat()))
    mark_used(token)
    return photo_form(token, ticket_id)
