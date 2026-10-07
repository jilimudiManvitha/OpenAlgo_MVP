"""Install eight Sandbox strategies through the existing NSE-aware scheduler."""

import hashlib
import json

from strategies.top_gain_volumes.profiles import PROFILES, ROOT


def configurations(owner):
    suffix = hashlib.sha256(owner.encode()).hexdigest()[:12]
    result = {}
    for profile_id, profile in PROFILES.items():
        prefix = (
            "Top_Gain_Volumes_Live_1L_"
            if profile_id == "nifty500_fixed"
            else f"Four10K_{profile_id}_"
        )
        path = ROOT / "strategies" / profile["file"]
        if not path.is_file():
            raise RuntimeError("Bundled strategy source is missing")
        result[prefix + suffix] = {
            "name": profile["name"],
            "file_path": str(path),
            "file_name": path.name,
            "exchange": "NSE",
            "user_id": owner,
            "is_running": False,
            "is_scheduled": True,
            "manually_stopped": False,
            "schedule_start": "09:15",
            "schedule_stop": "15:15",
            "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
        }
    return result


def install(owner):
    from blueprints import python_strategy as scheduler

    desired = configurations(owner)
    for strategy_id in desired:
        existing = scheduler.STRATEGY_CONFIGS.get(strategy_id, {})
        if existing and existing.get("user_id") != owner:
            raise RuntimeError("Strategy ownership mismatch")
        if existing.get("is_running"):
            raise RuntimeError("Stop the existing paper run before replacing its schedule")
    for strategy_id, config in desired.items():
        existing = scheduler.STRATEGY_CONFIGS.get(strategy_id, {})
        scheduler.STRATEGY_CONFIGS[strategy_id] = {
            **existing,
            **config,
            "created_at": existing.get("created_at", scheduler.get_ist_time().isoformat()),
        }
        for field in ("is_error", "error_message", "error_time", "paused_reason", "paused_message"):
            scheduler.STRATEGY_CONFIGS[strategy_id].pop(field, None)
        if scheduler.SCHEDULER is not None:
            scheduler.schedule_strategy(strategy_id, "09:15", "15:15", config["schedule_days"])
    scheduler.save_configs()
    saved = json.loads(scheduler.CONFIG_FILE.read_text())
    if any(
        any(saved.get(sid, {}).get(k) != value for k, value in config.items())
        for sid, config in desired.items()
    ):
        raise RuntimeError("Eight-strategy schedule persistence could not be verified")
    return list(desired)


def main():
    """Explicit local installer; never starts a strategy or submits an order."""
    import argparse
    import sqlite3
    from contextlib import closing

    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", required=True)
    parser.add_argument(
        "--backtest-day", help="Optional: require verified replays for all eight profiles"
    )
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    with closing(sqlite3.connect("file:db/market_scanner_live.db?mode=ro", uri=True)) as conn:
        owners = conn.execute(
            "SELECT user FROM scanner_live_accounts WHERE broker='fyers'"
        ).fetchall()
    if len(owners) != 1:
        raise RuntimeError("Exactly one FYERS account is required for the local installer")
    owner = owners[0][0]
    if args.backtest_day:
        verify_backtests(owner, args.backtest_day)
    from blueprints import python_strategy as scheduler

    try:
        ids = install(owner)
        for sid in ids:
            start = scheduler.SCHEDULER.get_job("start_" + sid)
            stop = scheduler.SCHEDULER.get_job("stop_" + sid)
            if start is None or stop is None:
                raise RuntimeError("Missing scheduler jobs")
            print(
                json.dumps(
                    {
                        "name": scheduler.STRATEGY_CONFIGS[sid]["name"],
                        "next_start": str(start.next_run_time),
                        "next_stop": str(stop.next_run_time),
                    }
                )
            )
        print(
            "Saved eight schedules. An already-running app must reload/restart to read this configuration."
        )
    finally:
        scheduler.shutdown_scheduler()


def verify_backtests(owner, day):
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect("file:db/scanner_strategy_reports.db?mode=ro", uri=True)) as conn:
        for profile in PROFILES:
            found = conn.execute(
                "SELECT payload FROM reports WHERE owner=? AND id=?",
                (owner, f"backtest-{day}-{profile}"),
            ).fetchone()
            if not found or not json.loads(found[0]).get("verification", {}).get("passed"):
                raise RuntimeError("Run and verify all eight backtests before using --backtest-day")


if __name__ == "__main__":
    main()
