"""Seed data: fictional customers, each built to trigger one test scenario.

Delivery dates are set relative to *today* (India time) every time the data is
reset, so "delivered 14 days ago" is always the last eligible day, whatever
day you run the evals.

Every customer has an email. Dummy customers get <firstname>@example.com, which the
mailer only logs and never sends. Real addresses are listed in REAL_EMAILS.

Set DEMO_PHONE to your own number so a real call finds Ananya's account.
Any other seed customer can be pointed at your number with POST /admin/map-phone.
"""

import os
from datetime import timedelta

from . import clock
from .db import ALL_TABLES, tx
from .phones import normalize_phone

DEMO_PHONE = normalize_phone(os.environ.get("DEMO_PHONE", "+919000000001"))

# (customer_id, full_name, phone, address_short, pincode, orders)
# each order: (order_id, payment_mode, behaviour, [items])
# each item:  (item_id_suffix, name, category, price, status, delivered_days_ago or None)
CUSTOMERS = [
    ("C01", "Ananya Rao", DEMO_PHONE, "Indiranagar, Bengaluru", "560038", [
        ("SK1001", "prepaid", None, [
            ("1", "blue cotton kurta", "ethnicwear", 1299, "delivered", 3),
        ]),
    ]),
    ("C02", "Rohan Mehta", "+919000000002", "Koramangala, Bengaluru", "560034", [
        ("SK1002", "prepaid", None, [("1", "white running sneakers", "footwear", 3499, "delivered", 2)]),
        ("SK1003", "prepaid", None, [("1", "black slim-fit jeans", "bottomwear", 1899, "delivered", 6)]),
        ("SK1004", "prepaid", None, [("1", "checked casual shirt", "topwear", 1199, "delivered", 10)]),
        # older order, already returned and refunded: used for refund-status questions
        ("SK1005", "prepaid", None, [("1", "grey hoodie", "topwear", 1599, "delivered", 30)]),
    ]),
    ("C03", "Priya Nair", "+919000000003", "Andheri West, Mumbai", "400053", [
        ("SK1006", "prepaid", None, [
            ("1", "floral crop top", "topwear", 899, "delivered", 5),
            ("2", "high-waist mom jeans", "bottomwear", 1799, "delivered", 5),
        ]),
    ]),
    ("C04", "Meera Das", "+919000000004", "Salt Lake, Kolkata", "700091", [
        ("SK1007", "prepaid", None, [("1", "maroon party dress", "westernwear", 2499, "delivered", 17)]),
    ]),
    ("C05", "Arjun Kulkarni", "+919000000005", "Baner, Pune", "411045", [
        ("SK1008", "prepaid", None, [("1", "olive bomber jacket", "outerwear", 2999, "delivered", 14)]),
    ]),
    ("C06", "Kabir Malhotra", "+919000000006", "Sector 62, Noida", "201309", [
        ("SK1009", "prepaid", None, [("1", "cotton innerwear pack of 3", "innerwear", 699, "delivered", 2)]),
    ]),
    ("C07", "Isha Reddy", "+919000000007", "Jubilee Hills, Hyderabad", "500033", [
        ("SK1010", "prepaid", None, [("1", "silk banarasi saree", "ethnicwear", 4999, "in_transit", None)]),
    ]),
    ("C08", "Dev Arora", "+919000000008", "Vasant Kunj, Delhi", "110070", [
        ("SK1011", "prepaid", None, [("1", "linen formal shirt", "topwear", 1499, "delivered", 4)]),
    ]),
    ("C09", "Neha Srivastava", "+919000000009", "Gomti Nagar, Lucknow", "226010", [
        ("SK1012", "cod", None, [("1", "printed anarkali kurta", "ethnicwear", 1699, "delivered", 4)]),
    ]),
    ("C10", "Sahil Wangchuk", "+919000000010", "Remote Area, Ladakh", "194101", [
        ("SK1013", "prepaid", None, [("1", "relaxed fit jeans", "bottomwear", 1599, "delivered", 3)]),
    ]),
    ("C11", "Tanya Sharma", "+919000000011", "Civil Lines, Jaipur", "302006", [
        ("SK1014", "prepaid", "eligibility_500", [("1", "embroidered dupatta", "ethnicwear", 799, "delivered", 3)]),
    ]),
    ("C12", "Vikram Iyer", "+919000000012", "Anna Nagar, Chennai", "600040", [
        ("SK1015", "prepaid", "slow_create", [("1", "navy polo t-shirt", "topwear", 999, "delivered", 3)]),
    ]),

    # ---- Real phone numbers, for live calls. Each one exercises a different path.
    # Upendra: several orders to choose from; one returnable, one expired, one non-returnable.
    ("C13", "Upendra Singh", "+917505062257", "Sector 21, Gurugram", "122016", [
        ("SK1016", "prepaid", None, [("1", "white leather sneakers", "footwear", 3299, "delivered", 2)]),
        ("SK1017", "prepaid", None, [("1", "blue denim jacket", "outerwear", 2799, "delivered", 19)]),
        ("SK1018", "prepaid", None, [("1", "cotton boxer briefs pack of 2", "innerwear", 599, "delivered", 5)]),
    ]),
    # Anant: cash-on-delivery kurta (refund needs bank details via an emailed link), plus a shirt in transit.
    ("C14", "Anant Jakhmola", "+919953260051", "Rajpur Road, Dehradun", "248001", [
        ("SK1019", "cod", None, [("1", "beige linen kurta", "ethnicwear", 1499, "delivered", 4)]),
        ("SK1020", "prepaid", None, [("1", "striped oxford shirt", "topwear", 1399, "in_transit", None)]),
    ]),
    # Rishabh: one order with two items (return just one), plus an old return already refunded.
    ("C15", "Rishabh Thakur", "+919149262211", "Gandhi Nagar, Jammu", "180004", [
        ("SK1021", "prepaid", None, [
            ("1", "black chino trousers", "bottomwear", 1699, "delivered", 6),
            ("2", "olive henley t-shirt", "topwear", 799, "delivered", 6),
        ]),
        ("SK1022", "prepaid", None, [("1", "navy puffer jacket", "outerwear", 3999, "delivered", 35)]),
    ]),
    # Jai: last day of the return window, plus a personalised (non-returnable) item for a quality ticket.
    ("C16", "Jai Khandelwal", "+919166017069", "Malviya Nagar, Jaipur", "302017", [
        ("SK1023", "prepaid", None, [("1", "tan suede chelsea boots", "footwear", 4299, "delivered", 14)]),
        ("SK1024", "prepaid", None, [("1", "name-printed cotton t-shirt", "personalised", 899, "delivered", 3)]),
    ]),
]

# Real inboxes. Anyone not listed gets <firstname>@example.com, which is never sent.
REAL_EMAILS = {
    "C13": "pratapsinghupendra96@gmail.com",
    "C14": "anantjakhmola9@gmail.com",
    "C15": "rishabhthakur046@gmail.com",
    "C16": "jaikhandelwal460@gmail.com",
}

# First names in Devanagari, so the voice agent pronounces them correctly in Hindi.
HINDI_FIRST_NAMES = {
    "C01": "अनन्या", "C02": "रोहन", "C03": "प्रिया", "C04": "मीरा", "C05": "अर्जुन", "C06": "कबीर",
    "C07": "ईशा", "C08": "देव", "C09": "नेहा", "C10": "साहिल", "C11": "तान्या", "C12": "विक्रम",
    "C13": "उपेंद्र", "C14": "अनंत", "C15": "ऋषभ", "C16": "जय",
}


def email_for(cid: str, full_name: str) -> str:
    return REAL_EMAILS.get(cid) or f"{full_name.split()[0].lower()}@example.com"

# Pincodes where the courier has no pickup capacity (tests the no-slot fallback).
NO_PICKUP_PINCODES = {"194101"}


def reset_data() -> None:
    today = clock.today_ist()
    now = clock.now_ist().isoformat()
    with tx() as conn:
        for table in ALL_TABLES:
            conn.execute(f"DELETE FROM {table}")
        for cid, full_name, phone, address, pincode, orders in CUSTOMERS:
            conn.execute(
                "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, full_name.split()[0], HINDI_FIRST_NAMES[cid], full_name, normalize_phone(phone),
                 email_for(cid, full_name), address, pincode),
            )
            for order_id, payment, behaviour, items in orders:
                delivered_days = [i[5] for i in items if i[5] is not None]
                placed_days = (max(delivered_days) if delivered_days else 0) + 4
                conn.execute(
                    "INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
                    (order_id, cid, (today - timedelta(days=placed_days)).isoformat(), payment, behaviour),
                )
                for suffix, item_name, category, price, status, days_ago in items:
                    delivered_on = (today - timedelta(days=days_ago)).isoformat() if days_ago is not None else None
                    conn.execute(
                        "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (f"{order_id}-{suffix}", order_id, item_name, category, price, status, delivered_on),
                    )

        # Dev already has a return booked for his shirt (tests "already returned").
        conn.execute(
            "INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("RT40011", "SK1011", "SK1011-1", "size issue",
             f"{(today + timedelta(days=1)).isoformat()}_evening", "pickup_scheduled", 1499, now),
        )
        # Rohan's old hoodie: returned and refunded.
        conn.execute(
            "INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("RT40005", "SK1005", "SK1005-1", "did not like",
             f"{(today - timedelta(days=20)).isoformat()}_morning", "refunded", 1599,
             (clock.now_ist() - timedelta(days=21)).isoformat()),
        )
        # Rishabh's old puffer jacket: returned and refunded.
        conn.execute(
            "INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("RT40022", "SK1022", "SK1022-1", "size issue",
             f"{(today - timedelta(days=25)).isoformat()}_evening", "refunded", 3999,
             (clock.now_ist() - timedelta(days=26)).isoformat()),
        )
