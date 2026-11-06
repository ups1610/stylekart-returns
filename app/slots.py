"""Pickup slots: the next 3 days that still have a pickup window, in three windows a day.

A slot is offered only if it starts at least 2 hours from now, so a call at
11:50 pm or after 5 pm never offers a window that has already started. A day
with no such window (today, late at night) is skipped and the next day is used,
so callers are always offered 3 days.
"""

from datetime import date, datetime, timedelta

from . import clock
from .seed import NO_PICKUP_PINCODES
from .speech import PERIODS, slot_text

MIN_LEAD = timedelta(hours=2)
MAX_SLOTS = 9
DAYS_OFFERED = 3
MAX_DAYS_AHEAD = 5  # look at today plus at most 5 days ahead


def available_slots(pincode: str) -> list[dict]:
    if pincode in NO_PICKUP_PINCODES:
        return []
    now = clock.now_ist()
    today = now.date()
    slots, days_used = [], 0
    for offset in range(MAX_DAYS_AHEAD + 1):
        day = today + timedelta(days=offset)
        day_slots = [
            {"slot_id": f"{day.isoformat()}_{period}", "slot_text": slot_text(day, period, today)}
            for period, info in PERIODS.items()
            if datetime(day.year, day.month, day.day, info["start"], tzinfo=clock.IST) - now >= MIN_LEAD
        ]
        if not day_slots:
            continue
        slots += day_slots
        days_used += 1
        if days_used == DAYS_OFFERED:
            break
    return slots[:MAX_SLOTS]


def describe_slot(slot_id: str) -> str:
    """Speakable text for a stored slot id, relative to today."""
    day_str, period = slot_id.split("_", 1)
    return slot_text(date.fromisoformat(day_str), period, clock.today_ist())
