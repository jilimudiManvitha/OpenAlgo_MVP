"""Import local stock/index/sector memberships; no broker calls or orders."""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from database.engine_factory import create_db_engine
    from services.stock_categories import SOURCE_DIR, load_catalog, save_catalog

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_DIR)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("SCANNER_LIVE_DB", ROOT / "db/market_scanner_live.db")),
    )
    parser.add_argument("--master-db", type=Path, default=ROOT / "db/openalgo.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    catalog = load_catalog(args.source, args.master_db)
    backup = None
    if not args.dry_run:
        args.database.parent.mkdir(parents=True, exist_ok=True)
        if args.database.exists():
            backup_dir = args.database.parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            backup = backup_dir / (
                "stock-categories-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".db"
            )
            source = sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)
            destination = sqlite3.connect(backup)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
        engine = create_db_engine("sqlite:///" + args.database.resolve().as_posix())
        try:
            save_catalog(engine, catalog)
        finally:
            engine.dispose()
    print(
        json.dumps(
            {
                "database": str(args.database),
                "dry_run": args.dry_run,
                "backup": str(backup) if backup else None,
                "unique_symbols": len(catalog["instruments"]),
                "memberships": sum(len(c["symbols"]) for c in catalog["categories"].values()),
                "categories": {key: c["count"] for key, c in catalog["categories"].items()},
                "files": catalog["files"],
                "issues": catalog["issues"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
