"""Read-only coverage audit for the fixed Nifty 50 research basket."""

import csv
import json

from .configuration import HERE, ROOT, load_config
from .source import Source


def main():
    config = load_config(HERE / "nifty50_2026_h1.json")
    with (ROOT / "stock_symbols_CSVs/ind_nifty50list.csv").open(newline="") as handle:
        wanted = {row["Symbol"] for row in csv.DictReader(handle)}
    config["symbols"] = []
    with Source(config) as source:
        source.db.execute("SET enable_progress_bar=false")
        catalog = source.catalog()
        selected = [r for r in catalog if r[0] in wanted]
        days = source.calendar()
        result = {
            "stocks": len(selected),
            "missing": sorted(wanted - {r[0] for r in selected}),
            "bajaj_candidates": [r for r in catalog if "BAJAJ" in r[0]],
            "minute_rows": sum(r[1] for r in selected),
            "days": len(days),
            "first_day": days[0],
            "last_day": days[-1],
            "catalog": selected,
        }
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
