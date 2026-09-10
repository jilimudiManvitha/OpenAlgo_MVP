# Nifty 50 BB/VWAP/Heikin Ashi research

Start with [the detailed strategy review and execution status](NIFTY50_BB_VWAP_HEIKIN_ASHI_detailed_report.md).

Historical backtest: **blocked; no API key or reachable local API server at the initial check**.
Optimization: **not run**. No validated best variant exists yet.

Implementation: `../../stratagies/nifty50_bb_vwap_ha_research.py`.
Environment: `../../.venv/Scripts/python.exe`.
Tests: `../../stratagies/test_nifty50_bb_vwap_ha_research.py`.

From the repository root:

```powershell
.\backtesting\.venv\Scripts\python.exe backtesting\stratagies\nifty50_bb_vwap_ha_research.py --preflight
.\backtesting\.venv\Scripts\python.exe backtesting\stratagies\nifty50_bb_vwap_ha_research.py --start 2021-09-05 --end 2026-09-05
```

Set `OPENALGO_API_KEY` in the root `.env`, ensure OpenAlgo is running and the broker is authenticated. Do not paste credentials into reports or chat. Market history stays in memory; reports contain derived results only.
