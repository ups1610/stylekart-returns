"""Single source of "now" in India time.

Everything date-related (return window, pickup slots, seed dates) reads the
clock from here, so tests and eval runs can freeze time with
POST /admin/clock (e.g. to simulate a call at 11:50 pm).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

_frozen: datetime | None = None


def now_ist() -> datetime:
    if _frozen is not None:
        return _frozen
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def freeze(value: datetime | None) -> None:
    """Freeze the clock at `value` (naive values are treated as IST); None unfreezes."""
    global _frozen
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=IST)
    _frozen = value.astimezone(IST) if value is not None else None


def is_frozen() -> bool:
    return _frozen is not None
