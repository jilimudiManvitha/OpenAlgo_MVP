"""Read-only scheduled Sandbox capital display; quotes never place orders."""

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from services.report_brokerage import COMPONENTS, estimate_report, rounded
from strategies.nifty_options.daily_reports import trade_row
from strategies.nifty_options.hedges import protected_quantity
from strategies.nifty_options.profiles import PROFILES, ROOT
from strategies.nifty_options.selection import DataUnavailable


def state_path():
    return Path(os.environ.get("NIFTY_OPTIONS_STATE_DB", ROOT / "db/nifty_options/state.sqlite3"))


def read_states(owner):
    path = state_path()
    if not path.is_file():
        return {}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)) as c:
        c.execute("PRAGMA query_only=ON")
        c.execute("BEGIN")
        result = {}
        for name, raw, updated in c.execute(
            "SELECT strategy,payload,updated_at FROM states WHERE owner=?", (owner,)
        ):
            if name not in PROFILES:
                continue
            state = json.loads(raw)
            closed = []
            if state.get("cycle_start"):
                start = datetime.fromisoformat(state["cycle_start"]).astimezone(UTC).isoformat()
                for (payload,) in c.execute(
                    "SELECT payload FROM events WHERE owner=? AND strategy=? AND kind='trade' "
                    "AND timestamp>=? ORDER BY id",
                    (owner, name, start),
                ):
                    closed.extend(
                        t for t in json.loads(payload) if t.get("cycle") == state["cycle"]
                    )
            result[name] = {"state": state, "updated_at": updated, "closed": closed}
        return result


def fingerprint(states):
    # Heartbeat revisions are deliberately excluded; fills/intents change this.
    content = {
        name: {"legs": row["state"]["legs"], "pending": row["state"]["pending"]}
        for name, row in states.items()
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def overview(owner):
    states = read_states(owner)
    rows = []
    for name, profile in PROFILES.items():
        saved = states.get(name, {})
        state = saved.get("state", {})
        legs = state.get("legs", [])
        trades = [trade_row(leg) for leg in saved.get("closed", []) + legs]
        estimate = estimate_report(
            {
                "id": "nifty-options-capital",
                "broker": "fyers",
                "exchange": "NFO",
                "product": "NRML",
                "trades": trades,
            }
        )
        available = not estimate["charge_info"]["unavailable"]
        breakdown = {
            key: rounded(sum(t.get("charge_breakdown", {}).get(key, 0) for t in estimate["trades"]))
            for key in COMPONENTS
        }
        rows.append(
            {
                "strategy_id": name,
                "name": name.replace("_", " ").title(),
                "allocation": profile.capital,
                "deployable_budget": profile.capital * 0.90,
                "updated_at": saved.get("updated_at"),
                "cycle_start": state.get("cycle_start"),
                "pending": bool(state.get("pending")),
                "halted": bool(state.get("halted")),
                "legs": [
                    {
                        k: leg[k]
                        for k in ("symbol", "side", "quantity", "lot_size", "entry", "expiry")
                    }
                    for leg in legs
                ],
                "unprotected_shorts": sum(
                    leg["side"] < 0 and protected_quantity(profile, leg, legs) < leg["quantity"]
                    for leg in legs
                ),
                "entry_snapshot": state.get("capital_snapshot"),
                "charges": {
                    "total": rounded(sum(breakdown.values())) if available else None,
                    "breakdown": breakdown if available else {},
                    "basis": "estimated",
                    "scope": "Confirmed entries and exits in this cycle, including open entry costs",
                    "source": estimate["charge_info"]["source"],
                    "version": estimate["charge_info"]["version"],
                },
            }
        )
    return {
        "mode": "paper",
        "broker": "fyers",
        "strategies": rows,
        "allocation": sum(p.capital for p in PROFILES.values()),
        "deployable_budget": sum(p.capital * 0.90 for p in PROFILES.values()),
        "fingerprint": fingerprint(states),
    }


def current_quote(owner, strategy_id, expected_fingerprint):
    from strategies.nifty_options.runtime import broker_margin

    if not isinstance(strategy_id, str) or (
        strategy_id != "combined" and strategy_id not in PROFILES
    ):
        raise ValueError("Unknown options strategy")
    states = read_states(owner)
    if not expected_fingerprint or fingerprint(states) != expected_fingerprint:
        raise DataUnavailable("Positions changed. Reload capital before requesting margin.")
    selected_states = (
        states
        if strategy_id == "combined"
        else {strategy_id: states[strategy_id]}
        if strategy_id in states
        else {}
    )
    if any(r["state"].get("pending") for r in selected_states.values()):
        raise DataUnavailable("Reconcile pending orders before quoting this basket.")
    net = {}
    for saved in selected_states.values():
        for leg in saved["state"]["legs"]:
            net[leg["symbol"]] = net.get(leg["symbol"], 0) + leg["quantity"] * leg["side"]
    # Full held quantities, same NRML product; net identical contracts once.
    selected = [
        (SimpleNamespace(symbol=s, lot_size=abs(q)), 1 if q > 0 else -1)
        for s, q in net.items()
        if q
    ]
    if not selected:
        raise DataUnavailable("No open net basket to quote.")
    if len(selected) > 50:
        raise DataUnavailable("Basket exceeds the margin endpoint limit.")
    result = broker_margin(owner, selected, None, details=True)
    if fingerprint(read_states(owner)) != expected_fingerprint:
        raise DataUnavailable("Positions changed during the quote. Reload and try again.")
    return {
        **result,
        "strategy_id": strategy_id,
        "fingerprint": expected_fingerprint,
        "scope": "Current held net basket"
        if strategy_id == "combined"
        else "Current held strategy basket",
        "notice": "FYERS estimate at quote time; account-inclusive values may include existing broker positions. Not an order or a Sandbox cash reservation.",
    }
