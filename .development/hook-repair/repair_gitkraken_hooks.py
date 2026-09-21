"""Repair the observed PowerShell quoting error without changing hook behavior."""

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

TARGET = Path("C:/Users/nikhi/.codex/plugins/cache/gitkraken/gitkraken-hooks/3.1.72/hooks/hooks.json")
EXE = "C:/Users/nikhi/AppData/Local/GitKrakenCLI/gk.exe"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    original = TARGET.read_bytes()
    document = json.loads(original)
    changes = []
    commands = set()
    for event, groups in document["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                old = hook["command"]
                prefix = f'"{EXE}" '
                if not old.startswith(prefix):
                    raise RuntimeError(f"Unexpected command for {event}; refusing to edit")
                new = EXE + " " + old[len(prefix):]
                hook["command"] = new
                changes.append(event)
                commands.add(new)
    if not Path(EXE).is_file() or " " in EXE:
        raise RuntimeError("Executable must exist and its unquoted path must not contain spaces")
    for command in sorted(commands):
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command + " --help"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
    print(f"Validated {len(commands)} command variants across {len(changes)} hook events")
    print('Change: remove executable-path quotes; preserve host, blocking, matchers and timeouts')
    if not args.apply:
        print("Preview only; no plugin files changed")
        return
    if TARGET.read_bytes() != original:
        raise RuntimeError("Hook file changed concurrently")
    backup = TARGET.with_name("hooks.json.before-powershell-fix-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".bak")
    with backup.open("xb") as handle:
        handle.write(original)
    replacement = (json.dumps(document, indent=2) + "\n").encode("utf-8")
    TARGET.write_bytes(replacement)
    assert json.loads(TARGET.read_bytes()) == document
    print("Updated:", TARGET)
    print("Backup:", backup)


if __name__ == "__main__":
    main()
