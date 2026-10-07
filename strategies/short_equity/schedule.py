"""Prepare schedules offline. This module never imports or starts the scheduler."""

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from .profiles import PROFILES


def configurations(owner, project_root):
    if not isinstance(owner, str) or not owner:
        raise ValueError("A saved schedule owner is required")
    suffix = hashlib.sha256(owner.encode()).hexdigest()[:12]
    return {
        f"Short10K_{profile_id}_{suffix}": {
            "name": profile["name"],
            "file_path": str(Path(project_root).resolve() / "strategies" / profile["file"]),
            "file_name": profile["file"],
            "exchange": "NSE",
            "user_id": owner,
            "is_running": False,
            "is_scheduled": True,
            "manually_stopped": False,
            "schedule_start": "09:15",
            "schedule_stop": "15:15",
            "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
        }
        for profile_id, profile in PROFILES.items()
    }


def merge_configurations(existing, desired):
    """Add only. Conflicting IDs fail; every existing value is preserved."""
    merged = deepcopy(existing)
    for strategy_id, config in desired.items():
        if strategy_id in merged:
            if any(merged[strategy_id].get(k) != v for k, v in config.items()):
                raise ValueError(f"Refusing to replace an existing schedule: {strategy_id}")
        else:
            merged[strategy_id] = deepcopy(config)
    return merged


def prepare(project_root, output_dir):
    project_root, output_dir = Path(project_root).resolve(), Path(output_dir).resolve()
    permitted = (
        project_root / ".development" / "equity-shorts" / "schedules",
        project_root / "log" / "test",
    )
    if not any(output_dir.is_relative_to(p) for p in permitted):
        raise ValueError("Schedule output must stay in the isolated development/test directory")
    source = project_root / "strategies" / "strategy_configs.json"
    raw = source.read_bytes()
    existing = json.loads(raw)
    owners = {c["user_id"] for c in existing.values()}
    if len(owners) != 1:
        raise ValueError("Expected one owner in saved schedules")
    desired = configurations(owners.pop(), project_root)
    merged = merge_configurations(existing, desired)
    if source.read_bytes() != raw:
        raise RuntimeError("Saved schedules changed while preparing; rerun the preview")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("short-schedules.json", desired),
        ("strategy_configs.json", merged),
        (
            "manifest.json",
            {
                "status": "STAGED_ONLY",
                "existing_count": len(existing),
                "new_short_count": len(desired),
                "combined_count": len(merged),
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "note": "Regenerate from current saved schedules after the user stops OpenAlgo; do not copy a stale combined preview.",
            },
        ),
    ):
        path = output_dir / name
        if path.is_symlink():
            raise ValueError("Refusing a symlink output")
        path.write_text(json.dumps(payload, indent=2) + "\n")
    return len(existing), len(desired), len(merged)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    before, added, combined = prepare(args.project_root, args.output_dir)
    print(
        f"Staged {added} short schedules alongside {before} saved schedules ({combined} total). Nothing activated."
    )


if __name__ == "__main__":
    main()
