import json
import sqlite3

import pytest

from .comparison import build, progress, select_leaders
from .demo import create_demo


def two_path_demo(output):
    create_demo(output)
    with sqlite3.connect(output / "results.sqlite") as db:
        manifest = json.loads(
            db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0]
        )
        manifest["config"]["paths"] = ["OLHC", "OHLC"]
        manifest["code_sha256"] = "SYNTHETIC"
        db.execute("UPDATE meta SET value=? WHERE key='manifest'", (json.dumps(manifest),))
        db.execute(
            "INSERT INTO daily SELECT strategy,'OHLC',day,payload FROM daily WHERE scenario='OLHC'"
        )


def test_leaders_use_lower_path_profit_and_preserve_ties():
    rows = [
        {"strategy": "A", "lower_path_net_pnl": -1, "max_drawdown": 1, "net_to_drawdown": -1},
        {"strategy": "B", "lower_path_net_pnl": 10, "max_drawdown": 5, "net_to_drawdown": 2},
        {"strategy": "C", "lower_path_net_pnl": 8, "max_drawdown": 2, "net_to_drawdown": 4},
        {"strategy": "D", "lower_path_net_pnl": 10, "max_drawdown": 5, "net_to_drawdown": 2},
    ]
    assert select_leaders(rows) == {
        "profit_leaders": ["B", "D"],
        "profit_to_drawdown_leaders": ["C"],
    }
    assert select_leaders(rows[:1]) == {"profit_leaders": [], "profit_to_drawdown_leaders": []}


def test_complete_demo_comparison_and_missing_day_refusal(tmp_path):
    output = tmp_path / "demo"
    two_path_demo(output)
    report = build(output)
    assert report["synthetic"]
    assert len(report["rows"]) == 2
    assert len(report["paths"]) == 4
    assert len(report["years"]) > 4
    assert "SYNTHETIC DEMO ONLY" in (output / "comparison/findings.md").read_text()
    assert json.loads((output / "comparison/comparison.json").read_text())["completed_days"] == 8
    with sqlite3.connect(output / "results.sqlite") as db:
        db.execute("DELETE FROM days WHERE day=(SELECT MIN(day) FROM days)")
    assert progress(output)["state"] == "partial"
    with pytest.raises(ValueError, match="requires all sessions"):
        build(output)


def test_missing_strategy_session_is_not_ranked(tmp_path):
    output = tmp_path / "demo"
    two_path_demo(output)
    with sqlite3.connect(output / "results.sqlite") as db:
        db.execute("DELETE FROM daily WHERE rowid=(SELECT MIN(rowid) FROM daily)")
    with pytest.raises(ValueError, match="Missing strategy sessions"):
        build(output)
