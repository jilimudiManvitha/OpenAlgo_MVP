"""Private read-only source DB snapshot for annual research; shares real API budget."""

import os, sqlite3, sys, tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "backtesting/nifty_options/2025-10-09_2026-10-08"


def setup(out=None, private_dir=None):
    import dotenv

    dotenv.load_dotenv(ROOT / ".env")
    dotenv.load_dotenv = lambda *a, **k: False
    dotenv.main.load_dotenv = dotenv.load_dotenv
    private = Path(private_dir) if private_dir else ROOT / "log/test/options-year/private"
    private.mkdir(parents=True, exist_ok=True)
    private.chmod(0o700)
    target = private / "auth.db"
    # A new read-only snapshot picks up the user's refreshed login on later days.
    fd, name = tempfile.mkstemp(prefix="auth-", suffix=".db", dir=private)
    os.close(fd)
    try:
        with (
            closing(
                sqlite3.connect((ROOT / "db/openalgo.db").as_uri() + "?mode=ro", uri=True)
            ) as src,
            closing(sqlite3.connect(name)) as dst,
        ):
            src.backup(dst)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    os.environ["DATABASE_URL"] = "sqlite:///" + str(target)
    os.environ["LOG_DIR"] = str(private / "logs")
    (Path(out) if out else OUT).mkdir(parents=True, exist_ok=True)
