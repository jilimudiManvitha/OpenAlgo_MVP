"""Migration backup must recover exact data and reject corruption before restore."""

import base64
import json
import sqlite3

import pytest
from cryptography.exceptions import InvalidTag

from scripts.migration_backup import create_backup, restore_backup


@pytest.fixture
def backup(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / ".env").write_bytes(b"APP_KEY=test-value\n")
    (source / "db").mkdir()
    with sqlite3.connect(source / "db" / "sample.db") as connection:
        connection.execute("create table sample (value text)")
        connection.execute("insert into sample values ('preserve me')")
    output, key = tmp_path / "backup", tmp_path / "recovery.key"
    manifest = create_backup(source, output, key, part_size=128)
    assert len(manifest["parts"]) > 1
    assert b"test-value" not in (output / "manifest.json").read_bytes()
    return source, output, key, manifest


def test_roundtrip_and_idempotent_restore(backup, tmp_path):
    source, output, key, manifest = backup
    target = tmp_path / "restored"
    restored = restore_backup(output, key, target)
    assert restored == manifest
    assert (source / ".env").read_bytes() == (target / ".env").read_bytes()
    with sqlite3.connect(target / "db" / "sample.db") as connection:
        assert connection.execute("select value from sample").fetchone()[0] == "preserve me"
    restore_backup(output, key, target)


def test_verify_does_not_restore_files(backup, tmp_path):
    _, output, key, _ = backup
    target = tmp_path / "verify"
    restore_backup(output, key, target, verify_only=True)
    assert list(target.iterdir()) == []


def test_tampered_part_fails_before_any_file_is_restored(backup, tmp_path):
    _, output, key, manifest = backup
    part = output / manifest["parts"][0]["name"]
    content = bytearray(part.read_bytes())
    content[-1] ^= 1
    part.write_bytes(content)
    target = tmp_path / "bad"
    with pytest.raises(ValueError, match="Damaged"):
        restore_backup(output, key, target)
    assert not (target / ".env").exists()


def test_manifest_and_key_are_authenticated(backup, tmp_path):
    _, output, key, _ = backup
    wrong = tmp_path / "wrong.key"
    wrong.write_text(base64.urlsafe_b64encode(b"x" * 32).decode())
    with pytest.raises(InvalidTag):
        restore_backup(output, wrong, tmp_path / "bad")
    envelope = json.loads((output / "manifest.json").read_text())
    envelope["backup_id"] += "modified"
    (output / "manifest.json").write_text(json.dumps(envelope))
    with pytest.raises(InvalidTag):
        restore_backup(output, key, tmp_path / "bad")


def test_existing_different_settings_are_not_overwritten(backup, tmp_path):
    _, output, key, _ = backup
    target = tmp_path / "existing"
    target.mkdir()
    (target / ".env").write_text("new laptop settings")
    with pytest.raises(FileExistsError):
        restore_backup(output, key, target)
    assert (target / ".env").read_text() == "new laptop settings"
    assert not (target / "db" / "sample.db").exists()
