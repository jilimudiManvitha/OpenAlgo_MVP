"""Eight explicitly named 1/5-minute, Rs 10,000 Sandbox strategy variants."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
PROFILES = {
    "nifty500_fixed": {
        "name": "Nifty500 Scanner · Fixed 3R · 10K",
        "universe": "nifty500",
        "trailing": False,
        "file": "Top_Gain_Volumes_Live_1L_stategy.py",
    },
    "weekday_fixed": {
        "name": "Weekday Watchlist · Fixed 3R · 10K",
        "universe": "watchlist",
        "trailing": False,
        "file": "Weekday_Watchlist_Fixed_3R_10K.py",
    },
    "nifty500_trailing": {
        "name": "Nifty500 Scanner · Trail after 3R · 10K",
        "universe": "nifty500",
        "trailing": True,
        "file": "Nifty500_Scanner_Trail_3R_10K.py",
    },
    "weekday_trailing": {
        "name": "Weekday Watchlist · Trail after 3R · 10K",
        "universe": "watchlist",
        "trailing": True,
        "file": "Weekday_Watchlist_Trail_3R_10K.py",
    },
}

for _id, _profile in list(PROFILES.items()):
    _profile["timeframe_minutes"] = 1
    PROFILES[_id + "_5m"] = {
        **_profile,
        "name": _profile["name"] + " · 5m HA",
        "timeframe_minutes": 5,
        "file": {
            "nifty500_fixed": "Nifty500_Scanner_Fixed_3R_10K_5m.py",
            "nifty500_trailing": "Nifty500_Scanner_Trail_3R_10K_5m.py",
            "weekday_fixed": "Weekday_Watchlist_Fixed_3R_10K_5m.py",
            "weekday_trailing": "Weekday_Watchlist_Trail_3R_10K_5m.py",
        }[_id],
    }


def nifty500_symbols():
    import json
    import os
    import sqlite3
    from contextlib import closing

    path = Path(os.environ.get("SCANNER_LIVE_DB", ROOT / "db/market_scanner_live.db"))
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute(
            "SELECT payload FROM scanner_live_categories WHERE id=1"
        ).fetchone()
    symbols = json.loads(row[0]).get("nifty500", {}).get("symbols", []) if row else []
    if not symbols:
        raise RuntimeError("Import the Nifty 500 category before starting this strategy")
    return set(symbols)


def weekday_symbols(owner, day):
    from database.watchlist_db import Watchlist, WatchlistItem, db_session

    if day.weekday() >= 5:
        return set()
    try:
        rows = (
            db_session.query(WatchlistItem.symbol)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .filter(
                Watchlist.user_id == owner,
                Watchlist.name == WEEKDAYS[day.weekday()],
                WatchlistItem.exchange == "NSE",
            )
            .all()
        )
        return {row[0] for row in rows}
    finally:
        db_session.remove()
