"""Helpers that turn data into text a voice agent can read aloud naturally.

The agent speaks Hinglish, so dates, slots and amounts are pre-formatted
here instead of asking the LLM to do date maths or read raw JSON.
"""

import re
from datetime import date

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

DAY_WORDS = {0: "aaj", 1: "kal", 2: "parson"}

PERIODS = {
    "morning": {"start": 9, "end": 12, "text": "subah 9 se 12 baje"},
    "afternoon": {"start": 12, "end": 16, "text": "dopahar 12 se 4 baje"},
    "evening": {"start": 16, "end": 19, "text": "shaam 4 se 7 baje"},
}


def date_text(d: date) -> str:
    """2026-11-03 -> '3 November'."""
    return f"{d.day} {MONTHS[d.month - 1]}"


def ordinal_date_en(d: date) -> str:
    """2026-11-05 -> '5th November', so the agent says "fifth", not "five". 11-13 take "th"."""
    if 11 <= d.day % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(d.day % 10, "th")
    return f"{d.day}{suffix} {MONTHS[d.month - 1]}"


def day_word_en(d: date, today: date) -> str | None:
    """'today' / 'tomorrow', or None for later days."""
    return {0: "today", 1: "tomorrow"}.get((d - today).days)


def slot_date(slot_id: str) -> date:
    """'2026-11-07_evening' -> date(2026, 11, 7)."""
    return date.fromisoformat(slot_id.split("_", 1)[0])


def delivered_text(delivered_on: date, today: date) -> str:
    days = (today - delivered_on).days
    if days == 0:
        when = "aaj"
    elif days == 1:
        when = "kal"
    else:
        when = f"{days} din pehle"
    return f"{date_text(delivered_on)} ko deliver hua tha ({when})"


def slot_text(slot_day: date, period: str, today: date) -> str:
    offset = (slot_day - today).days
    day_word = DAY_WORDS.get(offset, date_text(slot_day) + " ko")
    return f"{day_word} {PERIODS[period]['text']}"


def spell_id(value: str) -> str:
    """'RT48217' -> 'R T 4 8 2 1 7' so the agent reads it character by character."""
    return " ".join(ch for ch in value if ch.strip())


def amount_text(rupees: int) -> str:
    """1299 -> '1,299 rupaye' (Indian digit grouping)."""
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
        s = f"{head},{tail}"
    return f"{s} rupaye"
