"""Pickup slots: today, tomorrow and the day after, in three windows.

A slot is offered only if it starts at least 2 hours from now, so a call at
11:50 pm or after 5 pm never offers a window that has already started.
"""

from datetime import date, datetime, timedelta

from . import clock
from .seed import NO_PICKUP_PINCODES
from .speech import PERIODS, slot_text

MIN_LEAD = timedelta(hours=2)
MAX_SLOTS = 6


def available_slots(pincode: str) -> list[dict]:
    if pincode in NO_PICKUP_PINCODES:
        return []
    now = clock.now_ist()
    today = now.date()
    slots = []
    for offset in range(3):
        day = today + timedelta(days=offset)
        for period, info in PERIODS.items():
            start = datetime(day.year, day.month, day.day, info["start"], tzinfo=clock.IST)
            if start - now < MIN_LEAD:
                continue
            slots.append({
                "slot_id": f"{day.isoformat()}_{period}",
                "slot_text": slot_text(day, period, today),
            })
    return slots[:MAX_SLOTS]


def describe_slot(slot_id: str) -> str:
    """Speakable text for a stored slot id, relative to today."""
    day_str, period = slot_id.split("_", 1)
    return slot_text(date.fromisoformat(day_str), period, clock.today_ist())
