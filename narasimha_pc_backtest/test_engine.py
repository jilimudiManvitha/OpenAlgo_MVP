"""Deterministic behavioral checks; these fixtures are not historical results."""

import numpy as np
import pytest
from engine import indicators, replay
from run import stamp, validate


def fixture(days=1):
    blocks = []
    for d in range(days):
        t = stamp("2021-09-27") + d * 86400 + 555 * 60
        x = np.array([[t + i * 60, 100, 100, 100, 100, 1000] for i in range(375)], dtype=float)
        x[20, 1:5] = [101, 110, 101, 108]
        x[21, 1:5] = [107, 115, 98, 104]
        blocks.append(x)
    return np.concatenate(blocks)


def run(x, path=1, cutoff=905, **kwargs):
    allowed, _ = validate(x, cutoff, stamp("2021-09-25"), stamp("2021-10-01"))
    return replay(x, indicators(x), allowed, cutoff, path, **kwargs)


def test_ha_and_bands_against_independent_numpy():
    raw = fixture()
    actual = indicators(raw)
    hc = raw[:, 1:5].mean(axis=1)
    ho = np.empty(len(raw))
    ho[0] = (raw[0, 1] + raw[0, 4]) / 2
    for i in range(1, len(raw)):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2
    np.testing.assert_allclose(
        actual[:, :4],
        np.column_stack([ho, np.maximum(raw[:, 2], ho), np.minimum(raw[:, 3], ho), hc]),
    )
    for i in [19, 20, 21, 100, 374]:
        window = hc[i - 19 : i + 1]
        assert actual[i, 4] == pytest.approx(window.mean() + 2 * window.std(ddof=0))
    assert np.isnan(actual[18, 4])


def test_vwap_resets_and_ha_carries_across_midnight():
    raw = fixture(2)
    raw[375, 1:5] = [150, 155, 148, 152]
    ha = indicators(raw)
    assert ha[375, 7] == pytest.approx((155 + 148 + 152) / 3)
    assert ha[375, 0] == pytest.approx((ha[374, 0] + ha[374, 3]) / 2)


def test_intrabar_order_changes_wick_eligibility_without_future_rejection():
    raw = fixture()
    high_first, low_first = run(raw, 1), run(raw, 0)
    assert len(high_first) == 1
    assert len(low_first) == 0
    trade = high_first[0]
    assert trade[1] < raw[21, 0] + 20
    assert trade[11] == 1
    assert trade[2] < raw[21, 0] + 40
    assert indicators(raw)[21, 2] < indicators(raw)[21, 0]
    assert trade[3] * trade[5] <= 100000
    assert trade[6] == pytest.approx(99.9)


def test_one_trade_per_stock_per_day_and_reset_next_day():
    raw = fixture(2)
    for start in [0, 375]:
        raw[start + 100, 1:5] = [101, 110, 101, 108]
        raw[start + 101, 1:5] = [107, 115, 98, 104]
    t = run(raw)
    assert len(t) == 2
    assert t[:, 0].tolist() == [raw[20, 0], raw[395, 0]]


def test_target_is_3r_rounded_up_and_limit_fill():
    raw = fixture()
    raw[21, 1:5] = [107, 150, 104, 140]
    t = run(raw)[0]
    assert t[11] == 2
    assert t[4] == t[7]
    assert t[7] >= t[3] + 3 * (t[3] - t[6]) - 1e-8
    assert t[7] < t[3] + 3 * (t[3] - t[6]) + 0.050001
    assert t[10] == pytest.approx((t[4] - t[3]) * t[5] - (t[4] + t[3]) * t[5] * 0.0005)


@pytest.mark.parametrize("cutoff", [905, 920])
def test_scheduled_exit_uses_cutoff_open(cutoff):
    raw = fixture()
    raw[21, 1:5] = [107, 115, 104, 114]
    t = run(raw, cutoff=cutoff)[0]
    assert t[11] == 3
    assert t[2] == raw[cutoff - 555, 0]
    assert t[13] == raw[cutoff - 555, 1]


def test_gap_stop_fills_at_available_open():
    raw = fixture()
    raw[21, 1:5] = [107, 115, 104, 114]
    raw[22, 1:5] = [90, 95, 85, 91]
    t = run(raw)[0]
    assert t[11] == 1
    assert t[13] == 90
    assert t[4] < 90


def test_missing_cutoff_or_gap_excludes_session():
    raw = fixture()
    for ix in [10, 350]:
        incomplete = np.delete(raw, ix, axis=0)
        mask, coverage = validate(incomplete, 905, stamp("2021-09-25"), stamp("2021-10-01"))
        assert not mask.any()
        assert coverage[0]["missing_to_cutoff"] == 1
        assert len(replay(incomplete, indicators(incomplete), mask, 905, 1)) == 0


def test_signal_only_valid_on_immediate_next_minute():
    raw = fixture()
    raw[21, 0] += 1
    # Bypass input audit to isolate the immediate-next-minute engine guard.
    assert len(replay(raw, indicators(raw), np.ones(len(raw), dtype=np.bool_), 905, 1)) == 0


def test_zero_volume_and_signal_lower_wick_prevent_entry():
    raw = fixture()
    raw[21, 5] = 0
    assert len(run(raw)) == 0
    raw = fixture()
    raw[20, 3] = 99
    assert len(run(raw)) == 0


def test_compiled_matches_python_and_sampling_refinement():
    raw = fixture(2)
    ha = indicators(raw)
    allowed = np.ones(len(raw), dtype=np.bool_)
    args = (raw, ha, allowed, 905, 1, 0.05, 0.0005, 0.0005, 100000.0, 3.0, 0.1, 32)
    np.testing.assert_allclose(replay(*args), replay.py_func(*args), rtol=0, atol=1e-9)
    coarse, fine = replay(*args), replay(*args[:-1], 128)
    np.testing.assert_allclose(coarse[:, 3:11], fine[:, 3:11], rtol=0, atol=1e-8)


def test_invalid_data_rejected():
    raw = fixture()
    raw[5, 2] = 90
    with pytest.raises(ValueError, match="OHLC"):
        validate(raw, 905, stamp("2021-09-25"), stamp("2021-10-01"))


def test_worker_quarantines_bad_session_and_preserves_source(tmp_path):
    import duckdb
    import pandas as pd
    from run import digest, worker

    raw = fixture(2)
    raw[5, 2] = 90
    frame = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame["symbol"], frame["exchange"], frame["interval"] = "SBIN", "NSE", "1m"
    source = tmp_path / "source.duckdb"
    with duckdb.connect(str(source)) as db:
        db.register("fixture_data", frame)
        db.execute("CREATE TABLE market_data AS SELECT * FROM fixture_data")
    before = digest(source)
    out = tmp_path / "results"
    for folder in ["candles", "coverage", "ledgers", "rejected"]:
        (out / folder).mkdir(parents=True)
    cfg = {
        "source": str(source),
        "start": "2021-09-27",
        "end": "2021-09-28",
        "asof_timestamp": stamp("2021-10-01"),
        "slippage_bps": 5,
        "fee_bps": 5,
        "capital": 100000.0,
        "rr": 3.0,
        "stop_offset": 0.1,
        "steps": 32,
    }
    audit = worker("SBIN", cfg, {"is_fo": True, "tick": 0.05}, out)
    assert audit["rejected_invalid_rows"] == 1
    assert audit["eligible_sessions"] == 1
    assert audit["excluded_sessions"] == 1
    trades = pd.read_csv(out / "ledgers/SBIN.csv")
    assert len(trades) == 1
    assert trades.date.tolist() == ["2021-09-28"]
    assert digest(source) == before


@pytest.mark.parametrize("path", [0, 1])
def test_named_scenario_entrypoints(path):
    import importlib

    suffix = "olhc" if path == 0 else "ohlc"
    module = importlib.import_module("buy_ha1m_bb20x2_vwap_sl010_tp3r_" + suffix)
    raw = fixture()
    ha = indicators(raw)
    allowed = np.ones(len(raw), dtype=np.bool_)
    np.testing.assert_allclose(
        module.backtest(raw, ha, allowed, True, 0.05),
        replay(raw, ha, allowed, 905, path),
        atol=1e-9,
    )
