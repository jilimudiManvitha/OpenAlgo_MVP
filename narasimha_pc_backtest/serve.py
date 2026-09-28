"""Local report server; reads only the generated artifacts, never the trading app."""

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import duckdb
from run import HERE, stamp


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path != "/api/candles":
            return super().do_GET()
        try:
            q = parse_qs(url.query)
            symbol, day = q["symbol"][0], q["date"][0]
            manifest = json.loads((Path(self.directory) / "manifest.json").read_text())
            if symbol not in manifest["config"]["symbols"]:
                raise ValueError("Unknown symbol")
            start = stamp(day)
            filename = Path(self.directory) / "candles" / f"{symbol}.parquet"
            with duckdb.connect(config={"threads": 1, "memory_limit": "256MB"}) as db:
                df = db.execute(
                    "SELECT * FROM read_parquet(?) WHERE timestamp>=? AND timestamp<? ORDER BY timestamp",
                    [str(filename), start, start + 86400],
                ).fetchdf()
            payload = df.to_json(orient="records").encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (ValueError, KeyError, FileNotFoundError):
            self.send_error(400, "Invalid symbol/date or missing output")

    def log_message(self, *_):
        pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=HERE / "output")
    p.add_argument("--port", type=int, default=8782)
    a = p.parse_args()
    with ThreadingHTTPServer(
        ("127.0.0.1", a.port), partial(Handler, directory=str(a.output.resolve()))
    ) as server:
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
