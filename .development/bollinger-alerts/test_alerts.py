import math
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import Crossing, bands, epoch, history_rows
from server import Monitor, Store, create_app, validate_watch

CONNECTIONS = {
    "stocks": {
        "host": "http://127.0.0.1:5000",
        "ws": "ws://127.0.0.1:8765",
        "key": "fixture-secret",
    }
}


def watch(**kwargs):
    return dict(
        id="fixture",
        connection="stocks",
        symbol="TEST",
        exchange="NSE",
        interval="1m",
        mode="live",
        side="both",
        period=20,
        deviation=2.0,
        enabled=True,
        **kwargs,
    )


class EngineTests(unittest.TestCase):
    def test_population_standard_deviation(self):
        result = bands([1, 2, 3, 4], 4, 2)
        self.assertAlmostEqual(result["middle"], 2.5)
        self.assertAlmostEqual(result["upper"], 2.5 + 2 * math.sqrt(1.25))

    def test_upper_lower_rearm_and_candle_dedup(self):
        engine = Crossing()
        self.assertIsNone(engine.observe([100] * 20, 1, 1)[0])
        self.assertEqual(engine.observe([100] * 19 + [120], 2, 1)[0]["band"], "upper")
        self.assertIsNone(engine.observe([100] * 19 + [125], 3, 1)[0])
        engine.observe([100] * 20, 4, 1)
        self.assertIsNone(engine.observe([100] * 19 + [120], 5, 1)[0])
        # Merely advancing candle while still outside is not another crossing.
        self.assertIsNone(engine.observe([100] * 19 + [120], 6, 2)[0])
        engine.observe([100] * 20, 7, 2)
        self.assertEqual(engine.observe([100] * 19 + [80], 8, 2)[0]["band"], "lower")

    def test_start_outside_reset_and_out_of_order(self):
        engine = Crossing()
        self.assertIsNone(engine.observe([100] * 19 + [120], 5, 1)[0])
        self.assertEqual(engine.observe([100] * 20, 4, 1), (None, None))
        engine.reset()
        self.assertIsNone(engine.observe([100] * 19 + [80], 6, 1)[0])

    def test_side_filter_and_touch(self):
        engine = Crossing(side="upper")
        engine.observe([100] * 20, 1, 1)
        self.assertIsNone(engine.observe([100] * 20, 2, 1)[0])
        self.assertIsNone(engine.observe([100] * 19 + [80], 3, 1)[0])

    def test_distinct_ticks_with_same_second_timestamp(self):
        engine = Crossing()
        engine.observe([100] * 20, 10, 1)
        self.assertEqual(engine.observe([100] * 19 + [120], 10, 1)[0]["band"], "upper")
        self.assertEqual(engine.observe([100] * 19 + [120], 10, 1), (None, None))

    def test_history_validation(self):
        self.assertEqual(epoch(1_700_000_000_000), 1_700_000_000)
        self.assertEqual(
            history_rows([{"timestamp": 2, "close": 3}, {"timestamp": 1, "close": 4}]),
            [(1, 4), (2, 3)],
        )
        for value in (True, float("nan"), -1):
            with self.assertRaises(ValueError):
                epoch(value)
        with self.assertRaises(ValueError):
            history_rows([{"timestamp": 1, "close": 3}, {"timestamp": 1, "close": 4}])


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "test.sqlite3")
        self.monitor = Monitor(self.store, CONNECTIONS)
        self.row = watch()
        self.state = {
            "engine": Crossing(),
            "history": [(1000 + i * 60, 100) for i in range(21)],
            "display": {},
            "next_history": 9999,
            "last_closed": 0,
        }

    def tick(self, ts, value, now=None):
        self.monitor.tick(
            self.row,
            self.state,
            {"data": {"timestamp": ts, "ltp": value}},
            ts if now is None else now,
        )

    def test_live_tick_and_restart_dedup(self):
        self.tick(2261, 100)
        self.tick(2262, 120)
        self.assertEqual(len(self.store.events()), 1)
        event = self.store.events()[0]
        self.assertEqual(event["bar"], 2260)
        self.assertEqual(event["band"], "upper")
        self.store.event(self.row, event)
        self.assertEqual(len(Store(self.store.path).events()), 1)

    def test_stale_future_and_missing_latest_bar(self):
        self.tick(2261, 100)
        self.tick(2262, 120, 2300)
        self.tick(2263, 120, 2262)
        self.tick(2400, 120)
        self.assertEqual(self.store.events(), [])
        self.assertIn("Waiting", self.state["display"]["status"])

    def test_data_gap_rebaselines(self):
        self.tick(2261, 100)
        self.tick(2300, 120)
        self.assertEqual(self.store.events(), [])

    def test_form_validation(self):
        valid = validate_watch(watch(), CONNECTIONS)
        self.assertEqual(valid["period"], 20)
        for key, value in (
            ("period", True),
            ("period", 1),
            ("deviation", float("inf")),
            ("symbol", "<script>"),
            ("mode", "order"),
            ("connection", "other"),
        ):
            data = watch()
            data[key] = value
            with self.assertRaises(ValueError):
                validate_watch(data, CONNECTIONS)

    def test_closed_candles_no_startup_or_old_alerts(self):
        self.row["mode"] = "close"
        records = [{"timestamp": 1000 + i * 60, "close": 100} for i in range(22)]

        class Client:
            def post(self, url, json):
                self.url = url
                return self

            status_code = 200

            def json(self):
                return {"status": "success", "data": records}

        client = Client()
        self.monitor.refresh(client, self.row, self.state, 2323)
        self.assertEqual(self.store.events(), [])
        records.append({"timestamp": 2320, "close": 120})
        self.monitor.refresh(client, self.row, self.state, 2383)
        self.assertEqual(len(self.store.events()), 1)
        self.monitor.refresh(client, self.row, self.state, 2384)
        self.assertEqual(len(self.store.events()), 1)
        self.assertTrue(client.url.endswith("/api/v1/history"))

    def test_api_csrf_host_secrets_persistence_and_pause(self):
        app = create_app(self.store, self.monitor)
        client = app.test_client()
        base = "http://127.0.0.1:8781"
        self.assertEqual(client.get("/api/state", base_url="http://evil.test").status_code, 403)
        response = client.get("/api/state", base_url=base)
        self.assertNotIn(b"fixture-secret", response.data)
        headers = {"X-Alert-Token": response.json["token"]}
        self.assertEqual(client.post("/api/watches", json=watch(), base_url=base).status_code, 403)
        self.assertEqual(
            client.post("/api/watches", json=watch(), headers=headers, base_url=base).status_code,
            201,
        )
        self.assertEqual(
            client.post("/api/watches", json=watch(), headers=headers, base_url=base).status_code,
            400,
        )
        key = self.store.watches()[0]["id"]
        self.assertEqual(
            client.post(f"/api/watches/{key}/toggle", headers=headers, base_url=base).status_code,
            200,
        )
        self.assertFalse(Store(self.store.path).watches()[0]["enabled"])
        self.assertEqual(
            client.post(f"/api/watches/{key}/delete", headers=headers, base_url=base).status_code,
            200,
        )
        self.assertEqual(self.store.watches(), [])

    def test_background_worker_history_ticks_and_shutdown(self):
        self.store.save(self.row)
        now = time.time()
        records = [{"timestamp": now - 70 - (20 - i) * 60, "close": 100} for i in range(21)]

        class Client:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def post(self, *args, **kwargs):
                return self

            status_code = 200

            def json(self):
                return {"status": "success", "data": records}

        class FakeFeed:
            def __init__(self, *args):
                self.messages = queue.Queue()
                self.overflow = threading.Event()
                self.status = "Synthetic test feed"

            def close(self):
                pass

        with patch("server.httpx.Client", Client), patch("server.Feed", FakeFeed):
            self.monitor.start()
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if self.monitor.states.get("fixture", {}).get("history"):
                        break
                    time.sleep(0.02)
                self.assertTrue(self.monitor.states["fixture"]["history"])
                feed = self.monitor.feeds["stocks"]
                for value in (100, 120):
                    feed.messages.put(
                        {
                            "symbol": "TEST",
                            "exchange": "NSE",
                            "type": "market_data",
                            "data": {"ltp": value, "timestamp": time.time()},
                        }
                    )
                deadline = time.monotonic() + 3
                while not self.store.events() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertEqual(len(self.store.events()), 1)
                self.assertEqual(self.monitor.snapshot()[0]["status"], "Monitoring live ticks")
            finally:
                self.monitor.close()
            self.assertFalse(self.monitor.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
