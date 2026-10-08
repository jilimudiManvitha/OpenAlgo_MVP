# October 8 — after-hours mock latency verification

The user requested starting OpenAlgo, mock testing current latency and fixing errors, then explicitly confirmed the market was closed. No real broker orders were submitted. Main OpenAlgo remains running at http://127.0.0.1:5000, with its original Sandbox mode and 28 schedules preserved; no strategy runners were manually started.

## Mock order measurements

100 requests per case, paced at no more than approximately 8.7 requests/second under the normal 10/second order limit. Measurements include the first cold request. Loopback HTTP goes through the real order REST resource, schema validation, synthetic API-key authentication, order service, latency recorder and SQLite writes. The broker adapter is replaced by a MockTransport response. Sandbox uses actual paper-order/fund/position persistence against disposable databases and a synthetic ₹100 quote.

| Case | HTTP mean ms | P50 ms | P95 ms | P99 ms | Max ms | Under 150 ms |
|---|---:|---:|---:|---:|---:|---:|
| mock_ack_0ms | 8.357 | 8.339 | 12.977 | 14.01 | 42.658 | 100.0% |
| mock_ack_50ms | 61.739 | 58.731 | 64.744 | 110.099 | 200.74 | 99.0% |
| sandbox_fixed_quote | 21.011 | 22.672 | 28.981 | 30.6 | 30.726 | 100.0% |

All 300 requests succeeded; all 100 paper orders were confirmed complete in the fixture ledger. Five deliberate broker rejections returned errors and were counted as failed in telemetry. No unexpected failure occurred. File descriptors stayed at 6 before/after each 100-request case.

Server-handler means were 4.27 ms (immediate mock), 56.78 ms (50 ms delayed mock), and 17.76 ms (Sandbox). HTTP totals also include client connection handling, server dispatch, serialization and test-process scheduling. The delayed mock had one 200.74 ms client outlier despite 110.74 ms maximum handler time; it is retained in the results, not discarded.

The fixture does not include every production middleware or event subscriber and cannot measure actual broker routing, exchange acceptance, fills, peak market load or network jitter. These figures must not replace market-hours live order confirmation measurements. No production latency records are populated with synthetic mock results.

## Running-app read-only probe

| Endpoint | Successful requests after fix | Mean ms |
|---|---:|---:|
| orderbook | 3/3 | 17.48 |
| tradebook | 3/3 | 14.72 |
| positionbook | 3/3 | 84.49 |
| quotes | 2/3 | 69.62 |

Orderbook/Tradebook/Positions are the currently selected Sandbox account views. Quotes use FYERS but are after-hours last-available prices; freshness and market-hours execution are not established. The one failed quote was an expected HTTP 429 with a 3-second retry delay; subsequent requests succeeded.

## Reproduced and fixed error

Before the fix, FYERS data-budget/cooldown responses lost their typed status inside the quote/depth adapter and became HTTP 500 exceptions in the service. They also lost the retry delay. The new shared BrokerDataRateLimitError preserves the typed failure through the adapter and service; both REST endpoints return HTTP 429 with retry_after in the body and Retry-After in the header. The shared budget and its cooldown are unchanged; no bypass, extra retry or stale-price fallback was added.

The regression failed in all four throttle cases before the fix (positive/negative 429 × quote/depth), then passed. Unrelated failures remain HTTP 500. Final targeted suite: 45 passed, covering quote/depth boundaries, shared FYERS budget/pacing, latency monitoring and prior runtime fixes. Critical Python lint and diff whitespace checks passed. No new long-lived resources were introduced by the exception handling fix.

OpenAlgo was gracefully restarted to load the fix. The post-restart probe reproduced 429 with its retry delay and then successful responses; no HTTP 500 or traceback occurred in that probe. Some pre-existing option symbols returned no data after market close; those warnings were not suppressed or converted into fabricated prices.

Schedule configuration SHA256 remains 79593c33ba051796fec66ca8068e4b691ba5ef0e83bc376577bbd32382d588fe. No production order/trade/position records were created by the mock test. Read-only account queries can perform their normal mark-to-market refresh.

Evidence: log/test/oct8-mock/mock-results.json, live-read-results.json (before), live-read-after.json, throttle-before.log, regression-final.log, app-fixed.log. Reproduction tools: .development/oct8-mock/benchmark.py and live_reads.py. The benchmark blocks external socket connections and closes its temporary listener, clients, sessions and telemetry executor.
