"""Non-destructive sandbox capital setup. Does not reset orders, positions or P&L."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from .profiles import ROOT, SANDBOX_CAPITAL


def set_capital(path, owner, capital=SANDBOX_CAPITAL):
    with closing(sqlite3.connect(path, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        try:
            before = conn.execute(
                "SELECT * FROM sandbox_funds WHERE user_id=?", (owner,)
            ).fetchone()
            if before is None:
                raise RuntimeError("Existing sandbox account required; no implicit user creation")
            delta = Decimal(str(capital)) - Decimal(str(before["total_capital"]))
            balance = Decimal(str(before["available_balance"])) + delta
            if balance < 0:
                raise RuntimeError("Capital change would make available balance negative")
            conn.execute(
                "UPDATE sandbox_funds SET total_capital=?, available_balance=?, updated_at=? WHERE user_id=?",
                (capital, str(balance), datetime.now(UTC).isoformat(), owner),
            )
            # Automatic resets would erase carried positional P&L/margin after a restart.
            for key, value in (("starting_capital", str(capital)), ("reset_day", "Never")):
                conn.execute(
                    "INSERT INTO sandbox_config(config_key,config_value,updated_at) VALUES (?,?,CURRENT_TIMESTAMP) "
                    "ON CONFLICT(config_key) DO UPDATE SET config_value=excluded.config_value, updated_at=CURRENT_TIMESTAMP",
                    (key, value),
                )
            after = conn.execute("SELECT * FROM sandbox_funds WHERE user_id=?", (owner,)).fetchone()
            protected = set(before.keys()) - {"total_capital", "available_balance", "updated_at"}
            if any(before[k] != after[k] for k in protected):
                raise RuntimeError("Unexpected modification to sandbox P&L or margin")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    keys = ("total_capital", "available_balance", "used_margin", "realized_pnl", "reset_count")
    return {
        "before": {k: before[k] for k in keys},
        "after": {k: after[k] for k in keys},
        "reset_day": "Never",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-capital", action="store_true", required=True)
    parser.parse_args()
    import os

    from dotenv import load_dotenv
    from sqlalchemy.engine import make_url

    load_dotenv(ROOT / ".env")
    with closing(
        sqlite3.connect(f"file:{ROOT / 'db/market_scanner_live.db'}?mode=ro", uri=True)
    ) as conn:
        owners = conn.execute(
            "SELECT user FROM scanner_live_accounts WHERE broker='fyers'"
        ).fetchall()
    if len(owners) != 1:
        raise RuntimeError("Exactly one configured FYERS account required")
    url = make_url(os.getenv("SANDBOX_DATABASE_URL", "sqlite:///db/sandbox.db"))
    if url.get_backend_name() != "sqlite":
        raise RuntimeError("This local administrative helper requires SQLite")
    path = Path(url.database)
    path = path if path.is_absolute() else ROOT / path
    result = set_capital(path, owners[0][0])
    folder = ROOT / "db" / "nifty_options"
    folder.mkdir(exist_ok=True)
    audit = folder / ("capital-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + ".json")
    audit.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
