import re


def normalize_phone(raw: str) -> str:
    """Accept '+91 98765 43210', '098765-43210', '9876543210' -> '+919876543210'.

    Ringg may send the caller's number in different formats, so lookups never
    depend on spacing, a leading 0 or the country code.
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) >= 10:
        return "+91" + digits[-10:]
    return "+" + digits if digits else ""
