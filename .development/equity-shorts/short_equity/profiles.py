"""Eight short counterparts, independent of the installed long profiles."""

PROFILES = {}
for _minutes in (1, 5):
    for _universe, _label, _file in (
        ("nifty500", "Nifty500 Scanner", "Nifty500_Scanner"),
        ("weekday", "Weekday Watchlist", "Weekday_Watchlist"),
    ):
        for _trailing in (False, True):
            _exit = "trailing" if _trailing else "fixed"
            _suffix = "_5m" if _minutes == 5 else ""
            _id = f"{_universe}_short_{_exit}{_suffix}"
            PROFILES[_id] = {
                "name": f"{_label} · SHORT · {'Trail after 3R' if _trailing else 'Fixed 3R'} · 10K · {_minutes}m HA",
                "universe": "nifty500" if _universe == "nifty500" else "watchlist",
                "trailing": _trailing,
                "timeframe_minutes": _minutes,
                "direction": "SHORT",
                "file": f"{_file}_Short_{'Trail' if _trailing else 'Fixed'}_3R_10K{_suffix}.py",
            }
