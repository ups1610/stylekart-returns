"""SQLite storage: business tables, an events log used to score evals, and an email log."""

import os
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "stylekart.db")

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id            TEXT PRIMARY KEY,
    first_name    TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    phone         TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL,
    address_short TEXT NOT NULL,
    pincode       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id           TEXT PRIMARY KEY,
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    placed_on    TEXT NOT NULL,
    payment_mode TEXT NOT NULL CHECK (payment_mode IN ('prepaid', 'cod')),
    behaviour    TEXT              -- test hook: 'eligibility_500' or 'slow_create'
);

CREATE TABLE IF NOT EXISTS items (
    id           TEXT PRIMARY KEY,
    order_id     TEXT NOT NULL REFERENCES orders(id),
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,
    price        INTEGER NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('delivered', 'in_transit')),
    delivered_on TEXT
);

CREATE TABLE IF NOT EXISTS returns (
    id           TEXT PRIMARY KEY,
    order_id     TEXT NOT NULL,
    item_id      TEXT NOT NULL UNIQUE,  -- one return per item, enforced by the database
    reason       TEXT NOT NULL,
    slot_id      TEXT NOT NULL,
    status       TEXT NOT NULL,         -- pickup_scheduled | picked_up | refunded
    refund_amount INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('quality', 'callback')),
    phone      TEXT,
    order_id   TEXT,
    item_id    TEXT,
    detail     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    endpoint   TEXT NOT NULL,
    request    TEXT,
    status     INTEGER NOT NULL,
    response   TEXT
);

CREATE TABLE IF NOT EXISTS emails (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT,
    to_masked   TEXT NOT NULL,
    subject     TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- return_booked | quality_ticket | callback
    status      TEXT NOT NULL CHECK (status IN ('sent', 'logged', 'failed')),
    error       TEXT,
    created_at  TEXT NOT NULL
);

-- Links sent in emails. The token is the only key, so links can't be guessed.
CREATE TABLE IF NOT EXISTS links (
    token      TEXT PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('return_status', 'bank_details', 'photo_upload')),
    ref_id     TEXT NOT NULL,           -- return id or ticket id
    created_at TEXT NOT NULL,
    used_at    TEXT
);

-- Bank details for COD refunds. Only the last 4 digits of the account are kept.
CREATE TABLE IF NOT EXISTS bank_details (
    return_id      TEXT PRIMARY KEY,
    account_holder TEXT NOT NULL,
    account_last4  TEXT NOT NULL,
    ifsc           TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

-- Photos for quality tickets. Only metadata is stored; the file itself is discarded.
CREATE TABLE IF NOT EXISTS uploads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id    TEXT NOT NULL,
    filename     TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);
"""

ALL_TABLES = ("uploads", "bank_details", "links", "emails", "events",
              "tickets", "returns", "items", "orders", "customers")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = connect()
        _drop_if_outdated(_conn)
        _conn.executescript(SCHEMA)
    return _conn


def _drop_if_outdated(conn: sqlite3.Connection) -> None:
    """An older database file (no customers.email) is dropped; the app then reseeds it.

    Everything in here is demo data, so rebuilding is safe and avoids migrations.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(customers)")}
    if cols and "email" not in cols:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in ALL_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")


def reset_connection(path: str | None = None) -> None:
    """Used by tests to point at a fresh database file."""
    global _conn, DB_PATH
    if _conn is not None:
        _conn.close()
    _conn = None
    if path is not None:
        DB_PATH = path


@contextmanager
def tx():
    """Serialised transaction: commit on success, roll back on error."""
    with _lock:
        conn = get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
