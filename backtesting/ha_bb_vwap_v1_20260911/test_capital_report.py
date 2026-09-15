"""Capital accounting edge cases, independent of strategy entry rules."""

import pandas as pd
from capital_report import START, cost_parts, equity_curve, timeline


def trade(key, fills):
    records = []
    for clock, side, qty, price, reason in fills:
        fill = {
            "time": f"2026-09-11T{clock}+05:30",
            "side": side,
            "quantity": qty,
            "price": price,
            "reason": reason,
        }
        fill["fees"] = sum(cost_parts(fill).values())
        records.append(fill)
    net = sum(
        (1 if f["side"] == "sell" else -1) * f["price"] * f["quantity"] - f["fees"] for f in records
    )
    return {"id": key, "symbol": key, "side": "buy", "fills": records, "net_pnl": net}


def test_partial_release_and_equal_time_exit_entry_do_not_inflate_peak():
    rows = timeline(
        [
            trade(
                "A",
                [
                    ("10:00:00", "buy", 10, 100, "entry"),
                    ("10:02:00", "sell", 5, 120, "partial"),
                    ("10:03:00", "sell", 5, 80, "stop_loss"),
                ],
            ),
            trade(
                "B",
                [("10:01:00", "buy", 5, 200, "entry"), ("10:04:00", "sell", 5, 210, "square_off")],
            ),
            trade(
                "C",
                [
                    ("10:03:00", "buy", 10, 100, "entry"),
                    ("10:05:00", "sell", 10, 100, "square_off"),
                ],
            ),
        ]
    )
    times = {r["time"][11:19]: r for r in rows}
    assert times["10:02:00"]["capital_in_use"] == 1500
    assert times["10:02:00"]["open_positions"] == 2
    assert times["10:02:00"]["closed_trades_so_far"] == 0
    assert times["10:03:00"]["capital_in_use"] == 2000
    assert times["10:03:00"]["open_positions"] == 2
    assert max(r["capital_in_use"] for r in rows) == 2000
    assert rows[-1]["capital_in_use"] == 0 and rows[-1]["closed_trades_so_far"] == 3


def test_drawdown_uses_previous_peak_and_includes_initial_loss():
    series = pd.Series(
        {
            "2026-09-11T10:00:00+05:30": -200,
            "2026-09-11T11:00:00+05:30": 100,
            "2026-09-11T12:00:00+05:30": -50,
        }
    )
    _, stats = equity_curve([series], 50)
    assert stats["max_drawdown"] == 200
    assert stats["drawdown_peak_time"] == START
    assert stats["drawdown_trough_time"] == "2026-09-11T10:00:00+05:30"
    assert stats["max_session_mtm_profit"] == 100
    assert stats["min_session_mtm_pnl"] == -200


def test_no_trades_reports_zero_capital_and_positions():
    rows = timeline([])
    assert len(rows) == 2
    assert all(r["capital_in_use"] == r["open_positions"] == r["entries_so_far"] == 0 for r in rows)
