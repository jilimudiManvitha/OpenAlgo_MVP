"""Real scheduler persistence must never write the operator's configuration in pytest."""

import json
import os
from pathlib import Path


def test_scheduler_config_writes_use_the_isolated_directory(monkeypatch):
    from blueprints import python_strategy as scheduler

    operator_file = Path(__file__).resolve().parents[1] / "strategies/strategy_configs.json"
    target = scheduler.CONFIG_FILE.resolve()
    assert target != operator_file
    assert target.is_relative_to(Path(os.environ["PYTHON_STRATEGY_DATA_DIR"]).resolve())
    before = operator_file.read_bytes() if operator_file.exists() else None
    previous = target.read_bytes() if target.exists() else None
    try:
        monkeypatch.setattr(scheduler, "STRATEGY_CONFIGS", {"isolation_probe": {"is_scheduled": False}})
        scheduler.save_configs()
        assert json.loads(target.read_text()) == {"isolation_probe": {"is_scheduled": False}}
        assert (operator_file.read_bytes() if operator_file.exists() else None) == before
    finally:
        if previous is not None:
            target.write_bytes(previous)
        else:
            target.unlink(missing_ok=True)
