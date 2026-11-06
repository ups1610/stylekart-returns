"""Return policy. The backend decides eligibility; the voice agent only explains it.

Rules are checked in a fixed order and the first failing rule wins:
  1. NOT_DELIVERED    item not delivered yet
  2. ALREADY_RETURNED a return already exists for this item (the `say` line depends on
                      whether it is still awaiting pickup, picked up, or refunded)
  3. NON_RETURNABLE   innerwear, beauty or personalised items
  4. WINDOW_EXPIRED   more than 14 days since delivery (day 14 is still eligible)
  5. OK
"""

from dataclasses import dataclass
from datetime import date

from .speech import amount_text, slot_text, spell_id

RETURN_WINDOW_DAYS = 14
NON_RETURNABLE_CATEGORIES = {"innerwear", "beauty", "personalised"}


@dataclass
class Eligibility:
    eligible: bool
    reason_code: str
    say: str
    days_left: int | None = None
    days_past: int | None = None
    existing_return_status: str | None = None


def already_returned_say(ret: dict, today: date) -> str:
    rid = spell_id(ret["id"])
    if ret["status"] == "refunded":
        return (f"Is item ka return ho chuka hai aur {amount_text(ret['refund_amount'])} ka refund "
                f"original payment method mein bhej diya gaya hai. Return ID {rid}.")
    if ret["status"] == "picked_up":
        return (f"Is item ka return ho chuka hai, pickup ho gaya hai. Return ID {rid}. "
                "Refund 5 se 7 din mein aayega.")
    day, _, period = ret["slot_id"].partition("_")
    return (f"Is item ka return pehle se book hai. Return ID {rid}. "
            f"Pickup {slot_text(date.fromisoformat(day), period, today)} hoga.")


def check(item: dict, existing_return: dict | None, today: date) -> Eligibility:
    """`existing_return` is the item's row from the returns table, or None."""
    if item["status"] != "delivered" or not item["delivered_on"]:
        return Eligibility(False, "NOT_DELIVERED",
                           "Yeh item abhi deliver nahi hua hai. Delivery ke baad hi return ho sakta hai.")

    if existing_return is not None:
        return Eligibility(False, "ALREADY_RETURNED", already_returned_say(existing_return, today),
                           existing_return_status=existing_return["status"])

    if item["category"] in NON_RETURNABLE_CATEGORIES:
        return Eligibility(False, "NON_RETURNABLE",
                           "Policy ke hisaab se is category ke items return nahi hote.")

    days_since = (today - date.fromisoformat(item["delivered_on"])).days
    if days_since > RETURN_WINDOW_DAYS:
        past = days_since - RETURN_WINDOW_DAYS
        return Eligibility(False, "WINDOW_EXPIRED",
                           f"Iski 14 din ki return window {past} din pehle khatam ho gayi.",
                           days_past=past)

    left = RETURN_WINDOW_DAYS - days_since
    if left == 0:
        say = "Yeh item return ho sakta hai. Aaj return ka aakhri din hai."
    else:
        say = f"Yeh item return ho sakta hai. Return window mein abhi {left} din baaki hain."
    return Eligibility(True, "OK", say, days_left=left)
