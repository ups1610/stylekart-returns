"""Email notifications, the pages their links open, and the old-schema rebuild."""

import re
import sqlite3

import httpx
import pytest

from app import db, mailer
from app.seed import reset_data

UPENDRA = "+917505062257"
RISHABH = "+919149262211"
ANANT = "+919953260051"
JAI = "+919166017069"
NEHA = "+919000000009"
BASE = "https://returns.test"


class FakeResponse:
    def __init__(self, status_code=201, text='{"messageId":"<x@brevo>"}'):
        self.status_code = status_code
        self.text = text


@pytest.fixture()
def brevo(monkeypatch):
    """Brevo configured; httpx.post is replaced, and every request is captured."""
    monkeypatch.setenv("BREVO_API_KEY", "test-brevo-key")
    monkeypatch.setenv("MAIL_FROM", "support@stylekart.test")
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE)
    calls = []
    state = {"response": FakeResponse(), "raise": None}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if state["raise"]:
            raise state["raise"]
        return state["response"]

    monkeypatch.setattr(httpx, "post", fake_post)
    return {"calls": calls, "state": state}


@pytest.fixture()
def no_network(monkeypatch):
    def fail(*_a, **_k):
        raise AssertionError("must not call Brevo")
    monkeypatch.setattr(httpx, "post", fail)


def slot(client, order_id):
    return client.get(f"/pickup-slots/{order_id}").json()["slots"][0]["slot_id"]


def book(client, order_id, item_id):
    return client.post("/returns", json={"order_id": order_id, "item_id": item_id,
                                         "reason": "size issue", "slot_id": slot(client, order_id)})


def emails(client, phone):
    return client.get(f"/admin/state/{phone}").json()["emails"]


def links_in(html):
    return re.findall(r'href="([^"]+/l/[^"]+)"', html)


def path_of(url):
    return url.replace(BASE, "")


# ---------------------------------------------------------------- masking

def test_mask_email():
    assert mailer.mask_email("pratapsinghupendra96@gmail.com") == "pra****@gmail.com"
    assert mailer.mask_email("jai@example.com") == "j****@example.com"
    assert mailer.mask_email("") == "****"


def test_lookup_returns_masked_email_only(client):
    r = client.get(f"/customers/by-phone/{UPENDRA}")
    assert r.json()["email_masked"] == "pra****@gmail.com"
    assert "pratapsinghupendra96" not in r.text


def test_admin_state_masks_email(client):
    r = client.get(f"/admin/state/{RISHABH}")
    assert r.json()["customer"]["email"] == "ris****@gmail.com"
    assert "rishabhthakur046" not in r.text


def test_seed_emails(client):
    assert client.get("/customers/by-phone/9000000002").json()["email_masked"] == "roh****@example.com"
    jai = client.get(f"/customers/by-phone/{JAI}").json()
    assert jai["full_name"] == "Jai Khandelwal" and jai["email_masked"] == "jai****@gmail.com"


def test_jai_last_day_and_personalised_item(client):
    def elig(order, item):
        return client.post("/returns/eligibility", json={"order_id": order, "item_id": item}).json()
    assert elig("SK1023", "SK1023-1")["days_left"] == 0
    assert elig("SK1024", "SK1024-1")["reason_code"] == "NON_RETURNABLE"


# ---------------------------------------------------------------- send / log rules

def test_without_api_key_emails_are_only_logged(client, no_network):
    assert book(client, "SK1016", "SK1016-1").status_code == 200
    [e] = emails(client, UPENDRA)
    assert e["status"] == "logged" and e["kind"] == "return_booked"
    assert e["to_masked"] == "pra****@gmail.com"


def test_example_com_is_never_sent_even_with_key(client, brevo):
    book(client, "SK1001", "SK1001-1")
    assert brevo["calls"] == []
    assert emails(client, "+919000000001")[0]["status"] == "logged"


def test_real_address_is_sent_through_brevo(client, brevo):
    body = book(client, "SK1016", "SK1016-1").json()
    [call] = brevo["calls"]
    assert call["url"] == "https://api.brevo.com/v3/smtp/email"
    assert call["headers"]["api-key"] == "test-brevo-key" and call["timeout"] == 10
    msg = call["json"]
    assert msg["to"] == [{"email": "pratapsinghupendra96@gmail.com", "name": "Upendra Singh"}]
    assert msg["sender"] == {"name": "StyleKart Support", "email": "support@stylekart.test"}
    assert body["return_id"] in msg["subject"]
    assert "demo brand" in msg["htmlContent"] and "demo brand" in msg["textContent"]
    assert links_in(msg["htmlContent"])[0].startswith(f"{BASE}/l/")
    assert emails(client, UPENDRA)[0]["status"] == "sent"


def test_brevo_error_is_recorded_and_api_still_succeeds(client, brevo):
    brevo["state"]["response"] = FakeResponse(401, '{"message":"Key not found"}')
    r = book(client, "SK1016", "SK1016-1")
    assert r.status_code == 200 and r.json()["return_id"]
    e = emails(client, UPENDRA)[0]
    assert e["status"] == "failed" and "401" in e["error"]


def test_network_timeout_is_recorded_and_api_still_succeeds(client, brevo):
    brevo["state"]["raise"] = httpx.ConnectTimeout("timed out")
    r = client.post("/quality-tickets", json={"order_id": "SK1017", "item_id": "SK1017-1",
                                              "issue": "stitching came off"})
    assert r.status_code == 200
    e = emails(client, UPENDRA)[0]
    assert e["status"] == "failed" and "ConnectTimeout" in e["error"]


def test_missing_sender_is_recorded_as_failed(client, brevo, monkeypatch):
    monkeypatch.delenv("MAIL_FROM")
    book(client, "SK1016", "SK1016-1")
    assert brevo["calls"] == []
    assert emails(client, UPENDRA)[0]["error"] == "MAIL_FROM is not set"


def test_repeat_booking_sends_only_one_email(client, brevo):
    book(client, "SK1016", "SK1016-1")
    book(client, "SK1016", "SK1016-1")
    assert len(brevo["calls"]) == 1 and len(emails(client, UPENDRA)) == 1


def test_say_lines_mention_email_not_sms(client):
    cod = book(client, "SK1019", "SK1019-1").json()
    assert cod["email_masked"] == "ana****@gmail.com"
    assert cod["cod_link_emailed"] is True and "email" in cod["refund_eta_text"]
    ticket = client.post("/quality-tickets", json={"order_id": "SK1017", "item_id": "SK1017-1",
                                                   "issue": "torn"}).json()
    assert ticket["photo_link_emailed"] is True
    assert ticket["email_masked"] == "pra****@gmail.com"
    assert "photo_link_sms_sent" not in ticket and "cod_sms_sent" not in cod
    assert "SMS" not in cod["refund_eta_text"] + ticket["say"]


def test_callback_emails_known_customer_only(client):
    known = client.post("/callbacks", json={"phone": RISHABH, "topic": "pickup missed"}).json()
    assert known["confirmation_emailed"] is True and known["email_masked"] == "ris****@gmail.com"
    assert emails(client, RISHABH)[0]["kind"] == "callback"
    unknown = client.post("/callbacks", json={"phone": "9999999999", "topic": "query"}).json()
    assert unknown["confirmation_emailed"] is False and unknown["email_masked"] is None


# ---------------------------------------------------------------- link pages

def test_return_status_link(client, brevo):
    body = book(client, "SK1021", "SK1021-2").json()
    [status_url] = links_in(brevo["calls"][0]["json"]["htmlContent"])
    page = client.get(path_of(status_url))
    assert page.status_code == 200 and body["return_id"] in page.text and "olive henley" in page.text


def test_cod_bank_details_link(client, brevo):
    book(client, "SK1019", "SK1019-1")
    assert brevo["calls"][0]["json"]["to"][0]["email"] == "anantjakhmola9@gmail.com"
    bank_url, status_url = links_in(brevo["calls"][0]["json"]["htmlContent"])
    path = path_of(bank_url)

    assert "Submit bank details" in client.get(path).text
    bad = client.post(f"{path}/bank", data={"account_holder": "Anant J", "account_number": "12345678901",
                                            "ifsc": "BADCODE"})
    assert bad.status_code == 422 and "IFSC" in bad.text

    good = client.post(f"{path}/bank", data={"account_holder": "Anant Jakhmola",
                                             "account_number": "1234 5678 9012", "ifsc": "hdfc0001234"})
    assert good.status_code == 200 and "ending 9012" in good.text and "123456789012" not in good.text
    stored = dict(db.get_conn().execute("SELECT * FROM bank_details").fetchone())
    assert stored["account_last4"] == "9012" and stored["ifsc"] == "HDFC0001234"
    assert "account ending 9012" in client.get(path_of(status_url)).text


def test_photo_upload_link(client, brevo):
    client.post("/quality-tickets", json={"order_id": "SK1022", "item_id": "SK1022-1", "issue": "zip broken"})
    [url] = links_in(brevo["calls"][0]["json"]["htmlContent"])
    path = path_of(url)
    assert "Upload photos" in client.get(path).text

    not_image = client.post(f"{path}/photo", files={"photo": ("notes.txt", b"hello", "text/plain")})
    assert not_image.status_code == 422

    ok = client.post(f"{path}/photo", files={"photo": ("zip.jpg", b"\xff\xd8\xff" + b"0" * 100, "image/jpeg")})
    assert ok.status_code == 200 and "1 photo received" in ok.text
    row = dict(db.get_conn().execute("SELECT * FROM uploads").fetchone())
    assert row["filename"] == "zip.jpg" and row["size_bytes"] == 103


def test_unknown_or_wrong_kind_link_is_404(client):
    assert client.get("/l/not-a-token").status_code == 404
    assert client.post("/l/not-a-token/bank", data={}).status_code == 404


def test_reset_clears_emails_and_links(client):
    book(client, "SK1016", "SK1016-1")
    client.post("/admin/reset")
    assert emails(client, UPENDRA) == []
    assert db.get_conn().execute("SELECT COUNT(*) FROM links").fetchone()[0] == 0


# ---------------------------------------------------------------- old schema

def test_old_schema_database_is_rebuilt(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE customers (id TEXT PRIMARY KEY, first_name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE,
                                address_short TEXT NOT NULL, pincode TEXT NOT NULL);
        INSERT INTO customers VALUES ('C01', 'Old', '+910000000000', 'x', '000000');
        CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT, placed_on TEXT, payment_mode TEXT);
    """)
    old.commit()
    old.close()

    db.reset_connection(path)
    conn = db.get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(customers)")}
    assert "email" in cols
    assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0  # dropped; startup reseeds
    reset_data()
    assert conn.execute("SELECT email FROM customers WHERE id = 'C13'").fetchone()[0] == \
        "pratapsinghupendra96@gmail.com"


def test_database_without_devanagari_column_is_rebuilt(tmp_path):
    path = str(tmp_path / "v2.db")
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE customers (id TEXT PRIMARY KEY, first_name TEXT NOT NULL, full_name TEXT NOT NULL,
                                phone TEXT NOT NULL UNIQUE, email TEXT NOT NULL,
                                address_short TEXT NOT NULL, pincode TEXT NOT NULL);
        INSERT INTO customers VALUES ('C01', 'Old', 'Old Name', '+910000000000', 'o@example.com', 'x', '0');
    """)
    old.commit()
    old.close()

    db.reset_connection(path)
    conn = db.get_conn()
    assert "first_name_hi" in {r["name"] for r in conn.execute("PRAGMA table_info(customers)")}
    reset_data()
    assert conn.execute("SELECT first_name_hi FROM customers WHERE id = 'C13'").fetchone()[0] == "उपेंद्र"
