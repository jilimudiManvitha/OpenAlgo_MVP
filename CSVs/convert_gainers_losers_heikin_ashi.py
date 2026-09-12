"""Export only the requested date as Heikin Ashi for both stock groups.

Run: python CSVs/convert_gainers_losers_heikin_ashi.py --date 2026-09-11
Uses the standard library. Source CSVs must be chronological and contain
date,time,open,high,low,close columns. Other columns are preserved verbatim.
Each stock/timeframe has independent HA state, carried across sessions:
HA close = (O+H+L+C)/4; HA open = (previous HA open+previous HA close)/2;
HA high = max(H,HA open,HA close); HA low = min(L,HA open,HA close).
Initial HA open = (O+C)/2. Only output prices are rounded (10 decimals).
Missing source bars are not synthesized. Inconsistent raw OHLC ranges are
counted in the conversion report and used as supplied, without repair.
"""

import argparse
import csv
import math
from datetime import date
from pathlib import Path


def convert(source, destination, selected_date):
    output = []
    previous_key = None
    previous_open = previous_close = None
    input_count = bad_ranges = bad_selected = 0
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        if not columns or not {"date", "time", "open", "high", "low", "close"}.issubset(columns):
            raise ValueError(f"Missing required columns: {source}")
        for row in reader:
            key = (row["date"], row["time"])
            if previous_key is not None and key <= previous_key:
                raise ValueError(f"Unsorted or duplicate timestamp in {source}: {key}")
            previous_key = key
            if row["date"] > selected_date:
                continue
            input_count += 1
            o, h, low, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            if not all(math.isfinite(v) for v in (o, h, low, c)):
                raise ValueError(f"Nonfinite OHLC in {source}: {key}")
            if not low <= min(o, c) <= max(o, c) <= h:
                bad_ranges += 1
                bad_selected += row["date"] == selected_date
            ha_close = (o + h + low + c) / 4
            ha_open = (o + c) / 2 if previous_open is None else (previous_open + previous_close) / 2
            if row["date"] == selected_date:
                result = dict(row)
                for field, value in zip(
                    ("open", "high", "low", "close"),
                    (ha_open, max(h, ha_open, ha_close), min(low, ha_open, ha_close), ha_close),
                ):
                    result[field] = f"{value:.10f}".rstrip("0").rstrip(".")
                output.append(result)
            previous_open, previous_close = ha_open, ha_close
    if not output:
        raise ValueError(f"No {selected_date} candles in {source}")
    if source.resolve() == destination.resolve():
        raise ValueError("Cannot overwrite source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(output)
    return {
        "source": str(source), "output": str(destination), "date": selected_date,
        "input_candles_through_date": input_count, "output_candles": len(output),
        "first_time": output[0]["time"], "last_time": output[-1]["time"],
        "inconsistent_source_ranges": bad_ranges,
        "inconsistent_source_ranges_on_date": bad_selected,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-09-11")
    args = parser.parse_args()
    date.fromisoformat(args.date)
    base = Path(__file__).resolve().parent
    groups = (
        ("GainersOn11092026", "historify_export_20260912_194124"),
        ("LoosersOn11092026", "historify_export_20260912_195613"),
    )
    reports = []
    for group, export in groups:
        sources = sorted((base / group / export).glob("*.csv"))
        if not sources:
            raise ValueError(f"No source CSVs: {group}/{export}")
        for source in sources:
            timeframe = source.stem.rsplit("_", 1)[-1]
            if timeframe not in ("1m", "5m"):
                raise ValueError(f"Unrecognized timeframe: {source}")
            folder = "1minHAdata" if timeframe == "1m" else "5minHAdata"
            destination = base / group / folder / f"{source.stem}_HA_{args.date}.csv"
            report = convert(source, destination, args.date)
            reports.append(report)
            print(f"{group}/{folder}/{destination.name}: {report['output_candles']} candles", flush=True)
    report_path = base / f"heikin_ashi_conversion_report_{args.date}.csv"
    with report_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(reports[0]))
        writer.writeheader()
        writer.writerows(reports)
    print(f"Completed {len(reports)} files. Report: {report_path}")


if __name__ == "__main__":
    main()
