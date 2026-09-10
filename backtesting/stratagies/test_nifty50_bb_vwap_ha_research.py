"""Synthetic execution/accounting tests; fixtures are not historical results."""
import ast
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

import nifty50_bb_vwap_ha_research as r


def session(day="2025-01-02"):
    index = pd.date_range(f"{day} 09:15", periods=75, freq="5min")
    close = 100 + np.linspace(0, 3, 75) + np.sin(np.arange(75)) / 10
    return pd.DataFrame(dict(open=close - 0.05, high=close + 0.2, low=close - 0.2,
                             close=close, volume=np.full(75, 1000)), index=index)


def daily():
    index = pd.bdate_range("2024-11-01", "2025-01-03")
    return pd.DataFrame(dict(open=100., high=101., low=99., close=100., volume=75_000.), index=index)


def opportunity(symbol="SBIN", entry="2025-01-02 11:10", exit="2025-01-02 12:00", price=100.):
    entry, exit = pd.Timestamp(entry), pd.Timestamp(exit)
    return dict(symbol=symbol, signal_time=entry - pd.Timedelta(minutes=5), entry_time=entry,
                exit_time=exit, entry_price=price, exit_price=price + 1, risk_per_share=2,
                rank=1, reason="test", worst_price=price - 0.5)


def test_source_signal_parity_and_causality():
    original = ast.parse(r.SOURCE.read_text(encoding="utf-8"))
    names = {"add_heikin_ashi", "no_lower_wick", "bullish_ha", "signal_candle_condition", "entry_candle_condition"}
    module = ast.Module(body=[n for n in original.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    namespace = {"np": np, "pd": pd}
    exec(compile(module, "source_pure_functions", "exec"), namespace)
    bars = session()
    # Include sharp moves so parity covers nontrivial crossovers.
    bars.iloc[40:43, :4] += np.array([0.5, 1., 2.])[:, None]
    f = r.features(bars, daily(), 20, 2.)
    source = namespace["add_heikin_ashi"](bars)
    for ours, theirs in [("hc", "ha_close"), ("hh", "ha_high")]:
        np.testing.assert_allclose(f[ours], source[theirs])
    source["bb_upper"], source["bb_middle"], source["vwap"] = f.upper, f.middle, f.vwap
    for i in range(21, len(f)):
        assert bool(f.signal.iloc[i]) == namespace["signal_candle_condition"](source, i)
        assert bool(f.confirmation.iloc[i]) == namespace["entry_candle_condition"](source, i - 1, i)
    truncated = r.features(bars.iloc[:45], daily(), 20, 2.)
    pd.testing.assert_frame_equal(f.iloc[:45], truncated)
    changed_daily = daily()
    changed_daily.loc["2025-01-02", ["volume", "close"]] = [1e12, 1e6]
    altered = r.features(bars, changed_daily, 20, 2.)
    pd.testing.assert_series_equal(f.volume_ratio, altered.volume_ratio)
    pd.testing.assert_series_equal(f.gain, altered.gain)


def test_session_reset():
    a, b = session(), session("2025-01-03")
    joined = r.features(pd.concat([a, b]), daily(), 20, 2.)
    alone = r.features(b, daily(), 20, 2.)
    pd.testing.assert_frame_equal(joined.loc[b.index], alone, check_freq=False)


def test_shared_capital_no_overlap_and_costs():
    p = r.Parameters()
    first = opportunity()
    overlap = opportunity("INFY", "2025-01-02 11:20", "2025-01-02 12:10")
    second = opportunity("INFY", "2025-01-02 12:10", "2025-01-02 13:00", 200.)
    trades, equity = r.simulate([first, overlap, second], p, pd.DatetimeIndex(["2025-01-02"]))
    assert len(trades) == 2
    assert all(trades.quantity % 1 == 0)
    assert all(trades.quantity * trades.entry_price <= 50_000)
    assert equity.iloc[-1] == pytest.approx(10_000 + trades.net_pnl.sum())
    assert all(trades.net_pnl < trades.gross_pnl)
    assert trades.iloc[0].quantity * 100 / 5 + trades.iloc[0].buy_fee <= 10_000
    assert r.vectorbt_audit(trades)["status"] == "passed"


def crafted_features():
    f = session()
    for name in ["hc", "hh", "upper", "middle", "vwap", "atr", "gain", "volume_ratio", "rvol"]:
        f[name] = 1.
    f["hc"] = 102.
    f["middle"] = 90.
    f["signal"] = False
    f["confirmation"] = False
    f.loc[f.index[22], "signal"] = True
    f.loc[f.index[23], "confirmation"] = True
    f["gain"] = 2.
    f["low"] = 101.
    f["high"] = 103.
    f["open"] = 102.
    f.loc[f.index[25], ["open", "low"]] = [98., 97.]
    return {"SBIN": f}


def test_real_next_open_and_gap_stop():
    p = replace(r.Parameters(), stop_mode="fixed_hard", fixed_risk=2.)
    opps = r.opportunities(crafted_features(), p, slippage_bps=0)
    assert len(opps) == 1
    trade = opps[0]
    assert trade["entry_time"] == pd.Timestamp("2025-01-02 11:15")
    assert trade["entry_price"] == 102.
    assert trade["exit_price"] == 98.  # Gap below stop fills at lower real open.
    assert trade["reason"] == "hard_stop"


def test_baseline_stop_uses_ha_close_not_real_low():
    opps = r.opportunities(crafted_features(), r.Parameters(), slippage_bps=0)
    assert len(opps) == 1
    assert opps[0]["reason"] == "square_off"
    assert opps[0]["exit_time"] == pd.Timestamp("2025-01-02 15:20")


def test_risk_sizing_and_daily_loss_cutoff():
    p = replace(r.Parameters(), risk_fraction=.01, daily_loss_fraction=.005)
    losing = opportunity()
    losing["exit_price"] = 98
    next_trade = opportunity(entry="2025-01-02 12:10", exit="2025-01-02 13:00")
    trades, _ = r.simulate([losing, next_trade], p, pd.DatetimeIndex(["2025-01-02"]))
    assert len(trades) == 1
    assert trades.iloc[0].quantity == 50
    assert trades.iloc[0].net_pnl < -100


def test_first_day_loss_counts_in_drawdown():
    equity = pd.Series([9000., 9500.], index=pd.bdate_range("2025-01-02", periods=2))
    m = r.metrics(equity)
    assert m["max_daily_drawdown_pct"] == pytest.approx(-10.)
    assert m["total_return_pct"] == pytest.approx(-5.)


def test_invalid_candles_fail():
    f = session()
    f.iloc[0, f.columns.get_loc("high")] = 1.
    with pytest.raises(RuntimeError, match="Invalid OHLCV"):
        r.normalize(f)


def test_ist_preserved():
    f = session()
    f.index = f.index.tz_localize("Asia/Kolkata").tz_convert("UTC")
    result = r.normalize(f)
    assert result.index[0] == pd.Timestamp("2025-01-02 09:15")


def test_search_predeclared():
    params = r.experiments()
    assert len(params) == 35
    assert len({p.name for p in params}) == 35


def test_report_export(tmp_path):
    p = r.Parameters()
    trades, equity = r.simulate([opportunity()], p, pd.bdate_range("2025-01-02", periods=3))
    result = pd.DataFrame({"baseline": r.metrics(equity, trades)}).T
    curves = pd.DataFrame({"Baseline": equity, "Selected": equity, "NIFTY": equity})
    trials = pd.DataFrame([dict(bb_length=20, bb_multiplier=2., development_return_pct=1., development_sharpe=.1)])
    manifest = dict(start="2025-01-02", end="2025-01-06", actual_end="2025-01-06", universe=["SBIN", "INFY"])
    r.export_report(tmp_path, result, curves, trades, trades, trials, p, manifest, "synthetic software test only")
    assert (tmp_path / f"{r.NAME}_detailed_report.md").exists()
    assert (tmp_path / "equity_drawdown.html").exists()
    stocks = pd.read_csv(tmp_path / "per_stock_results.csv")
    assert len(stocks) == 4
    assert stocks.loc[stocks.symbol == "INFY", "trades"].eq(0).all()
