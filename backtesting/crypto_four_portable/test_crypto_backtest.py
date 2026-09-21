"""Small synthetic tests; never opens the user's market database or Crypto tree."""

import csv
import tempfile
import unittest
import zipfile
from pathlib import Path

import crypto_backtest as cb
import numpy as np


class CoreTests(unittest.TestCase):
    def test_raw_ha_and_chunk_continuity(self):
        ticks = np.array(
            [
                [0, 100, 2],
                [10_000_000, 110, 3],
                [20_000_000, 90, 4],
                [30_000_000, 106, 5],
                [60_000_000, 108, 6],
                [120_000_000, 107, 1],
            ],
            float,
        )
        state = cb.candle_state()
        events, bars = cb.make_events(ticks, 1, state)
        np.testing.assert_allclose(bars[0, 1:10], [100, 110, 90, 106, 14, 103, 110, 90, 101.5])
        self.assertEqual(bars[1, 6], 102.25)
        split = cb.candle_state()
        batches = [cb.make_events(part, 1, split) for part in (ticks[:2], ticks[2:4], ticks[4:])]
        np.testing.assert_allclose(np.concatenate([p[0] for p in batches]), events, equal_nan=True)
        np.testing.assert_allclose(np.concatenate([p[1] for p in batches]), bars, equal_nan=True)
        np.testing.assert_allclose(split, state)

    def test_five_minutes_from_raw_ticks(self):
        ticks = np.array(
            [[0, 10, 1], [60_000_000, 20, 2], [240_000_000, 5, 3], [300_000_000, 11, 4]], float
        )
        _, bars = cb.make_events(ticks, 5, cb.candle_state())
        np.testing.assert_allclose(bars[0, 1:6], [10, 20, 5, 5, 6])

    def test_midnight_vwap_reset_ha_continuity(self):
        ticks = np.array(
            [[cb.DAY_US - 60_000_000, 10, 1], [cb.DAY_US, 20, 1], [cb.DAY_US + 60_000_000, 30, 1]],
            float,
        )
        events, bars = cb.make_events(ticks, 1, cb.candle_state())
        midnight = events[(events[:, 1] == cb.DAY_US) & (events[:, 2] == 0)][0]
        self.assertEqual(midnight[11], 20)
        self.assertEqual(midnight[4], 10)
        self.assertEqual(len(bars), 2)

    def test_bb_population_variance(self):
        ticks = np.array([[i * 60_000_000, 100 + i, 1] for i in range(25)], float)
        events, bars = cb.make_events(ticks, 1, cb.candle_state())
        closes = bars[:20, 9]
        final20 = events[(events[:, 1] == 19 * 60_000_000) & (events[:, 2] == 1)][0]
        self.assertAlmostEqual(final20[8], closes.mean() + 2 * closes.std(ddof=0))

    @staticmethod
    def fixture(direction=1):
        events = np.full((3, 22), np.nan)
        events[:, 0] = [cb.DAY_US, cb.DAY_US + 1, cb.DAY_US + 60_000_001]
        events[:, 1] = [cb.DAY_US - 60_000_000, cb.DAY_US, cb.DAY_US + 60_000_000]
        events[:, 2] = [1, 0, 0]
        if direction == 1:
            events[:, 3] = [104, 106, 112]
            events[:, 4:8] = [[100, 105, 100, 104], [102, 106, 102, 105], [107, 112, 107, 110]]
            events[:, 8], events[:, 10], events[:, 11] = 99, 90, 98
        else:
            events[:, 3] = [96, 94, 88]
            events[:, 4:8] = [[100, 100, 95, 96], [98, 98, 94, 95], [93, 93, 88, 90]]
            events[:, 8], events[:, 10], events[:, 11] = 110, 101, 102
        events[:, 20], events[:, 21] = events[:, 3], events[:, 0]
        return events

    def test_long_short_fill_and_chunk_parity(self):
        for direction in (1, -1):
            events = self.fixture(direction)
            state = cb.strategy_state()
            args = (direction, 1, 1.0, 100000.0, 0.01, 0.0005, 0.0005)
            whole, marks = cb.trade_events(events, state, *args, final=True)
            split = cb.strategy_state()
            a, am = cb.trade_events(events[:1], split, *args)
            b, bm = cb.trade_events(events[1:], split, *args, final=True)
            np.testing.assert_allclose(np.concatenate((a, b)), whole)
            np.testing.assert_allclose(np.concatenate((am, bm)), marks)
            self.assertEqual(len(whole), 2)
            self.assertEqual(whole[0, 4], 0)
            self.assertAlmostEqual(whole[0, 2], events[1, 20] * (1 + direction * 0.0005))
            self.assertAlmostEqual(whole[:, 1].sum(), 0)

    def test_stale_signal_rejected(self):
        events = self.fixture()
        events[1:, 1] += 60_000_000
        fills, _ = cb.trade_events(
            events, cb.strategy_state(), 1, 1, 2, 100000, 0.01, 0.0005, 0.0005, True
        )
        self.assertEqual(len(fills), 0)

    def test_source_trade_fills_not_ha(self):
        events = self.fixture()[:2]
        events[1, 20] = 107
        fills, _ = cb.trade_events(
            events, cb.strategy_state(), 1, 1, 23.5, 100000, 0.01, 0.0005, 0.0005, True
        )
        self.assertEqual(fills[-1, 4], 8)
        self.assertAlmostEqual(fills[0, 2], 107 * 1.0005)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.out = self.root / "out"
        self.data.mkdir()
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_disguised_zip_duplicate_copy_and_sort(self):
        raw = b"product_symbol,price,size,timestamp,buyer_role\nBTCUSD,100,1,2026-01-01 00:01:00,maker\nBTCUSD,99,2,2026-01-01 00:00:00,taker\n"
        (self.data / "plain.csv").write_bytes(raw)
        with zipfile.ZipFile(self.data / "disguised.csv", "w") as z:
            z.writestr("nested/ticks.csv", raw)
        db, coverage = cb.ingest(self.data, self.out, "BTCUSD", "256MB")
        self.assertEqual(coverage["rows"], 2)
        self.assertEqual(coverage["duplicate_files"], 1)
        self.assertEqual(db.execute("SELECT p FROM ticks ORDER BY t").fetchall(), [(99,), (100,)])
        db.close()
        db, coverage = cb.ingest(self.data, self.out, "BTCUSD", "256MB")
        self.assertEqual(coverage["rows"], 2)
        db.close()

    def test_ambiguous_time_rejected(self):
        (self.data / "bad.csv").write_text(
            "product_symbol,price,size,timestamp,buyer_role\nBTCUSD,100,1,15:05.0,maker\n"
        )
        with self.assertRaisesRegex(ValueError, "full dated timestamps"):
            cb.ingest(self.data, self.out, "BTCUSD", "256MB")

    def test_nonfinite_price_rejected(self):
        (self.data / "bad.csv").write_text(
            "product_symbol,price,size,timestamp,buyer_role\nBTCUSD,nan,1,2026-01-01 00:00:00,maker\n"
        )
        with self.assertRaisesRegex(ValueError, "invalid rows"):
            cb.ingest(self.data, self.out, "BTCUSD", "256MB")

    def test_nonidentical_overlapping_exports_rejected(self):
        header = "product_symbol,price,size,timestamp,buyer_role\n"
        for name, price in (("one.csv", 100), ("two.csv", 101)):
            (self.data / name).write_text(header + f"BTCUSD,{price},1,2026-01-01 00:00:00,maker\n")
        with self.assertRaisesRegex(ValueError, "overlap in time"):
            cb.ingest(self.data, self.out, "BTCUSD", "256MB")

    def test_removed_cached_input_rejected(self):
        header = "product_symbol,price,size,timestamp,buyer_role\n"
        for name, day in (("one.csv", 1), ("two.csv", 2)):
            (self.data / name).write_text(header + f"BTCUSD,100,1,2026-01-0{day} 00:00:00,maker\n")
        db, _ = cb.ingest(self.data, self.out, "BTCUSD", "256MB")
        db.close()
        (self.data / "two.csv").unlink()
        with self.assertRaisesRegex(ValueError, "Input files changed"):
            cb.ingest(self.data, self.out, "BTCUSD", "256MB")

    def test_end_to_end_and_resume(self):
        folder = self.data / "btcfut"
        folder.mkdir()
        with (folder / "ticks.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["product_symbol", "price", "size", "timestamp", "buyer_role"])
            for i in range(500):
                w.writerow(
                    [
                        "BTCUSD",
                        100 + 10 * np.sin(i / 20) + i / 100,
                        1,
                        cb.iso(1_767_225_600_000_000 + i * 20_000_000),
                        "maker",
                    ]
                )
        settings = {
            "memory": "256MB",
            "capital": 100000,
            "unit": 0.01,
            "fee": 0.0005,
            "slippage": 0.0005,
            "benchmark_ticks": 0,
        }
        result = cb.run_symbol("BTCUSD", str(self.data), str(self.out), settings)
        cb.report(self.out, [result])
        self.assertEqual(len(result["strategies"]), 4)
        self.assertTrue(all(r["fill_cashflow_reconciled"] for r in result["strategies"]))
        self.assertEqual(result, cb.run_symbol("BTCUSD", str(self.data), str(self.out), settings))
        self.assertTrue((self.out / "index.html").is_file())
        with (self.out / "BTCUSD/candles_1m.csv").open() as f:
            bars = list(csv.DictReader(f))
        self.assertEqual(float(bars[-1]["complete"]), 0)


if __name__ == "__main__":
    unittest.main()
