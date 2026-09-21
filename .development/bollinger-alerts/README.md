# Bollinger Band alerts

An isolated alert dashboard for selected stocks and crypto, without changing
either existing OpenAlgo application. This is a separate localhost page, not
yet a page inside OpenAlgo. No strategy or order endpoints are called.

## Start

From `D:\Personal\openalgo`:

```powershell
# First setup only; do not overwrite an existing configured .env.
Copy-Item .development/bollinger-alerts/.env.example .development/bollinger-alerts/.env
```

Edit the new `.env` locally. Set each OpenAlgo instance's HTTP host, WebSocket
URL and **OpenAlgo API key**. The crypto port numbers are examples: replace
them with your actual Crypto instance's addresses. Credentials remain on the
server and are never returned to the browser. Remote hosts require HTTPS/WSS.
You can configure stocks only or crypto only. Do not send API keys in chat.
Start each required OpenAlgo instance and log in to its broker normally.

```powershell
& .venv/Scripts/python.exe .development/bollinger-alerts/server.py
```

Open **http://127.0.0.1:8781**, add the exact symbol/exchange from the relevant
OpenAlgo instance, select settings, and click **Add watch**. Click **Enable
sound** to allow browser audio. Up to 20 watches can be saved; pause/resume
and removal are available beside each watch. To change settings, remove the
old watch and add its replacement.

Keep this Python process running and the computer awake. The browser can be
closed while alerts continue to be recorded; audible/visual browser alerts
require an open page and browser permission to play audio. There is no
Telegram, WhatsApp, email or operating-system push delivery in this version.
Use Ctrl+C to stop. Run one instance against this module's database.

## Exact rules

- Defaults: ordinary 5-minute candle closes, 20-period SMA, 2 population
  standard deviations (`ddof=0`). Choose 1m, 5m, 15m, 30m or 1h, period 2–200,
  multiplier 0.1–10, and upper/lower/both bands. These are configurable defaults,
  not a trading recommendation or a tested profitable strategy.
- Upper crossing: previous observed price was at/below its upper band and
  current price is strictly above its newly calculated upper band. Lower
  crossing is the inverse. Band movement can also change this relationship.
  Merely touching a band or remaining outside produces no new crossing.
- **Live**: warm up from completed broker candles, then calculate using the
  latest `period - 1` completed closes plus each fresh streaming last price.
  Bands move with the developing candle. No historical high/low comparison.
- **Candle close**: poll broker history approximately every 10 seconds and
  compare the last two completed candles against each candle's own bands.
  Broker history publishing delays and shared rate limits can delay alerts.
- At most one alert per band per candle. A fresh crossing requires re-entry
  to the corresponding band; repeated intrabar recrossings are suppressed.
  Deduplication persists across restart for the same saved watch.
- Startup, reconnect, a live-data gap over 30 seconds and a missed closed-bar
  gap establish a fresh baseline. Existing outside-band prices and old
  historical crossings are not replayed as current alerts.
- Incoming live timestamps must be epoch seconds or milliseconds, no more
  than 30 seconds old, and not in the future. Older/out-of-order data is
  ignored. Prices must be finite and positive. Conflicting duplicate history
  timestamps are rejected. Missing candles are never manufactured.
- Provider candle start timestamps determine alignment. A live tick requires
  the immediately preceding completed candle; after boundaries it can wait
  for broker history publication. Crossings during warmup, outages or that
  boundary gap can be missed. This is not guaranteed tick-complete delivery.
- Completion uses the full nominal candle duration plus a two-second buffer.
  Shortened final session candles (for example a partial 1h stock candle) are
  not finalized early using an exchange calendar. Prefer 1m/5m/15m when this
  matters. Crypto has no Indian session cutoff.

The dashboard shows connection state, band values, latest observation time,
stale/no-recent-data states and the newest 100 saved alerts. Up to 10,000 alerts
are retained in ignored `alerts.sqlite3`; watches persist there too. A local
CSRF token and loopback host restriction protect configuration mutations.

## Verification and status

Implemented and tested offline on September 17, 2026. **Live broker operation
is not verified and no real watchlist has been activated.** The supplied
connection addresses are templates, not discovered running endpoints.
Both hosts must expose compatible OpenAlgo `/api/v1/history` and WebSocket
LTP APIs. Symbol, timeframe, timestamp and crypto-adapter capabilities depend
on the connected broker. Unsupported data remains unavailable rather than
being substituted with another market's price.

13 Python checks passed: independent band arithmetic, upper/lower crossing,
rearm/deduplication, same-second updates, malformed/stale data, data gaps,
closed candles, persistent settings/events, CSRF/host protection and actual
background history/tick processing/shutdown with synthetic providers. Eight
Chrome UI checks passed with no page errors, including desktop/mobile layouts,
watch creation/removal, pause/resume and sound opt-in. Screenshots were inspected.

```powershell
& .venv/Scripts/python.exe -m unittest discover -s .development/bollinger-alerts -p test_alerts.py -v
& .venv/Scripts/ruff.exe check .development/bollinger-alerts
# Browser verification: start this synthetic-only fixture in another terminal.
& .venv/Scripts/python.exe .development/bollinger-alerts/preview_fixture.py
node .development/bollinger-alerts/verify_browser.cjs
```

Browser artifacts are ignored under `artifacts/`. The fixture never connects to
a broker and uses a temporary database. Dependencies come from the repository's
existing environment; no package or lockfile changes are required.
