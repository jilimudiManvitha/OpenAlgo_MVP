"""OpenAlgo upload entry point: fixed September 25 scanner basket, sandbox only."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "narasimha_pc_backtest" / "today_20260925"
if not PACKAGE.is_dir():
    raise RuntimeError("This strategy requires its verified local narasimha_pc_backtest package")
sys.path.insert(0, str(PACKAGE))
from paper_runtime import main

if __name__ == "__main__":
    main()
