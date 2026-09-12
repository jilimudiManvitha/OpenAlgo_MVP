"""Convert the two PINELABS CSVs using only the Python standard library.

Run: python convert_to_heikin_ashi.py
Optional: --date 2026-09-11 --input-dir PATH --output-dir PATH

Output open/high/low/close are Heikin Ashi values; all other columns are
unchanged. Each timeframe is calculated independently in chronological order:
  HA close = (raw open + raw high + raw low + raw close) / 4
  HA open  = (previous HA open + previous HA close) / 2
  HA high  = max(raw high, HA open, HA close)
  HA low   = min(raw low, HA open, HA close)
The first HA open uses (raw open + raw close) / 2. State carries across
sessions. Date extracts are filtered AFTER conversion of the full history.
Calculations use unrounded values; output prices have up to 10 decimals.
Original input files are never overwritten. Invalid raw candle ranges are
reported, but their supplied numbers are used without silently repairing them.
"""

import argparse
import csv
import math
from datetime import date, datetime
from pathlib import Path


def convert(source: Path, output_dir: Path, selected_date: str) -> None:
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        required = {"date", "time", "open", "high", "low", "close"}
        if not columns or not required.issubset(columns):
            raise ValueError(f"{source}: required columns: {sorted(required)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{source}: no candles")
    rows.sort(key=lambda row: datetime.fromisoformat(f"{row['date']}T{row['time']}"))
    if not any(row["date"] == selected_date for row in rows):
        raise ValueError(f"{source}: no candles for {selected_date}")

    previous_open = previous_close = None
    seen = set()
    converted = []
    invalid_ranges = 0
    selected_invalid_ranges = 0
    for row in rows:
        timestamp = (row["date"], row["time"])
        if timestamp in seen:
            raise ValueError(f"{source}: duplicate timestamp {timestamp}")
        seen.add(timestamp)
        raw_open, raw_high, raw_low, raw_close = (
            float(row[key]) for key in ("open", "high", "low", "close")
        )
        if not all(math.isfinite(v) for v in (raw_open, raw_high, raw_low, raw_close)):
            raise ValueError(f"{source}: nonfinite OHLC at {timestamp}")
        if not raw_low <= min(raw_open, raw_close) <= max(raw_open, raw_close) <= raw_high:
            invalid_ranges += 1
            selected_invalid_ranges += row["date"] == selected_date
        ha_close = (raw_open + raw_high + raw_low + raw_close) / 4
        ha_open = (
            (raw_open + raw_close) / 2
            if previous_open is None
            else (previous_open + previous_close) / 2
        )
        ha_high = max(raw_high, ha_open, ha_close)
        ha_low = min(raw_low, ha_open, ha_close)
        result = dict(row)
        for key, value in zip(
            ("open", "high", "low", "close"), (ha_open, ha_high, ha_low, ha_close)
        ):
            result[key] = f"{value:.10f}".rstrip("0").rstrip(".")
        converted.append(result)
        previous_open, previous_close = ha_open, ha_close

    output_dir.mkdir(parents=True, exist_ok=True)
    selected = [row for row in converted if row["date"] == selected_date]
    for suffix, output_rows in (("", converted), (f"_{selected_date}", selected)):
        destination = output_dir / f"{source.stem}_heikin_ashi{suffix}.csv"
        if destination.resolve() == source.resolve():
            raise ValueError("Output must not overwrite the source")
        with destination.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(output_rows)
        print(f"{destination.name}: {len(output_rows):,} candles")
    if invalid_ranges:
        print(
            f"  Source warning: {invalid_ranges:,} inconsistent raw OHLC ranges "
            f"({selected_invalid_ranges} on {selected_date}); supplied values retained."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-09-11", help="Extract date, YYYY-MM-DD")
    parser.add_argument("--input-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    date.fromisoformat(args.date)
    output_dir = args.output_dir or args.input_dir / "heikin_ashi"
    for timeframe in ("1m", "5m"):
        convert(args.input_dir / f"PINELABS_NSE_{timeframe}.csv", output_dir, args.date)


if __name__ == "__main__":
    main()
