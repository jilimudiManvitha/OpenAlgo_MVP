"""Independent artifact consistency, integrity and preservation checks."""

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "log/test/day-review-20261007"
data = json.loads((OUT / "report-data.json").read_text())
checks = {}
assert len(data["results"]) == 56
assert all(sum(r["path"] == p for r in data["results"]) == 28 for p in ("OLHC", "OHLC"))
assert all(
    r["metrics"]["wins"] + r["metrics"]["losses"] + r["metrics"]["breakeven"]
    == r["metrics"]["trades"]
    for r in data["results"]
)
for path in ("OLHC", "OHLC"):
    rows = [r for r in data["results"] if r["path"] == path]
    trades = [t for r in rows for t in r["trades"]]
    assert len({t["id"] for t in trades}) == len(trades)
    closed = [t for t in trades if t["exit_ts"] is not None]
    open_rows = [t for t in trades if t["exit_ts"] is None]
    fees = math.fsum(t["fees"] for t in trades)
    net = math.fsum(t["net_pnl"] for t in closed)
    total = net + math.fsum(t["unrealized"] - t["entry_estimated_fees"] for t in open_rows)
    expected = data["scenarios"][path]
    assert abs(fees - expected["all_charges"]) < 0.001
    assert abs(net - expected["net_pnl"]) < 0.001
    assert abs(total - expected["total_net"]) < 0.001
    assert abs(fees - math.fsum(math.fsum(t["charge_breakdown"].values()) for t in trades)) < 0.001
    checks[path] = {
        "strategies": len(rows),
        "entries": len(trades),
        "closed_trades": len(closed),
        "open_legs": len(open_rows),
        "closed_net": round(net, 2),
        "total_marked_net": round(total, 2),
        "all_charges": round(fees, 2),
    }
html = ROOT / "backtesting/all_strategies_2026-10-07.html"
text = html.read_text()
assert text.count("<script") == 2 and "__DATA__" not in text
assert "<script src=" not in text and "<link " not in text
for secret_key in ("access_token", "auth_token", "api_key", "client_secret", "user_id", "owner"):
    assert ('"' + secret_key + '":') not in text, "Private source field leaked into report"
checks["html"] = {
    "bytes": html.stat().st_size,
    "sha256": hashlib.sha256(html.read_bytes()).hexdigest(),
    "external_assets": False,
}
before = json.loads((OUT / "protected-before.json").read_text())
changed = [
    p
    for p, old in before.items()
    if not (ROOT / p).is_file() or hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != old
]
checks["preservation"] = {"checked_files": len(before), "changed": changed}
assert not changed, "Protected application/data files changed; investigate rather than overwrite"
checks["source_hashes"] = {
    str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in (OUT / "inputs").rglob("*")
    if p.is_file()
}
(OUT / "verification.json").write_text(json.dumps(checks, indent=2))
print(json.dumps({k: v for k, v in checks.items() if k != "source_hashes"}, indent=2))
