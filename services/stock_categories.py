"""Offline, provenance-preserving stock category imports. No broker/network calls."""

import csv
import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "Stock_Symbols"
INDEXES = {
    "nifty50": "Nifty 50",
    "nifty100": "Nifty 100",
    "niftynext50": "Nifty Next 50",
    "niftymidcap50": "Nifty Midcap 50",
    "niftymidcap100": "Nifty Midcap 100",
    "niftymidcap150": "Midcap · Nifty Midcap 150",
    "niftysmallcap100": "Nifty Smallcap 100",
    "niftysmallcap250": "Smallcap · Nifty Smallcap 250",
    "nifty200": "Nifty 200",
    "nifty500": "Nifty 500",
    "nifty500multicap502525": "Nifty 500 Multicap 50:25:25",
}
SECTOR_FILES = {
    "Dhan - Cement Stocks.csv": ("cement", "Cement stocks"),
    "Dhan - Nifty Bank.csv": ("niftybank", "Nifty Bank"),
    "Dhan - Nifty Fin Services.csv": ("niftyfinancialservices", "Nifty Financial Services"),
    "Dhan - Nifty Fmcg.csv": ("niftyfmcg", "Nifty FMCG"),
    "Dhan - Nifty Healthcare.csv": ("niftyhealthcare", "Nifty Healthcare"),
    "Dhan - Nifty It.csv": ("niftyit", "Nifty IT"),
    "Dhan - Nifty Metal.csv": ("niftymetal", "Nifty Metal"),
    "Dhan - Nifty Pharma.csv": ("niftypharma", "Nifty Pharma"),
    "Dhan - Nifty Realty.csv": ("niftyrealty", "Nifty Realty"),
    "Nifty Auto.csv": ("niftyauto", "Nifty Auto"),
    "MW-NIFTY-AUTO.csv": ("niftyauto", "Nifty Auto"),
    "Nifty Media (NIFTYMED).csv": ("niftymedia", "Nifty Media"),
    "Nifty PSU Bank (NIFTYPSU).csv": ("niftypsubank", "Nifty PSU Bank"),
    "Nifty Private Bank (NIFPVTBNK).csv": ("niftyprivatebank", "Nifty Private Bank"),
}
# Explicit abbreviations reviewed against this installation's NSE symbol master.
# These map source company names; they never rewrite historical ticker symbols.
NAME_ALIASES = {
    "Ramco Cements": "RAMCOCEM",
    "Heidelberg Cement": "HEIDELBERG",
    "Shree Digvijay Cement Company": "SHREDIGCEM",
    "Anjani Portland Cement": "APCL",
    "Barak Valley Cements": "BVCL",
    "Kakatiya Cement Sugar & Industries": "KAKATCEM",
    "Kotak Bank": "KOTAKBANK",
    "SBI Life Insurance": "SBILIFE",
    "Cholamandalam Investment": "CHOLAFIN",
    "HDFC Life Insurance": "HDFCLIFE",
    "ICICI Lombard General Insurance": "ICICIGI",
    "SBI Cards": "SBICARD",
    "Nestle": "NESTLEIND",
    "Sun Pharmaceutical": "SUNPHARMA",
    "Apollo Hospitals": "APOLLOHOSP",
    "Zydus Life Science": "ZYDUSLIFE",
    "Abbott": "ABBOTINDIA",
    "NALCO": "NATIONALUM",
    "Maruti Suzuki": "MARUTI",
    "TVS Motors": "TVSMOTOR",
    "Tube Investment": "TIINDIA",
    "Network18 Media & Investments": "NETWORK18",
    "Zee Entertainment": "ZEEL",
    "CBI": "CENTRALBK",
    "SBI": "SBIN",
}


def name_key(value):
    value = re.sub(r"\b(ltd|limited)\b", "", value.lower()).replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", value)


def symbol_key(value):
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9&.\-]*", value) or not re.search(r"[A-Z]", value):
        raise ValueError(f"Invalid NSE equity symbol: {value!r}")
    return value


def load_catalog(root=None, master_db=None):
    root = Path(root) if root is not None else SOURCE_DIR
    if not root.is_dir():
        raise ValueError(f"Stock category source folder does not exist: {root}")
    stamp = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    categories, instruments, files, issues, resolutions = {}, {}, [], [], []
    names = defaultdict(set)
    hashes = {}

    def register(symbol, name="", industry="", isin=""):
        symbol = symbol_key(symbol)
        item = instruments.setdefault(symbol, {"symbol": symbol, "exchange": "NSE"})
        for key, value in (("name", name), ("industry", industry), ("isin", isin)):
            if value:
                item.setdefault(key, value)
        if name:
            names[name_key(name)].add(symbol)
        return symbol

    def add(key, label, kind, symbols, sources, **extra):
        symbols = sorted(set(symbols))
        if not symbols:
            raise ValueError(f"Refusing empty category: {key}")
        source_hashes = {s: hashes[s] for s in sources}
        categories[key] = dict(
            label=label,
            kind=kind,
            symbols=symbols,
            count=len(symbols),
            source=", ".join(sources),
            source_hashes=source_hashes,
            sha256=(
                next(iter(source_hashes.values()))
                if len(source_hashes) == 1
                else hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest()
            ),
            imported_at=stamp,
            effective_date=None,
            **extra,
        )

    csv_rows = {}
    for path in sorted(root.glob("*")):
        if path.suffix.lower() not in {".csv", ".txt"}:
            continue
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        record = {"source": path.name, "sha256": hashes[path.name], "status": "pending"}
        files.append(record)
        if path.name.startswith("hist_india_vix_"):
            record["status"] = "excluded_price_history"
            continue
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as handle:
                csv_rows[path.name] = list(csv.DictReader(handle))

    # Explicit index tickers take precedence over name-only exports and broker names.
    for filename, rows in csv_rows.items():
        if not filename.startswith("ind_"):
            continue
        key = filename[4:].removesuffix(".csv").replace("_", "").removesuffix("list").lower()
        symbols = []
        for row in rows:
            if row.get("Series", "EQ").strip().upper() != "EQ":
                continue
            symbols.append(
                register(
                    row["Symbol"],
                    row.get("Company Name", ""),
                    row.get("Industry", ""),
                    row.get("ISIN Code", ""),
                )
            )
        add(key, INDEXES.get(key, key), "index", symbols, [filename])

    # Read-only master supplies exact identity for companies outside the Nifty 500.
    master = Path(master_db) if master_db else ROOT / "db/openalgo.db"
    master_names = {}
    if master.is_file():
        connection = sqlite3.connect(master.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            for symbol, name in connection.execute(
                "SELECT symbol,name FROM symtoken WHERE exchange='NSE' AND instrumenttype='EQ'"
            ):
                names[name_key(name or "")].add(symbol)
                master_names[symbol] = name or ""
        finally:
            connection.close()

    for filename, (key, label) in SECTOR_FILES.items():
        if filename not in csv_rows:
            continue
        symbols = []
        for row in csv_rows[filename]:
            if "SYMBOL" in row:
                if row["SYMBOL"].startswith("NIFTY "):
                    continue
                symbol = symbol_key(row["SYMBOL"])
            else:
                name = row["Name"].strip()
                matches = names.get(name_key(name), set())
                symbol = NAME_ALIASES.get(name)
                if symbol is None and len(matches) == 1:
                    symbol = next(iter(matches))
                if symbol is None:
                    issues.append({"source": filename, "name": name, "reason": "unresolved_name"})
                    continue
                resolutions.append(
                    {
                        "source": filename,
                        "name": name,
                        "symbol": symbol,
                        "method": "reviewed_alias" if name in NAME_ALIASES else "exact_name",
                        "master_name": master_names.get(symbol),
                    }
                )
            symbols.append(register(symbol, master_names.get(symbol) or row.get("Name", "")))
        if not symbols:
            continue
        if key in categories:
            previous = categories[key]
            if set(previous["symbols"]) != set(symbols):
                # Symbol-bearing exchange export wins over a name-only snapshot.
                issues.append(
                    {
                        "source": filename,
                        "reason": "different_snapshot_membership",
                        "only_previous": sorted(set(previous["symbols"]) - set(symbols)),
                        "only_this": sorted(set(symbols) - set(previous["symbols"])),
                    }
                )
            if "SYMBOL" not in csv_rows[filename][0]:
                continue
        add(key, label, "sector_index" if key != "cement" else "sector", symbols, [filename])

    # Industry groups cover the supplied symbol-bearing CSVs, not the whole exchange.
    industries = defaultdict(list)
    for symbol, item in instruments.items():
        if item.get("industry"):
            industries[item["industry"]].append(symbol)
    index_sources = sorted(n for n in csv_rows if n.startswith("ind_"))
    for industry, symbols in sorted(industries.items()):
        key = "sector_" + re.sub(r"[^a-z0-9]+", "_", industry.lower()).strip("_")
        add(
            key,
            "Sector · " + industry,
            "industry",
            symbols,
            index_sources,
            coverage="Union of supplied index CSVs with Industry metadata",
        )

    for key, label, components in (
        ("niftylargemidcap250", "Nifty LargeMidcap 250", ["nifty100", "niftymidcap150"]),
        ("niftymidsmallcap400", "Nifty MidSmallcap 400", ["niftymidcap150", "niftysmallcap250"]),
    ):
        if key not in categories and all(c in categories for c in components):
            add(
                key,
                label,
                "derived_index",
                [s for c in components for s in categories[c]["symbols"]],
                sorted({s for c in components for s in categories[c]["source_hashes"]}),
                derivation="Union of supplied " + " + ".join(components),
            )

    # Keep download/history ticker lists separately; they contain old aliases and
    # intentionally differ from official constituent CSVs.
    for path in sorted(root.glob("*.txt")):
        if not path.name.startswith(("nifty50", "nifty500")):
            continue
        symbols = []
        with path.open(encoding="utf-8-sig") as handle:
            for line in handle:
                token = line.strip().split(",")[0].split("  (")[0].strip()
                if (
                    not token
                    or token == "Done"
                    or token.isdigit()
                    or re.match(r"^\d{4}\s+-", token)
                    or re.fullmatch(r"[=\-]+", token)
                ):
                    continue
                symbols.append(register(token))
        key = "reference_" + re.sub(r"[^a-z0-9]+", "_", path.stem.lower()).strip("_")
        add(
            key,
            "Reference · " + path.stem,
            "reference",
            symbols,
            [path.name],
            coverage="Historical/download list; not current index membership",
        )

    used = {s for c in categories.values() for s in c["source_hashes"]}
    for record in files:
        if record["status"] == "pending":
            record["status"] = "imported" if record["source"] in used else "reconciled_alternate"
    if any(i["reason"] == "unresolved_name" for i in issues):
        raise ValueError("Unresolved stock names; database unchanged: " + json.dumps(issues))
    if not categories:
        raise ValueError("No stock categories found; database unchanged")
    return {
        "categories": categories,
        "instruments": instruments,
        "files": files,
        "issues": issues,
        "name_resolutions": resolutions,
        "imported_at": stamp,
    }


def import_categories(root=None):
    """Compatibility entry point for the scanner and existing callers."""
    return load_catalog(root)["categories"]


def save_catalog(engine, catalog):
    """Atomically upsert our categories and replace only their own memberships.

    Preserve unrelated categories, all account settings and scanner snapshots.
    The JSON cache and relational tables are committed in the same transaction.
    """
    from sqlalchemy import text

    with engine.begin() as connection:
        for ddl in (
            "CREATE TABLE IF NOT EXISTS stock_categories "
            "(id TEXT PRIMARY KEY, label TEXT NOT NULL, kind TEXT NOT NULL, metadata TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS stock_category_symbols "
            "(exchange TEXT NOT NULL, symbol TEXT NOT NULL, name TEXT, industry TEXT, isin TEXT, "
            "PRIMARY KEY(exchange,symbol))",
            "CREATE TABLE IF NOT EXISTS stock_category_memberships "
            "(category_id TEXT NOT NULL REFERENCES stock_categories(id), exchange TEXT NOT NULL, "
            "symbol TEXT NOT NULL, PRIMARY KEY(category_id,exchange,symbol), "
            "FOREIGN KEY(exchange,symbol) REFERENCES stock_category_symbols(exchange,symbol))",
            "CREATE INDEX IF NOT EXISTS ix_stock_membership_symbol "
            "ON stock_category_memberships(exchange,symbol)",
            "CREATE TABLE IF NOT EXISTS stock_category_imports "
            "(imported_at TEXT PRIMARY KEY, report TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS scanner_live_categories (id INTEGER PRIMARY KEY, payload TEXT)",
        ):
            connection.execute(text(ddl))
        for symbol, item in catalog["instruments"].items():
            connection.execute(
                text(
                    "INSERT INTO stock_category_symbols VALUES(:exchange,:symbol,:name,:industry,:isin) "
                    "ON CONFLICT(exchange,symbol) DO UPDATE SET "
                    "name=COALESCE(excluded.name,stock_category_symbols.name), "
                    "industry=COALESCE(excluded.industry,stock_category_symbols.industry), "
                    "isin=COALESCE(excluded.isin,stock_category_symbols.isin)"
                ),
                {
                    "symbol": symbol,
                    "exchange": "NSE",
                    **{k: item.get(k) for k in ("name", "industry", "isin")},
                },
            )
        payload = connection.execute(
            text("SELECT payload FROM scanner_live_categories WHERE id=1")
        ).scalar()
        combined = json.loads(payload) if payload else {}
        for key, item in catalog["categories"].items():
            metadata = {k: v for k, v in item.items() if k != "symbols"}
            connection.execute(
                text(
                    "INSERT INTO stock_categories VALUES(:id,:label,:kind,:metadata) "
                    "ON CONFLICT(id) DO UPDATE SET label=:label,kind=:kind,metadata=:metadata"
                ),
                {
                    "id": key,
                    "label": item["label"],
                    "kind": item["kind"],
                    "metadata": json.dumps(metadata),
                },
            )
            connection.execute(
                text("DELETE FROM stock_category_memberships WHERE category_id=:id"), {"id": key}
            )
            connection.execute(
                text("INSERT INTO stock_category_memberships VALUES(:id,'NSE',:symbol)"),
                [{"id": key, "symbol": symbol} for symbol in item["symbols"]],
            )
        combined.update(catalog["categories"])
        connection.execute(
            text(
                "INSERT INTO scanner_live_categories VALUES(1,:payload) "
                "ON CONFLICT(id) DO UPDATE SET payload=:payload"
            ),
            {"payload": json.dumps(combined)},
        )
        report = {k: v for k, v in catalog.items() if k not in {"categories", "instruments"}}
        report["category_counts"] = {k: len(v["symbols"]) for k, v in catalog["categories"].items()}
        connection.execute(
            text(
                "INSERT INTO stock_category_imports VALUES(:stamp,:report) "
                "ON CONFLICT(imported_at) DO UPDATE SET report=:report"
            ),
            {"stamp": catalog["imported_at"], "report": json.dumps(report)},
        )
        connection.execute(
            text(
                "DELETE FROM stock_category_imports WHERE imported_at NOT IN "
                "(SELECT imported_at FROM stock_category_imports ORDER BY imported_at DESC LIMIT 50)"
            )
        )
