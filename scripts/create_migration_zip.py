"""Archive this stopped installation, including private files, outside the repo.

No app imports, database writes, broker calls or dependency installation. The ZIP
is private and unencrypted. Every member is read back and SHA-256 verified.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", ".numba_cache", ".llvm_tmp",
}
EXCLUDED_FILES = {".DS_Store", "Thumbs.db"}
BLOCK = 1024 * 1024


def signature(path):
    s = path.stat()
    return s.st_size, s.st_mtime_ns, s.st_ino


def inventory():
    result = {}
    for current, directories, names in os.walk(ROOT, followlinks=False):
        for name in directories + names:
            path = Path(current) / name
            if name not in EXCLUDED_DIRS and path.is_symlink():
                raise RuntimeError(f"Review symlink before archiving: {path}")
        directories[:] = sorted(d for d in directories if d not in EXCLUDED_DIRS)
        for name in sorted(names):
            path = Path(current) / name
            if name in EXCLUDED_FILES or path.suffix == ".pyc":
                continue
            result[path.relative_to(ROOT).as_posix()] = signature(path)
    return result


def check_stopped():
    for port in (5000, 8765):
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Port {port} is active; do not archive a live installation")


def digest_stream(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(BLOCK), b""):
        digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("Keep the migration ZIP outside the project being deleted")
    partial = output.with_suffix(output.suffix + ".partial")
    checksum = output.with_suffix(output.suffix + ".sha256")
    evidence = output.with_suffix(output.suffix + ".verification.json")
    for path in (output, partial, checksum, evidence):
        if path.exists():
            raise FileExistsError(path)
    check_stopped()
    files = inventory()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    print(f"Archiving {len(files):,} files / {sum(s[0] for s in files.values()) / 1024**3:.2f} GiB", flush=True)
    started = time.monotonic()
    metadata = {}
    os.umask(0o077)
    with partial.open("xb") as destination:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=3, allowZip64=True) as archive:
            for i, (name, before) in enumerate(files.items(), 1):
                path = ROOT / name
                if signature(path) != before:
                    raise RuntimeError(f"Source changed before copying: {name}")
                info = zipfile.ZipInfo.from_file(path, arcname=f"OpenAlgo_Mac/{name}")
                info.compress_type = zipfile.ZIP_DEFLATED
                info._compresslevel = 3
                digest = hashlib.sha256()
                with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as target:
                    for chunk in iter(lambda: source.read(BLOCK), b""):
                        digest.update(chunk)
                        target.write(chunk)
                if signature(path) != before:
                    raise RuntimeError(f"Source changed while copying: {name}")
                metadata[name] = {"bytes": before[0], "sha256": digest.hexdigest()}
                if i % 10000 == 0:
                    print(f"Copied {i:,}/{len(files):,}", flush=True)
            manifest = {"git_commit": commit, "files": metadata,
                        "excluded_directories": sorted(EXCLUDED_DIRS),
                        "excluded_files": sorted(EXCLUDED_FILES) + ["*.pyc"],
                        "private_unencrypted": True}
            archive.writestr("MIGRATION_MANIFEST.json", json.dumps(manifest, indent=2))
        destination.flush()
        os.fsync(destination.fileno())
    if inventory() != files:
        raise RuntimeError("Source inventory changed during archive; partial ZIP not published")
    check_stopped()
    print("Reading back every ZIP member and verifying SHA-256...", flush=True)
    with zipfile.ZipFile(partial) as archive:
        assert len(archive.infolist()) == len(files) + 1
        assert json.loads(archive.read("MIGRATION_MANIFEST.json")) == manifest
        for i, (name, expected) in enumerate(metadata.items(), 1):
            info = archive.getinfo(f"OpenAlgo_Mac/{name}")
            assert info.file_size == expected["bytes"], name
            with archive.open(info) as source:
                assert digest_stream(source) == expected["sha256"], name
            if i % 10000 == 0:
                print(f"Verified {i:,}/{len(files):,}", flush=True)
    # Ensure high-value private data and saved schedules match the original,
    # independently of the hashes computed during ZIP creation.
    private = [n for n in files if n.startswith(("db/", "keys/")) or
               n in {".env", "strategies/strategy_configs.json"}]
    for name in private:
        with (ROOT / name).open("rb") as source:
            assert digest_stream(source) == metadata[name]["sha256"], name
    with partial.open("rb") as source:
        zip_hash = digest_stream(source)
    # Link refuses replacement if another archive appeared during this run.
    os.link(partial, output)
    partial.unlink()
    checksum.write_text(f"{zip_hash}  {output.name}\n")
    report = {"verified": True, "git_commit": commit, "files": len(files),
              "source_bytes": sum(s[0] for s in files.values()),
              "zip_bytes": output.stat().st_size, "sha256": zip_hash,
              "private_files_rehashed": len(private),
              "elapsed_seconds": round(time.monotonic() - started, 1)}
    evidence.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    print(f"Verified private archive: {output}", flush=True)


if __name__ == "__main__":
    main()
