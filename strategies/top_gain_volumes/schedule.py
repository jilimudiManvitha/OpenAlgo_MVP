"""Install the bundled paper strategy through the existing scheduler configuration."""

import hashlib
from pathlib import Path


def install(owner):
    from blueprints import python_strategy as scheduler

    strategy_id = "Top_Gain_Volumes_Live_1L_" + hashlib.sha256(owner.encode()).hexdigest()[:12]
    path = Path("strategies/Top_Gain_Volumes_Live_1L_stategy.py").resolve()
    if not path.is_file():
        raise RuntimeError("Bundled strategy source is missing")
    existing = scheduler.STRATEGY_CONFIGS.get(strategy_id)
    if existing and existing.get("user_id") != owner:
        raise RuntimeError("Strategy ownership mismatch")
    if existing and existing.get("is_running"):
        return strategy_id
    scheduler.STRATEGY_CONFIGS[strategy_id] = {
        "name": "Top_Gain_Volumes_Live_1L_stategy",
        "file_path": str(path),
        "file_name": path.name,
        "exchange": "NSE",
        "user_id": owner,
        "is_running": False,
        "is_scheduled": True,
        "created_at": scheduler.get_ist_time().isoformat(),
        "schedule_start": "09:15",
        "schedule_stop": "15:10",
        "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
    }
    scheduler.save_configs()
    if scheduler.SCHEDULER is not None:
        scheduler.schedule_strategy(
            strategy_id, "09:15", "15:10", ["mon", "tue", "wed", "thu", "fri"]
        )
    return strategy_id
