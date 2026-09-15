"""One trading day per transaction; source stays read-only throughout the run."""

import hashlib
import json
from dataclasses import asdict

from backtesting.ha_bb_vwap_v1_20260911.replay import safe_json

from .configuration import Costs, Instruments, code_hash, file_hash, resolve
from .execution import event_stream, reconcile, replay, selected_definitions
from .source import Source, aggregate
from .statistics import DayAccumulator
from .storage import Store, encode


def chart_rows(charts):
    return safe_json(
        [
            {
                "time": s.candle.start.isoformat(),
                "ha": [s.ha_open, s.ha_high, s.ha_low, s.ha_close],
                "raw": [s.candle.open, s.candle.high, s.candle.low, s.candle.close],
                "volume": s.candle.volume,
                **asdict(s.indicators),
            }
            for s in charts
        ]
    )


def run(config, resume=False, max_days=None, demo=False):
    definitions = selected_definitions(config)
    costs = Costs(config)
    with Source(config) as source:
        catalog = source.catalog()
        if not catalog:
            raise ValueError("No source minute candles in the requested date range")
        symbols = {r[0] for r in catalog}
        calendar = source.calendar()
        instruments = Instruments(config, sorted(symbols))
        source_path = resolve(config["source"])
        before = source_path.stat()
        print("Fingerprinting read-only source snapshot...", flush=True)
        digest = file_hash(source_path)
        if (before.st_size, before.st_mtime_ns) != (
            source_path.stat().st_size,
            source_path.stat().st_mtime_ns,
        ):
            raise ValueError("Source changed while hashing")
        manifest = {
            "schema_version": 1,
            "demo": demo,
            "config": config,
            "source_sha256": digest,
            "code_sha256": code_hash(),
            "instruments": instruments.identity(),
            "cost_schedule": costs.rows,
            "catalog": catalog,
            "planned_days": calendar,
            "capital_reference": len(symbols) * 100000,
            "notes": [
                "Two synthetic minute paths; no tick/order-book replay.",
                "Fixed research fees/current metadata across history unless effective-date CSVs supplied.",
                "All available NSE source symbols; source coverage is not a reconstructed exchange universe.",
                "Unlimited independent stock allocations; gross entry notional, not broker margin.",
                "No forced ranking by hindsight gainers/losers; buy and sell versions each test all source stocks.",
            ],
        }
        # JSON canonicalization prevents tuple/list differences on resume.
        manifest = json.loads(json.dumps(manifest))
        defs = [
            (sid, {**asdict(definition[0]), "name": definition[0].name})
            for sid, definition in definitions
        ]
        output = resolve(config["output"])
        with Store(output / "results.sqlite", manifest, defs, resume) as store:
            (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            complete = store.complete_days()
            done = 0
            for day in calendar:
                if day in complete:
                    continue
                if max_days is not None and done >= max_days:
                    break
                costs.rates(
                    day
                )  # Fail for uncovered historical fee dates before doing any day work.
                day_symbols = [s for s in source.day_symbols(day) if s in symbols]
                totals = {
                    (sid, p): DayAccumulator(day) for sid, _ in definitions for p in config["paths"]
                }
                tested = skipped = 0
                day_hashes = []
                print(
                    f"{day}: {len(day_symbols)} source stocks, {len(definitions)} strategies",
                    flush=True,
                )
                with (
                    store.db
                ):  # Interruption rolls back this whole day, retaining earlier completed days.
                    for index, symbol in enumerate(day_symbols):
                        try:
                            warmup, bars, audit = source.session(symbol, day)
                            instrument = instruments.get(symbol, day)
                        except (ValueError, TypeError) as error:
                            store.db.execute(
                                "INSERT INTO coverage VALUES(?,?,?,?)",
                                (day, symbol, "skipped", json.dumps({"reason": str(error)})),
                            )
                            skipped += 1
                            continue
                        audit["instrument"] = instrument
                        audit["warmup_5m"] = min(len(aggregate(warmup)), config["warmup_bars"])
                        store.db.execute(
                            "INSERT INTO coverage VALUES(?,?,?,?)",
                            (day, symbol, "tested", json.dumps(audit)),
                        )
                        day_hashes.append([symbol, audit["input_sha256"]])
                        tested += 1
                        for minutes in sorted({d[0].timeframe_minutes for _, d in definitions}):
                            history = (warmup if minutes == 1 else aggregate(warmup))[
                                -config["warmup_bars"] :
                            ]
                            native = bars if minutes == 1 else aggregate(bars)
                            any_trades = False
                            charts = []
                            for path in config["paths"]:
                                events, charts, _ = event_stream(
                                    history, bars, native, minutes, path
                                )
                                for sid, definition in definitions:
                                    if definition[0].timeframe_minutes != minutes:
                                        continue
                                    trades, marks, rejected = replay(
                                        definition,
                                        sid,
                                        symbol,
                                        day,
                                        instrument,
                                        events,
                                        path,
                                        config,
                                        costs,
                                    )
                                    if config["vectorbt_reconcile"]:
                                        reconcile(trades)
                                    totals[(sid, path)].add(trades, marks, len(rejected))
                                    store.add_trades(trades)
                                    any_trades |= bool(trades)
                                    if rejected:
                                        store.db.execute(
                                            "INSERT INTO rejections VALUES(?,?,?,?,?)",
                                            (sid, path, day, symbol, json.dumps(rejected)),
                                        )
                            if config["store_trade_charts"] and any_trades:
                                store.db.execute(
                                    "INSERT INTO candles VALUES(?,?,?,?)",
                                    (day, symbol, minutes, encode(chart_rows(charts))),
                                )
                        if (index + 1) % 25 == 0:
                            print(f"  {day}: {index + 1}/{len(day_symbols)} stocks", flush=True)
                    for (sid, path), accumulator in totals.items():
                        row, series = accumulator.finish()
                        store.daily(sid, path, day, row, series)
                    benchmark = source.benchmark(day)
                    store.db.execute(
                        "INSERT INTO days VALUES(?,?,?,?,?,?)",
                        (
                            day,
                            len(day_symbols),
                            tested,
                            skipped,
                            benchmark,
                            hashlib.sha256(json.dumps(day_hashes).encode()).hexdigest(),
                        ),
                    )
                done += 1
                print(f"Committed {day}: {tested} tested, {skipped} skipped", flush=True)
            result = {
                "completed_days": len(store.complete_days()),
                "planned_days": len(calendar),
                "new_days": done,
                "results": str(output / "results.sqlite"),
                "demo": demo,
            }
            print(json.dumps(result), flush=True)
            return result
