from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from polars_data import TZ, aggregate_pnl, export_heikin_ashi, prepare_historify


def candles(day="2026-01-05"):
    stamps = pd.date_range(day + " 09:15", periods=75, freq="5min")
    return pd.DataFrame({"date": stamps.strftime("%Y-%m-%d"), "time": stamps.strftime("%H:%M:%S"),
                         "open": 100., "high": 102., "low": 99., "close": 101., "volume": 100.})


def prepare(tmp_path, data, now="2026-09-09 12:00"):
    path = tmp_path / "data.csv"
    data.to_csv(path, index=False)
    return prepare_historify(path, now=now)


def test_sort_timezone_and_boundary(tmp_path):
    result = prepare(tmp_path, candles().sample(frac=1, random_state=12))
    raw = result.to_strategy()
    assert len(raw) == 75 and raw.timestamp.is_monotonic_increasing
    assert str(raw.timestamp.iloc[0]) == "2026-01-05 09:15:00+05:30"
    assert str(raw.timestamp.dtype) == f"datetime64[ns, {TZ}]"
    assert raw.close.dtype == np.dtype("float64")
    assert result.exclusions == []


@pytest.mark.parametrize("bad", ["duplicate", "missing", "negative", "range", "infinity"])
def test_bad_input_rejected(tmp_path, bad):
    data = candles()
    if bad == "duplicate": data = pd.concat([data, data.iloc[:1]])
    elif bad == "missing": data.loc[0, "close"] = np.nan
    elif bad == "negative": data.loc[0, "volume"] = -1
    elif bad == "range": data.loc[0, "high"] = 100
    elif bad == "infinity": data.loc[0, "close"] = np.inf
    with pytest.raises(ValueError): prepare(tmp_path, data)


@pytest.mark.parametrize("kind", ["gap", "off_grid", "fractional", "unfinished"])
def test_session_exclusions(tmp_path, kind):
    extra = candles("2026-01-06")
    if kind == "gap": extra = extra.iloc[:-1]
    elif kind == "off_grid": extra.loc[0, "time"] = "09:16:00"
    elif kind == "fractional": extra.loc[0, "time"] = "09:15:00.000001"
    result = prepare(tmp_path, pd.concat([candles(), extra]),
                     now="2026-01-06 15:29" if kind == "unfinished" else "2026-01-07")
    assert len(result.to_strategy()) == 75
    assert result.exclusions[0]["date"] == "2026-01-06"
    assert result.exclusions[0]["reason"] == ("Unfinished bar" if kind == "unfinished" else "Incomplete/non-regular session")


def test_zero_volume_and_no_complete_session(tmp_path):
    data = candles(); data.loc[0, "volume"] = 0
    assert len(prepare(tmp_path, data).to_strategy()) == 75
    with pytest.raises(ValueError, match="No complete"):
        prepare(tmp_path, data.iloc[:74])


def test_pnl_includes_no_trade_days_and_month_boundaries():
    dates = pd.DatetimeIndex(["2026-01-30", "2026-02-02", "2026-02-03"], tz=TZ)
    equity = pd.Series([100100., 100100., 100060.], index=dates)
    ledger = pd.DataFrame({"exit_time": pd.to_datetime(["2026-01-30 10:00", "2026-02-03 15:20"]).tz_localize(TZ),
                            "gross_pnl": [110., -30.], "costs": [10., 10.],
                            "net_pnl": [100., -40.], "reason": ["bb_middle", "square_off"]})
    daily, monthly, exits = aggregate_pnl(ledger, equity, 100000.)
    assert daily.trades.tolist() == [1, 0, 1]
    assert daily.net_pnl.tolist() == [100., 0., -40.]
    assert monthly.net_pnl.tolist() == [100., -40.]
    assert monthly.closing_equity.tolist() == [100100., 100060.]
    np.testing.assert_allclose(monthly.return_pct, [.1, -40 / 100100 * 100])
    assert exits.net_pnl.sum() == 60.


def test_heikin_ashi_export_preserves_calculated_values(tmp_path):
    d = pd.DataFrame({"symbol": ["TEST"], "open": [289.9], "high": [299.7], "low": [288.15],
                      "close": [296.6], "ha_open": [293.25], "ha_high": [299.7],
                      "ha_low": [288.15], "ha_close": [293.5875], "volume": [100.]},
                     index=pd.DatetimeIndex(["2025-05-07 09:15"],tz=TZ))
    export_heikin_ashi(d, tmp_path)
    ha = pd.read_csv(tmp_path / "ATHERENERG_heikin_ashi_5m.csv")
    np.testing.assert_allclose(ha[["open","high","low","close"]], [[293.25,299.7,288.15,293.5875]])
    assert len(pd.read_csv(tmp_path / "real_vs_heikin_ashi.csv")) == 1
