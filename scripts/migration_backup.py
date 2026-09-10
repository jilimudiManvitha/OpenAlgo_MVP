"""Create/restore authenticated, split migration backups (credentials never enter Git).

Each compressed archive part is encrypted with AES-256-GCM. The encrypted manifest
authenticates part order, ciphertext hashes, archive hash, and individual file hashes.
Keep the generated key file separately from the backup/repository.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import uuid
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BLOCK = 1024 * 1024
PART_SIZE = 512 * BLOCK
MAGIC = b"OAMIG1"


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(BLOCK), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PartWriter:
    def __init__(self, output, key, backup_id, part_size=PART_SIZE):
        self.output, self.key, self.backup_id = output, key, backup_id
        self.part_size = part_size
        self.parts = []
        self.stream = None
        self.digest = hashlib.sha256()

    def _open(self):
        self.name = f"data-{len(self.parts) + 1:05d}.enc"
        self.stream = (self.output / self.name).open("xb")
        nonce = os.urandom(12)
        self.stream.write(MAGIC + nonce)
        self.encryptor = Cipher(algorithms.AES(self.key), modes.GCM(nonce)).encryptor()
        self.encryptor.authenticate_additional_data(f"{self.backup_id}:{self.name}".encode())
        self.count = 0

    def _close(self):
        if self.stream is None:
            return
        self.stream.write(self.encryptor.finalize())
        self.stream.write(self.encryptor.tag)
        self.stream.close()
        path = self.output / self.name
        self.parts.append(
            {"name": self.name, "size": path.stat().st_size, "sha256": file_hash(path)}
        )
        print(f"Sealed {self.name}: {path.stat().st_size / BLOCK:.1f} MiB", flush=True)
        self.stream = None

    def write(self, data):
        self.digest.update(data)
        total = len(data)
        view = memoryview(data)
        while view:
            if self.stream is None:
                self._open()
            count = min(len(view), self.part_size - self.count)
            self.stream.write(self.encryptor.update(view[:count]))
            self.count += count
            view = view[count:]
            if self.count == self.part_size:
                self._close()
        return total

    def finish(self):
        self._close()


class HashReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, count):
        data = self.stream.read(count)
        self.digest.update(data)
        return data


def select_private_files(root):
    files = set()
    for name in (
        ".env",
        ".flaskenv",
        "config.ini",
        ".claude/settings.json",
        ".claude/settings.local.json",
    ):
        if (root / name).is_file():
            files.add(name)
    for directory in ("db", "keys", "log", ".cloudflared", ".vscode", "tmp"):
        base = root / directory
        if not base.exists():
            continue
        for current, dirs, names in os.walk(base, followlinks=False):
            dirs[:] = [
                name
                for name in dirs
                if name not in {"test", "__pycache__"} and not name.startswith("pytest-")
            ]
            for name in names:
                path = Path(current) / name
                rel = path.relative_to(root).as_posix()
                if (
                    path.is_symlink()
                    or "-test.db" in name
                    or name.endswith((".db-wal", ".db-shm", ".db-journal", ".pyc"))
                ):
                    continue
                if name in {".gitignore", "readme.txt", "README.md", "readme.md"}:
                    continue
                files.add(rel)
    return sorted(files)


def create_backup(root, output, key_file, paths=None, part_size=PART_SIZE):
    root, output, key_file = root.resolve(), output.resolve(), key_file.resolve()
    output.mkdir(parents=True, exist_ok=False)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    with key_file.open("x", encoding="ascii") as stream:
        stream.write(base64.urlsafe_b64encode(key).decode() + "\n")
    backup_id = uuid.uuid4().hex
    selected = select_private_files(root) if paths is None else paths
    metadata = []
    writer = PartWriter(output, key, backup_id, part_size)
    with ExitStack() as stack:
        staging = Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="sqlite-", dir=output.parent))
        )
        prepared = []
        for name in selected:
            original = (root / name).resolve()
            if not original.is_relative_to(root) or not original.is_file():
                raise ValueError(f"Unsafe or missing source: {name}")
            source = original
            if original.suffix == ".duckdb":
                import duckdb

                # Hold a read-only database lock throughout the filesystem copy.
                # This refuses a cross-process active writer rather than backing up
                # an inconsistent live database. Stop OpenAlgo before retrying.
                connection = duckdb.connect(str(original), read_only=True)
                stack.callback(connection.close)
                if original.with_suffix(original.suffix + ".wal").exists():
                    raise RuntimeError(
                        "DuckDB has an uncheckpointed WAL. Close OpenAlgo cleanly first."
                    )
            elif original.suffix in {".db", ".sqlite", ".sqlite3"}:
                source = staging / name
                source.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)
                destination = sqlite3.connect(source)
                try:
                    connection.backup(destination)
                finally:
                    destination.close()
                    connection.close()
            prepared.append((name, source))
        with tarfile.open(fileobj=writer, mode="w|gz", compresslevel=1) as archive:
            for name, source in prepared:
                before = source.stat()
                info = tarfile.TarInfo(name)
                info.size = before.st_size
                info.mode = 0o600
                info.mtime = int(before.st_mtime)
                print(f"Backing up {name} ({before.st_size / BLOCK:.1f} MiB)", flush=True)
                with source.open("rb") as stream:
                    reader = HashReader(stream)
                    archive.addfile(info, reader)
                after = source.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError(f"Source changed during backup: {name}")
                metadata.append(
                    {"path": name, "size": info.size, "sha256": reader.digest.hexdigest()}
                )
        writer.finish()
    manifest = {
        "backup_id": backup_id,
        "parts": writer.parts,
        "files": metadata,
        "archive_sha256": writer.digest.hexdigest(),
    }
    nonce = os.urandom(12)
    sealed = AESGCM(key).encrypt(
        nonce, json.dumps(manifest, sort_keys=True).encode(), backup_id.encode()
    )
    envelope = {
        "version": 1,
        "backup_id": backup_id,
        "nonce": nonce.hex(),
        "encrypted_manifest": base64.b64encode(sealed).decode(),
    }
    (output / "manifest.json").write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    print(
        f"Backup complete: {len(metadata)} files, {len(writer.parts)} encrypted parts.", flush=True
    )
    print(f"Recovery key file (keep separately): {key_file}", flush=True)
    return manifest


def read_manifest(backup, key_file):
    key = base64.urlsafe_b64decode(key_file.read_text(encoding="ascii").strip())
    if len(key) != 32:
        raise ValueError("Recovery key must decode to 32 bytes")
    envelope = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    if envelope["version"] != 1:
        raise ValueError("Unsupported backup format")
    raw = AESGCM(key).decrypt(
        bytes.fromhex(envelope["nonce"]),
        base64.b64decode(envelope["encrypted_manifest"]),
        envelope["backup_id"].encode(),
    )
    manifest = json.loads(raw)
    if manifest["backup_id"] != envelope["backup_id"]:
        raise ValueError("Backup identity mismatch")
    return key, manifest


def restore_backup(backup, key_file, destination, verify_only=False):
    backup, key_file, destination = backup.resolve(), key_file.resolve(), destination.resolve()
    key, manifest = read_manifest(backup, key_file)
    # Verify and decrypt to a temporary archive before extracting anything.
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="migration-restore-", dir=destination) as temporary:
        archive_path = Path(temporary) / "backup.tar.gz"
        archive_digest = hashlib.sha256()
        with archive_path.open("wb") as target:
            for part in manifest["parts"]:
                if Path(part["name"]).name != part["name"]:
                    raise ValueError("Unsafe part name")
                path = backup / part["name"]
                if path.stat().st_size != part["size"] or file_hash(path) != part["sha256"]:
                    raise ValueError(f"Damaged or missing backup part: {part['name']}")
                with path.open("rb") as source:
                    if source.read(len(MAGIC)) != MAGIC:
                        raise ValueError("Invalid encrypted part")
                    nonce = source.read(12)
                    source.seek(-16, io.SEEK_END)
                    tag = source.read(16)
                    source.seek(len(MAGIC) + 12)
                    decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
                    decryptor.authenticate_additional_data(
                        f"{manifest['backup_id']}:{part['name']}".encode()
                    )
                    remaining = part["size"] - len(MAGIC) - 12 - 16
                    while remaining:
                        chunk = source.read(min(BLOCK, remaining))
                        if not chunk:
                            raise ValueError("Truncated encrypted part")
                        remaining -= len(chunk)
                        plain = decryptor.update(chunk)
                        archive_digest.update(plain)
                        target.write(plain)
                    decryptor.finalize()
                print(f"Verified {part['name']}", flush=True)
        if archive_digest.hexdigest() != manifest["archive_sha256"]:
            raise ValueError("Archive hash mismatch")
        expected = {item["path"]: item for item in manifest["files"]}
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) != len(expected) or {member.name for member in members} != set(
                expected
            ):
                raise ValueError("Archive file inventory mismatch")
            to_extract = []
            for member in members:
                relative = PurePosixPath(member.name)
                target = (destination / member.name).resolve()
                if (
                    not member.isfile()
                    or relative.is_absolute()
                    or ".." in relative.parts
                    or not target.is_relative_to(destination)
                ):
                    raise ValueError("Unsafe archive member")
                exists = target.exists()
                if not verify_only and exists:
                    if not target.is_file() or file_hash(target) != expected[member.name]["sha256"]:
                        raise FileExistsError(f"Refusing to overwrite existing file: {target}")
                with archive.extractfile(member) as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if (
                    digest != expected[member.name]["sha256"]
                    or member.size != expected[member.name]["size"]
                ):
                    raise ValueError(f"File hash mismatch: {member.name}")
                if not exists:
                    to_extract.append(member)
            if not verify_only:
                archive.extractall(destination, members=to_extract, filter="data")
        print(f"{'Verified' if verify_only else 'Restored'} {len(expected)} files.", flush=True)
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["create", "restore", "verify"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "create":
        create_backup(args.root, args.backup, args.key_file)
    else:
        restore_backup(args.backup, args.key_file, args.root, args.mode == "verify")


if __name__ == "__main__":
    main()
