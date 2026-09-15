"""Generate historical findings only after every planned session is committed."""

import argparse
import csv
import html
import json
import time
from collections import defaultdict
from datetime import UTC, datetime, timezone
from pathlib import Path

from .configuration import load_config, resolve
from .statistics import combine
from .storage import read_connection


def progress(output):
    path = Path(output) / "results.sqlite"
    if not path.is_file():
        return {"state": "not_run", "completed_days": 0, "planned_days": None}
    with read_connection(path) as db:
        db.execute("BEGIN")
        manifest = json.loads(
            db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0]
        )
        days = [r[0] for r in db.execute("SELECT day FROM days ORDER BY day")]
    planned = manifest["planned_days"]
    complete = bool(planned) and days == sorted(planned)
    return {
        "state": "complete" if complete else "partial",
        "synthetic": manifest["demo"],
        "completed_days": len(days),
        "planned_days": len(planned),
        "first_completed": days[0] if days else None,
        "last_completed": days[-1] if days else None,
    }


def select_leaders(rows):
    """Rank by declared measures; no arbitrary mixture of profit and win rate."""
    profitable = [r for r in rows if r["lower_path_net_pnl"] > 0]
    risk_candidates = [
        r for r in profitable if r["net_to_drawdown"] is not None and r["max_drawdown"] > 0
    ]
    by_profit = sorted(profitable, key=lambda r: (-r["lower_path_net_pnl"], r["strategy"]))
    by_risk = sorted(risk_candidates, key=lambda r: (-r["net_to_drawdown"], r["strategy"]))

    def top_ties(ranked, metric):
        if not ranked:
            return []
        best = ranked[0][metric]
        # Preserve equivalent versions instead of claiming an arbitrary ID is uniquely best.
        return [r["strategy"] for r in ranked if abs(r[metric] - best) <= 1e-9 * max(1, abs(best))]

    return {
        "profit_leaders": top_ties(by_profit, "lower_path_net_pnl"),
        "profit_to_drawdown_leaders": top_ties(by_risk, "net_to_drawdown"),
    }


def build(output):
    output = Path(output)
    status = progress(output)
    if status["state"] != "complete":
        raise ValueError(
            f"Final comparison requires all sessions: {status['completed_days']}/"
            f"{status['planned_days']} completed. No full-history winner has been selected."
        )
    rows, detail, year_rows = [], [], []
    with read_connection(output / "results.sqlite") as db:
        db.execute("BEGIN")
        manifest = json.loads(
            db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0]
        )
        days = [r[0] for r in db.execute("SELECT day FROM days ORDER BY day")]
        if days != sorted(manifest["planned_days"]):
            raise ValueError("Completed session set changed during comparison")
        coverage = dict(
            db.execute("SELECT SUM(tested) tested,SUM(skipped) skipped FROM days").fetchone()
        )
        paths = manifest["config"]["paths"]
        if set(paths) != {"OLHC", "OHLC"}:
            raise ValueError("This comparison requires both OLHC and OHLC scenarios")
        for definition in db.execute("SELECT * FROM strategies ORDER BY id").fetchall():
            summaries, annual = {}, defaultdict(dict)
            for path in paths:
                daily = [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT payload FROM daily WHERE strategy=? AND scenario=? ORDER BY day",
                        (definition["id"], path),
                    )
                ]
                if [r["day"] for r in daily] != days:
                    raise ValueError(f"Missing strategy sessions: {definition['id']} / {path}")
                summary = combine(daily, manifest["capital_reference"])
                summaries[path] = summary
                detail.append({"strategy": definition["id"], "path": path, **summary})
                grouped = defaultdict(list)
                for row in daily:
                    grouped[row["day"][:4]].append(row)
                for year, group in grouped.items():
                    stats = combine(group, manifest["capital_reference"])
                    annual[year][path] = stats["net_pnl"]
                    year_rows.append(
                        {"strategy": definition["id"], "path": path, "year": year, **stats}
                    )
            lower = min(s["net_pnl"] for s in summaries.values())
            drawdown = max(s["max_drawdown"] for s in summaries.values())
            positive_years = sum(min(v.values()) > 0 for v in annual.values())
            worst_year = min(annual, key=lambda y: min(annual[y].values()))
            rows.append(
                {
                    "strategy": definition["id"],
                    "name": definition["name"],
                    "side": definition["side"],
                    "minutes": definition["minutes"],
                    "config": json.loads(definition["config"]),
                    "lower_path_net_pnl": lower,
                    "higher_path_net_pnl": max(s["net_pnl"] for s in summaries.values()),
                    "max_drawdown": drawdown,
                    "net_to_drawdown": lower / drawdown if drawdown > 0 else None,
                    "peak_capital": max(s["peak_capital"] for s in summaries.values()),
                    "min_trades": min(s["trades"] for s in summaries.values()),
                    "max_trades": max(s["trades"] for s in summaries.values()),
                    "positive_years_both_paths": positive_years,
                    "observed_years": len(annual),
                    "worst_year": worst_year,
                    "worst_year_lower_net": min(annual[worst_year].values()),
                    "latest_year_lower_net": min(annual[max(annual)].values()),
                }
            )
    rows.sort(key=lambda r: (-r["lower_path_net_pnl"], r["strategy"]))
    groups = defaultdict(list)
    for row in rows:
        groups[f"{row['side']} {row['minutes']}m"].append(row)
    report = {
        **status,
        "generated_utc": datetime.now(UTC).isoformat(),
        "source_sha256": manifest["source_sha256"],
        "code_sha256": manifest["code_sha256"],
        "coverage": coverage,
        "leaders": select_leaders(rows),
        "groups": {key: select_leaders(group) for key, group in sorted(groups.items())},
        "rows": rows,
        "paths": detail,
        "years": year_rows,
        "method": [
            "Profit ranking uses the lower net P&L of the two modeled paths, after fees and slippage.",
            "Profit-to-drawdown ranking uses lower path net P&L divided by the larger path MTM drawdown.",
            "Only versions profitable on both paths can be leaders; tied versions are reported together.",
            "Annual consistency includes partial endpoint years; year rows are diagnostics, not held-out tests.",
            "No positive candidate means none worked profitably under the configured assumptions.",
            "Ranking 404 versions retrospectively is selection on this history, not proof of future returns.",
            "Fees and tick/F&O metadata follow the run manifest, including any fixed historical assumptions.",
            "Completed source sessions can contain skipped stocks or missing candles; inspect coverage.",
        ],
    }
    write_report(output, report)
    return report


def write_report(output, report):
    folder = Path(output) / "comparison"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "comparison.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    for name, rows in (
        ("ranking", report["rows"]),
        ("path_metrics", report["paths"]),
        ("year_metrics", report["years"]),
    ):
        with (folder / f"{name}.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                for row in rows:
                    writer.writerow(
                        {k: json.dumps(v) if isinstance(v, dict) else v for k, v in row.items()}
                    )
    label = "SYNTHETIC DEMO ONLY" if report["synthetic"] else "Completed historical comparison"
    lines = [
        f"# {label}",
        "",
        f"Completed {report['completed_days']} of {report['planned_days']} source sessions.",
        "",
    ]
    by_id = {r["strategy"]: r for r in report["rows"]}
    path_stats = defaultdict(list)
    for row in report["paths"]:
        path_stats[row["strategy"]].append(row)
    for group, leaders in [("All strategies", report["leaders"]), *report["groups"].items()]:
        lines += [f"## {group}", ""]
        for kind, ids in leaders.items():
            description = (
                "Highest net profit" if kind == "profit_leaders" else "Highest profit / drawdown"
            )
            lines.append(
                f"{description}: {', '.join(ids) if ids else 'No eligible profitable strategy'}."
            )
            if ids:
                r = by_id[ids[0]]
                lines.append(
                    f"{r['name']}: lower-path net Rs {r['lower_path_net_pnl']:,.2f}; "
                    f"largest path drawdown Rs {r['max_drawdown']:,.2f}; "
                    f"peak notional Rs {r['peak_capital']:,.2f}; "
                    f"{r['min_trades']:,}-{r['max_trades']:,} trades; "
                    f"profitable in both paths in {r['positive_years_both_paths']}/{r['observed_years']} observed years."
                )
                stats = path_stats[r["strategy"]]
                lines.append(
                    f"Brokerage Rs {min(s['brokerage'] for s in stats):,.2f}-"
                    f"{max(s['brokerage'] for s in stats):,.2f}; "
                    f"total charges Rs {min(s['fees'] for s in stats):,.2f}-"
                    f"{max(s['fees'] for s in stats):,.2f}. "
                    f"Worst observed year: {r['worst_year']} (lower-path net Rs {r['worst_year_lower_net']:,.2f}); "
                    f"latest observed year lower-path net Rs {r['latest_year_lower_net']:,.2f}."
                )
                if r["positive_years_both_paths"] < r["observed_years"]:
                    lines.append(
                        "Its aggregate ranking includes years that were not profitable on both paths."
                    )
                lines.append("Configuration: " + json.dumps(r["config"], sort_keys=True))
            lines.append("")
    lines += [
        "## Interpretation",
        "",
        *[f"- {s}" for s in report["method"]],
        "",
        f"Coverage: {report['coverage']}",
    ]
    (folder / "findings.md").write_text("\n".join(lines), encoding="utf-8")
    columns = [
        "strategy",
        "side",
        "minutes",
        "lower_path_net_pnl",
        "max_drawdown",
        "net_to_drawdown",
        "peak_capital",
        "positive_years_both_paths",
        "observed_years",
    ]
    table = (
        "<table><thead><tr>"
        + "".join(f"<th>{html.escape(k.replace('_', ' '))}</th>" for k in columns)
        + "</tr></thead><tbody>"
    )
    for row in report["rows"]:
        table += (
            "<tr>"
            + "".join(
                f"<td>{html.escape(f'{row[k]:,.2f}' if isinstance(row[k], float) else str(row[k]))}</td>"
                for k in columns
            )
            + "</tr>"
        )
    document = (
        "<!doctype html><meta charset='utf-8'><title>Strategy comparison</title>"
        "<style>body{font:16px system-ui;background:#101827;color:#e2e8f0;padding:30px}"
        "pre{white-space:pre-wrap;line-height:1.6}table{border-collapse:collapse;width:100%;font-size:13px}"
        "td,th{padding:9px;border:1px solid #334155;text-align:right}th{position:sticky;top:0;background:#1e293b}"
        "a{color:#7dd3fc}</style>"
        f"<pre>{html.escape(chr(10).join(lines))}</pre>"
        "<p><a href='ranking.csv'>Ranking CSV</a> | <a href='path_metrics.csv'>All path metrics</a> | "
        "<a href='year_metrics.csv'>Annual metrics</a></p>" + table + "</tbody></table>"
    )
    (folder / "index.html").write_text(document, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    parser.add_argument(
        "--watch", action="store_true", help="Wait for all committed days, then write findings"
    )
    args = parser.parse_args()
    output = resolve(args.output or load_config()["output"])
    last = None
    while True:
        status = progress(output)
        if status != last:
            print(json.dumps(status), flush=True)
            last = status
        if status["state"] == "complete":
            build(output)
            print(f"Final findings written to {output / 'comparison' / 'index.html'}", flush=True)
            return
        if not args.watch:
            parser.exit(
                2,
                "Run incomplete; no full-history winner is available. Use --watch to generate findings when complete.\n",
            )
        time.sleep(30)


if __name__ == "__main__":
    main()
