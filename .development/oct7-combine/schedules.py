"""Offline October 7 schedule migration. Default is read-only verification."""

import argparse
import ast
import hashlib
import json
import os
import socket
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.short_equity.schedule import configurations


def verify(saved):
    assert len(saved) == 28, f"Expected 28 schedules, found {len(saved)}"
    assert sum(c["exchange"] == "NSE" for c in saved.values()) == 16
    assert sum(c["exchange"] == "NFO" for c in saved.values()) == 12
    for config in saved.values():
        assert config["is_scheduled"] and not config.get("manually_stopped")
        assert config["schedule_start"] == "09:15"
        assert config["schedule_stop"] == ("15:15" if config["exchange"] == "NSE" else "15:40")
        assert config["schedule_days"] == ["mon", "tue", "wed", "thu", "fri"]
        source = Path(config["file_path"])
        assert source.parent == ROOT / "strategies"
        ast.parse(source.read_text(), filename=str(source))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = ROOT / "strategies/strategy_configs.json"
    raw = path.read_bytes()
    original = json.loads(raw)
    saved = json.loads(raw)
    if args.apply:
        for port in (5000, 8765):
            with socket.socket() as probe:
                probe.settimeout(0.5)
                assert probe.connect_ex(("127.0.0.1", port)) != 0, "Stop OpenAlgo first"
        assert len(saved) in (20, 28)
        assert not any(c.get("is_running") for c in saved.values())
        owners = {c["user_id"] for c in saved.values()}
        assert len(owners) == 1
        desired = configurations(owners.pop(), ROOT)
        for config in saved.values():
            if config["exchange"] == "NSE":
                config["schedule_stop"] = "15:15"
        for key, config in desired.items():
            if key in saved:
                assert saved[key] == config, "Existing short configuration differs"
            else:
                saved[key] = config
        verify(saved)
        for key, old in original.items():
            expected = dict(old)
            if old["exchange"] == "NSE":
                expected["schedule_stop"] = "15:15"
            assert saved[key] == expected
        backup = ROOT / "log/test/oct7-combine" / ("schedules-before-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(raw)
        backup.chmod(0o600)
        assert path.read_bytes() == raw, "Schedules changed during migration"
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
            temp_path = Path(output.name)
            json.dump(saved, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, path)
    verify(saved)
    print(json.dumps({"schedules": len(saved), "equity_stop": "15:15 IST", "option_schedules": 12,
                      "applied": args.apply, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
