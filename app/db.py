"""SQLite storage. Six business tables plus an events log used to score evals."""

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
"""


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
        _conn.executescript(SCHEMA)
    return _conn


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
