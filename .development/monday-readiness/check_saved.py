"""Read-only checks of scheduled Python strategies and their Monday prerequisites."""

import ast
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from database.auth_db import get_api_key_for_tradingview, verify_api_key
from database.market_calendar_db import is_market_holiday
from strategies.nifty_options.execution import cleanup_sessions
from strategies.nifty_options.schedule import verify
from strategies.top_gain_volumes.profiles import nifty500_symbols, weekday_symbols
from utils.db_sessions import remove_all_scoped_sessions

IST = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 10, 5)
config_path = ROOT / "strategies/strategy_configs.json"
raw = config_path.read_bytes()
saved = json.loads(raw)
checks = []
try:
    assert len(saved) == 20
    verify()
    for config in saved.values():
        file = Path(config["file_path"])
        ast.parse(file.read_text(), filename=str(file))
        assert config["is_scheduled"] and "mon" in config["schedule_days"]
        assert not config.get("manually_stopped")
        assert not is_market_holiday(MONDAY, config["exchange"])
        hour, minute = map(int, config["schedule_start"].split(":"))
        trigger = CronTrigger(
            day_of_week=",".join(config["schedule_days"]), hour=hour, minute=minute, timezone=IST
        )
        next_fire = trigger.get_next_fire_time(None, datetime(2026, 10, 4, 12, tzinfo=IST))
        assert next_fire.date() == MONDAY
        checks.append({"name": config["name"], "next_start_ist": next_fire.isoformat(),
                       "stop": config["schedule_stop"], "exchange": config["exchange"],
                       "source_sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    owners = {c["user_id"] for c in saved.values()}
    assert len(owners) == 1
    owner = owners.pop()
    key = get_api_key_for_tradingview(owner)
    assert key and verify_api_key(key) == owner
    universe = nifty500_symbols()
    assert len(universe) == 500
    monday = weekday_symbols(owner, MONDAY)
    databases = {}
    for name in ("openalgo.db", "sandbox.db", "market_scanner_live.db", "scanner_strategy_reports.db"):
        db = ROOT / "db" / name
        assert db.is_file(), name
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as conn:
            assert conn.execute("PRAGMA quick_check").fetchall() == [("ok",)], name
            databases[name] = "ok"
    with closing(sqlite3.connect((ROOT / "db/sandbox.db").as_uri()+"?mode=ro", uri=True)) as conn:
        funds = conn.execute("SELECT total_capital,available_balance,used_margin,realized_pnl FROM sandbox_funds WHERE user_id=?", (owner,)).fetchone()
        assert funds and funds[0] == 50_000_000
        assert conn.execute("SELECT config_value FROM sandbox_config WHERE config_key='reset_day'").fetchone()[0] == "Never"
    assert config_path.read_bytes() == raw
    result = {"checked_at": datetime.now(IST).isoformat(), "passed": True,
              "saved_schedules": checks, "scheduler_key_valid": True,
              "nifty500_symbols": len(universe), "monday_watchlist_symbols": len(monday),
              "watchlist_note": "User will populate before 09:00; empty is explicitly accepted for now.",
              "sqlite_quick_check": databases, "sandbox_funds": list(funds),
              "config_sha256": hashlib.sha256(raw).hexdigest(),
              "limits": "Saved configuration and premarket prerequisites; does not claim Monday ticks or fills are verified."}
    (Path(__file__).parent / "saved_checks.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k != "saved_schedules"}, indent=2))
finally:
    cleanup_sessions()
    remove_all_scoped_sessions()
