"""Replay calendar regressions; no production calendar writes or broker access."""

from datetime import date, datetime, time, timedelta

import numpy as np
import pytest

from strategies.nifty_options.engine import IST, decision, initial_state
from strategies.nifty_options.profiles import PROFILES, ROOT, Policy
from strategies.nifty_options.replay import Archive
from strategies.nifty_options.selection import DataUnavailable


def archive():
    a = Archive.__new__(Archive)
    a.expiries = [date(2025, 10, 28), date(2025, 11, 4)]
    a.catalogues = {"2025-10-28": [], "2025-11-04": []}
    return a


def test_muhurat_uses_only_real_session_window():
    stamps, _, _ = archive().day(date(2025, 10, 21), set())
    assert len(stamps) == 60
    assert datetime.fromtimestamp(int(stamps[0]), IST).time() == time(13, 45)
    assert datetime.fromtimestamp(int(stamps[-1]), IST).time() == time(14, 44)
    assert np.all(np.diff(stamps) == 60)


def test_calendar_corrects_seed_and_includes_budget_sunday(monkeypatch):
    from database import market_calendar_db as db

    monkeypatch.setattr(
        db,
        "get_holidays_by_year",
        lambda year: [
            {"date": "2025-10-21", "closed_exchanges": ["NFO"]},
            {"date": "2025-11-14", "closed_exchanges": ["NFO"]},
        ],
    )
    a = archive()
    start, end = date(2025, 10, 20), date(2026, 2, 2)
    # Fixture intentionally includes no other holidays: this checks seed overrides.
    days = {
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    }
    days -= {date(2025, 10, 22), date(2025, 11, 5)}
    days.add(date(2026, 2, 1))
    a.spot = {int(datetime.combine(d, time(14), IST).timestamp()): 25000 for d in days}
    result = a.verify_calendar(start, end)
    assert set(result["sessions"]) == {str(d) for d in days}
    assert result["calendar_corrections"]["sources"]
    del a.spot[int(datetime.combine(date(2025, 11, 14), time(14), IST).timestamp())]
    with pytest.raises(DataUnavailable, match="missing=.*2025, 11, 14"):
        a.verify_calendar(start, end)


@pytest.mark.parametrize(
    "now", [datetime(2025, 10, 21, 13, 46, tzinfo=IST), datetime(2026, 2, 1, 9, 30, tzinfo=IST)]
)
def test_special_calendar_does_not_move_strategy_entry_window(now):
    profile = PROFILES["premium_intraday_current_week"]
    policy = Policy.load(ROOT / "strategies/nifty_options/policy.json")
    state = initial_state(profile, policy)
    action = decision(profile, policy, state, [], now, [now.date() + timedelta(days=7)])
    assert action["action"] == "wait"
