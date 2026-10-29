"""Launch the authorized offline quarter download in an independent OS session."""

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "log/test/options-previous-quarter"
LOG.mkdir(parents=True, exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
log_path = LOG / f"full-quota-{stamp}.log"
baseline = {
    str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (
        ROOT / "strategies/strategy_configs.json",
        ROOT / "backtesting/options_3months_2026-10-07.html",
    )
}
with log_path.open("x") as output:
    process = subprocess.Popen(
        ["/usr/bin/caffeinate", "-i", sys.executable,
         str(ROOT / ".development/options-previous-quarter/run.py"), "--full-quota"],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output,
        stderr=subprocess.STDOUT, start_new_session=True,
    )
record = dict(pid=process.pid, log=str(log_path.relative_to(ROOT)),
              started_at=datetime.now().astimezone().isoformat(), baseline=baseline)
(LOG / "full-quota-launch.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record))
