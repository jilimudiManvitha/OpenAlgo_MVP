"""Compatibility entry point for the current read-only schedule verification.

The October 5 calendar/auth check is historical. The October 7 release has
28 schedules; do not restore a twenty-entry backup over the new shorts.
"""
import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "oct7-combine/schedules.py"), run_name="__main__")
