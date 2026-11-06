"""Email delivery through the Brevo HTTP API.

Rules:
  - No BREVO_API_KEY, or a recipient @example.com (dummy customers): nothing is sent,
    the email is only recorded with status "logged".
  - Every email is recorded in the `emails` table as sent | logged | failed.
  - `send_email` never raises. It is meant to run in a FastAPI BackgroundTask, so a slow
    or failing mail provider can never break or delay the API response the agent waits for.

Settings are read on every call, so changing the environment needs no restart in tests.
"""

import os

import httpx

from . import clock
from .db import tx

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
TIMEOUT_SECONDS = 10
DUMMY_DOMAIN = "@example.com"


def public_base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "https://stylekart-returns.onrender.com").rstrip("/")


def mask_email(email: str) -> str:
    """'pratapsinghupendra96@gmail.com' -> 'pra****@gmail.com'."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "****"
    keep = 3 if len(local) > 3 else 1
    return f"{local[:keep]}****@{domain}"


def record(customer_id: str | None, to: str, subject: str, kind: str,
           status: str, error: str | None = None) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO emails (customer_id, to_masked, subject, kind, status, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (customer_id, mask_email(to), subject, kind, status, error, clock.now_ist().isoformat()),
        )


def _deliver(to: str, to_name: str, subject: str, html: str, text: str) -> str | None:
    """Send one email. Returns None on success, or a short error message."""
    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    sender = os.environ.get("MAIL_FROM", "").strip()
    if not sender:
        return "MAIL_FROM is not set"
    payload = {
        "sender": {"name": os.environ.get("MAIL_FROM_NAME", "StyleKart Support"), "email": sender},
        "to": [{"email": to, "name": to_name}],
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }
    resp = httpx.post(BREVO_URL, json=payload, timeout=TIMEOUT_SECONDS,
                      headers={"api-key": api_key, "accept": "application/json"})
    if resp.status_code >= 300:
        return f"Brevo HTTP {resp.status_code}: {resp.text[:200]}"
    return None


def send_email(customer_id: str | None, to: str, to_name: str, subject: str,
               html: str, text: str, kind: str) -> str:
    """Send (or just log) an email and record it. Returns the recorded status."""
    try:
        if not os.environ.get("BREVO_API_KEY", "").strip() or to.lower().endswith(DUMMY_DOMAIN):
            status, error = "logged", None
        else:
            error = _deliver(to, to_name, subject, html, text)
            status = "failed" if error else "sent"
    except Exception as exc:  # network errors, timeouts, anything: never propagate
        status, error = "failed", f"{type(exc).__name__}: {exc}"[:300]
    try:
        record(customer_id, to, subject, kind, status, error)
    except Exception:
        pass
    return status
