"""Documented research-only corrections to the seeded exchange calendar.

These do not update the production holiday database or change strategy entry rules.
"""

from datetime import date, time

from .greeks import session_close

SOURCES = [
    "https://nsearchives.nseindia.com/content/circulars/FAOP65588.pdf",
    "https://nsearchives.nseindia.com/content/circulars/FAOP70320.pdf",
    "https://nsearchives.nseindia.com/content/circulars/FAOP72352.pdf",
]
CORRECTIONS = {
    # The legacy seed incorrectly closes Nov 14 and labels Oct 21 Dussehra.
    "closed": ["2025-10-22", "2025-11-05"],
    "open": ["2025-10-21", "2025-11-14", "2026-02-01"],
    "special_windows": {"2025-10-21": {"start": "13:45", "end": "14:45"}},
}


def corrected_sessions(expected, start, end):
    result = set(expected)
    result.difference_update(date.fromisoformat(day) for day in CORRECTIONS["closed"])
    result.update(
        date.fromisoformat(day)
        for day in CORRECTIONS["open"]
        if start <= date.fromisoformat(day) <= end
    )
    return result


def session_window(day):
    special = CORRECTIONS["special_windows"].get(day.isoformat())
    if special:
        return time.fromisoformat(special["start"]), time.fromisoformat(special["end"])
    return time(9, 15), session_close(day)
