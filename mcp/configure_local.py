"""Preview/install a local Codex MCP entry using the existing OpenCode credential.

No credential is printed or passed on a child process's command line. The
application API key is copied to a private user configuration file, not the repo.
Existing OpenCode configuration is read-only. Run without --apply to preview.
"""

import argparse
import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    source = Path.home() / ".config/opencode/opencode.json"
    entry = json.loads(source.read_text())["mcp"]["openalgo"]
    command = entry["command"]
    if len(command) != 4 or Path(command[1]).resolve() != root / "mcp/mcpserver.py":
        raise SystemExit("OpenCode must reference this repository's standard MCP command")
    key, host = command[2], command[3].rstrip("/")
    if not isinstance(key, str) or not 12 <= len(key) <= 256 or any(c.isspace() for c in key):
        raise SystemExit("OpenCode API key is not a literal valid key; use manual setup")
    if host not in ("http://127.0.0.1:5000", "http://localhost:5000"):
        raise SystemExit("Review the non-default OpenCode host before copying the configuration")
    key_dir = Path.home() / ".config/openalgo"
    key_path = key_dir / "mcp-api-key"
    config_path = Path.home() / ".codex/config.toml"
    config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    if "openalgo" in config.get("mcp_servers", {}):
        raise SystemExit("Codex already has an openalgo entry; inspect it instead of overwriting")
    executable = shutil.which("codex")
    if not executable:
        raise SystemExit("codex CLI is not installed")
    launch = [
        str(root / ".venv/bin/python3"),
        str(root / "mcp/launch_local.py"),
        "--api-key-file",
        str(key_path),
        "--host",
        host,
    ]
    print(
        json.dumps(
            {
                "client": "Codex/shared desktop configuration",
                "config": str(config_path),
                "command": launch,
                "toolsets": "all",
                "credential_source": str(source),
                "credential_destination": str(key_path),
                "apply": args.apply,
            },
            indent=2,
        )
    )
    if not args.apply:
        return
    key_dir.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        if key_path.is_symlink() or key_path.read_text().strip() != key:
            raise SystemExit("Existing key file differs or is a symlink; no overwrite performed")
        key_path.chmod(0o600)
    else:
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(key + "\n")
    command = [
        executable,
        "mcp",
        "add",
        "openalgo",
        "--env",
        "OPENALGO_MCP_READ_ONLY=0",
        "--env",
        "OPENALGO_MCP_TOOLSETS=orders,account,marketdata,research,utility,watchlists",
        "--",
        *launch,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise SystemExit(
            "Codex configuration failed; private key file retained. Inspect codex mcp settings."
        )
    updated = tomllib.loads(config_path.read_text())["mcp_servers"]["openalgo"]
    if updated["command"] != launch[0] or updated["args"] != launch[1:]:
        raise SystemExit("Codex wrote an unexpected command; inspect configuration")
    print("Configured openalgo; existing MCP entries preserved. No API key printed.")


if __name__ == "__main__":
    main()
