"""Return policy. The backend decides eligibility; the voice agent only explains it.

Rules are checked in a fixed order and the first failing rule wins:
  1. NOT_DELIVERED    item not delivered yet
  2. ALREADY_RETURNED a return already exists for this item
  3. NON_RETURNABLE   innerwear, beauty or personalised items
  4. WINDOW_EXPIRED   more than 14 days since delivery (day 14 is still eligible)
  5. OK
"""

from dataclasses import dataclass
from datetime import date

RETURN_WINDOW_DAYS = 14
NON_RETURNABLE_CATEGORIES = {"innerwear", "beauty", "personalised"}


@dataclass
class Eligibility:
    eligible: bool
    reason_code: str
    say: str
    days_left: int | None = None
    days_past: int | None = None


def check(item: dict, has_return: bool, existing_return_id: str | None, today: date) -> Eligibility:
    if item["status"] != "delivered" or not item["delivered_on"]:
        return Eligibility(False, "NOT_DELIVERED",
                           "Yeh item abhi deliver nahi hua hai. Delivery ke baad hi return ho sakta hai.")

    if has_return:
        return Eligibility(False, "ALREADY_RETURNED",
                           f"Is item ka return pehle se book hai. Return ID {' '.join(existing_return_id or '')} hai.")

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
