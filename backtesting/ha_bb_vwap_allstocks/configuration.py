import csv
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def resolve(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def load_config(path=None):
    config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    if path:
        config.update(json.loads(Path(path).read_text(encoding="utf-8")))
    if date.fromisoformat(config["start"]) > date.fromisoformat(config["end"]):
        raise ValueError("Start date is after end date")
    if not config["paths"] or set(config["paths"]) - {"OLHC", "OHLC"}:
        raise ValueError("Paths must be OLHC/OHLC")
    if len(set(config["paths"])) != len(config["paths"]):
        raise ValueError("Duplicate paths")
    if not 35 <= config["warmup_bars"] <= 10000:
        raise ValueError("warmup_bars must be 35..10000")
    if not 0 <= config["slippage"] < 0.1 or config["fallback_tick"] <= 0:
        raise ValueError("Invalid slippage/tick setting")
    if resolve(config["source"]) == resolve(config["output"]) / "results.sqlite":
        raise ValueError("Source and results must be separate")
    return config


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def code_hash():
    files = [
        HERE / name
        for name in (
            "configuration.py",
            "source.py",
            "execution.py",
            "statistics.py",
            "storage.py",
            "runner.py",
        )
    ]
    files += list((ROOT / "strategies/ha_bb_vwap_v1").glob("*.py"))
    files += list((ROOT / "strategies/ha_bb_vwap_v1/versions").glob("*/*/*.py"))
    files += [ROOT / "backtesting/ha_bb_vwap_v1_20260911/replay.py"]
    value = [(str(p.relative_to(ROOT)), file_hash(p)) for p in sorted(files)]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


class Costs:
    """Explicit research rates, optionally replaced by effective-date CSV rows."""

    def __init__(self, config):
        self.fixed = config["fixed_research_fees"]
        self.rows = []
        if config.get("fees_csv"):
            with resolve(config["fees_csv"]).open(newline="", encoding="utf-8-sig") as handle:
                self.rows = list(csv.DictReader(handle))
        for row in [self.fixed, *self.rows]:
            if any(not math.isfinite(float(row[k])) or float(row[k]) < 0 for k in self.fixed):
                raise ValueError("Fee rates must be finite and nonnegative")

    def rates(self, day):
        if not self.rows:
            return self.fixed
        matches = [r for r in self.rows if r["effective_from"] <= day <= r["effective_to"]]
        if len(matches) != 1:
            raise ValueError(f"Fee schedule must cover {day} exactly once")
        return {k: float(matches[0][k]) for k in self.fixed}

    def breakdown(self, day, side, quantity, price):
        r, turnover = self.rates(day), quantity * price
        result = {
            "brokerage": min(r["brokerage_cap"], turnover * r["brokerage_rate"]),
            "exchange": turnover * r["exchange_rate"],
            "sebi": turnover * r["sebi_rate"],
            "stt": turnover * r["sell_stt_rate"] if side == "sell" else 0.0,
            "stamp": turnover * r["buy_stamp_rate"] if side == "buy" else 0.0,
        }
        result["gst"] = r["gst_rate"] * (result["brokerage"] + result["exchange"] + result["sebi"])
        return result


class Instruments:
    def __init__(self, config, symbols):
        self.config, self.rows, self.snapshot = config, [], {}
        if config.get("metadata_csv"):
            with resolve(config["metadata_csv"]).open(newline="", encoding="utf-8-sig") as handle:
                self.rows = list(csv.DictReader(handle))
        elif config.get("metadata_database") and resolve(config["metadata_database"]).exists():
            uri = resolve(config["metadata_database"]).as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as db:
                for symbol in symbols:
                    tick = db.execute(
                        "SELECT tick_size FROM symtoken WHERE symbol=? AND exchange=?",
                        (symbol, config["exchange"]),
                    ).fetchone()
                    fo = db.execute(
                        "SELECT 1 FROM symtoken WHERE exchange='NFO' AND (name=? OR symbol GLOB ?) LIMIT 1",
                        (symbol, symbol + "[0-9]*"),
                    ).fetchone()
                    if tick and tick[0] and float(tick[0]) > 0:
                        self.snapshot[symbol] = {
                            "tick_size": float(tick[0]),
                            "is_fo": bool(fo),
                            "source": "current_local_snapshot",
                        }

    def get(self, symbol, day):
        if self.rows:
            matches = [
                r
                for r in self.rows
                if r["symbol"] == symbol and r["effective_from"] <= day <= r["effective_to"]
            ]
            if len(matches) != 1:
                raise ValueError(f"Instrument schedule must cover {symbol}/{day} exactly once")
            row = matches[0]
            tick = float(row["tick_size"])
            if (
                not math.isfinite(tick)
                or tick <= 0
                or row["is_fo"].lower() not in {"true", "false", "1", "0"}
            ):
                raise ValueError("Invalid instrument tick/is_fo")
            return {
                "tick_size": tick,
                "is_fo": row["is_fo"].lower() in {"true", "1"},
                "source": "effective_date_csv",
            }
        return self.snapshot.get(
            symbol,
            {
                "tick_size": self.config["fallback_tick"],
                "is_fo": self.config["fallback_is_fo"],
                "source": "explicit_research_fallback",
            },
        )

    def identity(self):
        return {"snapshot": self.snapshot, "effective_rows": self.rows}
