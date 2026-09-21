"""Browser-test fixture. Synthetic data only; no broker connections."""

import tempfile
from pathlib import Path

from server import Monitor, Store, create_app

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "fixture.sqlite3")

        class FixtureMonitor(Monitor):
            def snapshot(self):
                return [dict(row, status="Synthetic preview") for row in self.store.watches()]

        monitor = FixtureMonitor(store, {"stocks": {"key": ""}, "crypto": {"key": ""}})
        create_app(store, monitor, 8782).run(host="127.0.0.1", port=8782, use_reloader=False)
