"""Verify schedules, or install offline during an explicitly authorized restart."""

import argparse
import hashlib
import json
import os
from datetime import datetime

from .engine import IST
from .profiles import PROFILES, ROOT


def expected():
    return {
        key: {
            "file": key + ".py",
            "schedule_start": "09:15",
            "schedule_stop": "15:40",
            "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
            "exchange": "NFO",
        }
        for key in PROFILES
    }


def verify():
    saved = json.loads((ROOT / "strategies/strategy_configs.json").read_text())
    result = {}
    for key, required in expected().items():
        matches = [
            value
            for value in saved.values()
            if key in str(value.get("file_name", "")) or key == value.get("name")
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one installed schedule for {key}; found {len(matches)}")
        actual = matches[0]
        if not actual.get("is_scheduled") or any(
            actual.get(k) != value for k, value in required.items() if k != "file"
        ):
            raise RuntimeError("Schedule mismatch: " + key)
        result[key] = {
            k: actual.get(k)
            for k in (
                "is_scheduled",
                "schedule_start",
                "schedule_stop",
                "schedule_days",
                "is_running",
            )
        }
    return result


def install_offline():
    import psutil

    for process in psutil.process_iter(["cmdline", "cwd"]):
        command = process.info.get("cmdline") or []
        if any(arg == "app.py" or arg.endswith("/app.py") for arg in command):
            if process.info.get("cwd") == str(ROOT):
                raise RuntimeError("Stop OpenAlgo before installing offline schedules")
    path = ROOT / "strategies/strategy_configs.json"
    original = path.read_bytes()
    saved = json.loads(original)
    owners = {c.get("user_id") for c in saved.values() if c.get("user_id")}
    if len(owners) != 1:
        raise RuntimeError("Exactly one existing scheduler owner is required")
    owner = owners.pop()
    suffix = hashlib.sha256(owner.encode()).hexdigest()[:12]
    now = datetime.now(IST).isoformat()
    updated = dict(saved)
    for key, required in expected().items():
        source = ROOT / "strategies" / required["file"]
        if not source.is_file():
            raise RuntimeError("Missing strategy launcher: " + key)
        sid = "Nifty12_" + key + "_" + suffix
        previous = saved.get(sid, {})
        if previous and (previous.get("user_id") != owner or previous.get("is_running")):
            raise RuntimeError("Existing schedule ownership/running state prevents replacement")
        updated[sid] = {
            **previous,
            **{k: v for k, v in required.items() if k != "file"},
            "name": key,
            "file_path": str(source),
            "file_name": source.name,
            "user_id": owner,
            "is_running": False,
            "is_scheduled": True,
            "manually_stopped": False,
            "created_at": previous.get("created_at", now),
        }
    audit_dir = ROOT / "db/nifty_options"
    audit_dir.mkdir(parents=True, exist_ok=True)
    backup = audit_dir / (
        "schedules-before-" + datetime.now(IST).strftime("%Y%m%d-%H%M%S") + ".json"
    )
    backup.write_bytes(original)
    os.chmod(backup, 0o600)
    temp = path.with_suffix(".nifty12.tmp")
    with temp.open("w") as stream:
        json.dump(updated, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    verify()
    reread = json.loads(path.read_text())
    assert all(
        reread[key] == value for key, value in saved.items() if not key.startswith("Nifty12_")
    )
    return {"installed": 12, "total_schedules": len(reread), "backup": str(backup)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-offline", action="store_true")
    args = parser.parse_args()
    print(json.dumps(install_offline() if args.install_offline else verify(), indent=2))
