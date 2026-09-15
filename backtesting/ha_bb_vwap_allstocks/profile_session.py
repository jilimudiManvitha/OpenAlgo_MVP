"""Bounded read-only throughput measurement; writes no historical result rows."""

import cProfile
import io
import json
import pstats
import time
from pathlib import Path

from .configuration import Costs, Instruments, load_config
from .execution import event_stream, reconcile, replay, selected_definitions
from .source import Source, aggregate
from .statistics import DayAccumulator


def main():
    config = load_config()
    day, symbol = config["start"], "20MICRONS"
    costs = Costs(config)
    definitions = selected_definitions(config)
    stages = {}
    started = time.perf_counter()
    with Source(config) as source:
        warmup, bars, _ = source.session(symbol, day)
    stages["read_source_seconds"] = time.perf_counter() - started
    instrument = Instruments(config, [symbol]).get(symbol, day)
    profiler = cProfile.Profile()
    profiler.enable()
    ntrades = 0
    encoded_bytes = 0
    for minutes in (1, 5):
        history = (warmup if minutes == 1 else aggregate(warmup))[-config["warmup_bars"] :]
        native = bars if minutes == 1 else aggregate(bars)
        for path in config["paths"]:
            start = time.perf_counter()
            events, charts, _ = event_stream(history, bars, native, minutes, path)
            stages[f"events_{minutes}_{path}"] = time.perf_counter() - start
            start = time.perf_counter()
            for sid, definition in definitions:
                if definition[0].timeframe_minutes != minutes:
                    continue
                trades, marks, rejected = replay(
                    definition, sid, symbol, day, instrument, events, path, config, costs
                )
                reconcile(trades)
                accumulator = DayAccumulator(day)
                accumulator.add(trades, marks, len(rejected))
                ntrades += len(trades)
                encoded_bytes += len(json.dumps(trades))
            stages[f"replay_reconcile_accumulate_{minutes}_{path}"] = time.perf_counter() - start
            print(json.dumps(stages), flush=True)
    profiler.disable()
    stream = io.StringIO()
    pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(35)
    folder = Path(__file__).parent / "artifacts"
    folder.mkdir(exist_ok=True)
    report = {
        "symbol": symbol,
        "day": day,
        "strategies": len(definitions),
        "paths": config["paths"],
        "seconds": time.perf_counter() - started,
        "stages": stages,
        "trades": ntrades,
        "uncompressed_trade_json_bytes": encoded_bytes,
        "notes": "One early stock-session, cold VectorBT JIT, cProfile and concurrent runner overhead; not a full-history ETA. Accumulator constructors are per replay here, per day in the full runner.",
    }
    (folder / "throughput-profile.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (folder / "throughput-profile.txt").write_text(stream.getvalue(), encoding="utf-8")
    print(json.dumps(report), flush=True)
    print(stream.getvalue(), flush=True)


if __name__ == "__main__":
    main()
