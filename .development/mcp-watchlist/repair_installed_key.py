"""Repair this installation's stale local MCP key without rotating the app key.

Requires exactly one stored API key, and matching OpenCode/private-file keys.
Prints no credentials. Run only after reviewing these installation-specific checks.
"""

import json
import os
import sys
import tempfile
import tomllib
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from database.auth_db import PEPPER, ApiKeys, db_session, decrypt_token, ph


def replace_private(path, content):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    key_path = Path.home() / ".config/openalgo/mcp-api-key"
    opencode_path = Path.home() / ".config/opencode/opencode.json"
    assert not key_path.is_symlink() and not opencode_path.is_symlink()
    config = json.loads(opencode_path.read_text())
    command = config["mcp"]["openalgo"]["command"]
    assert len(command) == 4 and Path(command[1]).resolve() == ROOT / "mcp/mcpserver.py"
    assert command[3].rstrip("/") in ("http://127.0.0.1:5000", "http://localhost:5000")
    assert key_path.read_text().strip() == command[2]
    codex = tomllib.loads((Path.home() / ".codex/config.toml").read_text())
    assert str(key_path) in codex["mcp_servers"]["openalgo"]["args"]
    try:
        rows = ApiKeys.query.all()
        assert len(rows) == 1, "Cannot select an owner automatically"
        key = decrypt_token(rows[0].api_key_encrypted)
        assert key and ph.verify(rows[0].api_key_hash, key + PEPPER)
    finally:
        db_session.remove()
    command[2] = key
    replace_private(opencode_path, json.dumps(config, indent=2) + "\n")
    replace_private(key_path, key + "\n")
    print("Existing application key installed for OpenCode and Codex; no key rotated or printed.")


if __name__ == "__main__":
    main()
