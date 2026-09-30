"""Separate completed history from the requested session; reject ambiguous bars."""

from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo


def fetch_intraday_history(provider, broker_symbol, day):
    opening = int(datetime.fromisoformat(day).replace(tzinfo=ZoneInfo("Asia/Kolkata")).timestamp())
    rows = []
    for first, last in ((opening - 30 * 86400, opening - 1), (opening, opening + 86400 - 1)):
        fetched = (
            provider._request(
                "/data/history?"
                + urlencode(
                    {
                        "symbol": broker_symbol,
                        "resolution": "1",
                        "date_format": "0",
                        "range_from": str(first),
                        "range_to": str(last),
                        "cont_flag": "1",
                    }
                )
            ).get("candles")
            or []
        )
        rows.extend(r for r in fetched if first <= r[0] <= last)
    return rows
