"""Build optional Rust math / Go baseline binaries for this computer."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    native = Path(__file__).with_name("native")
    suffix = ".dylib" if sys.platform == "darwin" else ".dll" if sys.platform == "win32" else ".so"
    rust = shutil.which("rustc")
    go = shutil.which("go")
    if not rust or not go:
        raise SystemExit("Install rustc and Go, then rerun; Python fallbacks remain available.")
    subprocess.run(
        [
            rust,
            "--edition",
            "2024",
            "--crate-type",
            "cdylib",
            "-O",
            str(native / "bands.rs"),
            "-o",
            str(native / ("libbands" + suffix)),
        ],
        check=True,
    )
    subprocess.run(
        [
            go,
            "build",
            "-o",
            str(native / ("baseline-fetch.exe" if os.name == "nt" else "baseline-fetch")),
            str(native / "baseline_fetch.go"),
        ],
        check=True,
    )
    print("Built native kernels for", sys.platform)


if __name__ == "__main__":
    main()
