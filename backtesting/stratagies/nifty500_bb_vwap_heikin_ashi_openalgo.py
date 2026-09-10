"""
NIFTY 500 | BB(20,2,SMA) + VWAP + HEIKIN ASHI
OpenAlgo + Fyers broker connection

Strategy:
1. Universe: NIFTY 500 equities.
2. Stock filter: TOP GAINERS OR VOLUME SHOCKER.
   - Top gainer: current LTP % change >= TOP_GAINER_PCT.
   - Volume shocker: current day volume >= VOLUME_SHOCKER_MULTIPLIER
     x average volume of the last 20 completed trading days.
3. Timeframe: 5 minutes.
4. Signal candle:
   - Heikin Ashi candle is bullish.
   - HA close crosses above BB upper band.
   - HA close > VWAP.
   - HA candle has NO LOWER WICK.
5. Entry candle:
   - Must be the immediate next completed 5-minute candle.
   - HA close > signal candle HA high.
   - HA close > BB upper.
   - HA close > VWAP.
   - Bullish HA candle.
   - NO LOWER WICK.
6. Position sizing:
   - Capital = Rs 10,000
   - Leverage = 5x
   - Max notional = Rs 50,000
   - Quantity = floor(50,000 / actual entry price)
7. Risk/reward:
   - Fixed risk = Rs 10/share.
   - Initial stop = entry - Rs 10.
   - 1:2 target = entry + Rs 20.
   - Default behavior below: once 2R is reached, keep trailing and
     exit when HA close falls below BB middle.
   - Before 2R, the Rs 10/share stop is active.
8. Exit:
   - Before 2R: stop at entry - Rs 10.
   - At/after 2R: BB middle trail.
   - BB middle exit also works after entry.
   - Square off by 15:20 IST.
9. Signals use COMPLETED 5-minute candles only.
10. Live orders are OFF by default. Set LIVE_TRADING=true to enable.

Important:
- OpenAlgo is the broker abstraction. If Fyers is connected inside OpenAlgo,
  orders are routed through the Fyers connection.
- NIFTY 500 constituents are downloaded from the official Nifty Indices CSV.
- You can override the universe with NIFTY500_SYMBOLS="SBIN,INFY,...".
- For the 20-day volume baseline, the script requests daily history.
  Configure VOLUME_AVG_START_DATE if needed.
"""

import io
import math
import os
import time
import urllib.request
from datetime import datetime, time as dt_time

import numpy as np
import pandas as pd
import pytz

from openalgo import api, ta


# ============================================================
# CONFIGURATION
# ============================================================

STRATEGY_NAME = "NIFTY500_BB_VWAP_HA"

EXCHANGE = os.getenv("OPENALGO_STRATEGY_EXCHANGE") or os.getenv("EXCHANGE", "NSE")
if EXCHANGE not in ("NSE", "BSE"):
    EXCHANGE = "NSE"

PRODUCT = "MIS"
PRICE_TYPE = "MARKET"

TIMEFRAME = "5m"

BB_LENGTH = 20
BB_MULTIPLIER = 2.0

CAPITAL = float(os.getenv("CAPITAL", "10000"))
LEVERAGE = float(os.getenv("LEVERAGE", "5"))
MAX_NOTIONAL = CAPITAL * LEVERAGE

RISK_PER_SHARE = float(os.getenv("RISK_PER_SHARE", "10"))
REWARD_R_MULTIPLE = float(os.getenv("REWARD_R_MULTIPLE", "2"))

# True:
#   Entry 100 -> Stop 90 -> 2R = 120.
#   When 120 is reached, do NOT immediately exit; switch to BB-middle trail.
TRAIL_AFTER_2R = os.getenv("TRAIL_AFTER_2R", "true").lower() == "true"

TOP_GAINER_PCT = float(os.getenv("TOP_GAINER_PCT", "1.0"))
VOLUME_SHOCKER_MULTIPLIER = float(os.getenv("VOLUME_SHOCKER_MULTIPLIER", "2.0"))

# To reduce API load, only the strongest candidates are evaluated.
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "30"))

# One position at a time.
ONE_POSITION_AT_A_TIME = True
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "3"))

# Strategy entry window.
ENTRY_START = dt_time(9, 20)
ENTRY_END = dt_time(15, 0)

# Forced square-off.
SQUARE_OFF_TIME = dt_time(15, 20)

# Polling frequency.
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "10"))

# The current day's 5-minute history.
INTRADAY_START_DATE = os.getenv("INTRADAY_START_DATE", "")
INTRADAY_END_DATE = os.getenv("INTRADAY_END_DATE", "")

# Daily history range used to obtain the latest 20 completed daily volumes.
# It intentionally uses explicit start/end date controls.
VOLUME_AVG_START_DATE = os.getenv("VOLUME_AVG_START_DATE", "2026-01-01")
VOLUME_AVG_END_DATE = os.getenv("VOLUME_AVG_END_DATE", "")

# Live trading is deliberately OFF unless explicitly enabled.
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

# Official Nifty 500 constituent CSV.
NIFTY500_URL = (
    "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
)

# Number of quotes sent per API request.
QUOTE_CHUNK_SIZE = int(os.getenv("QUOTE_CHUNK_SIZE", "100"))

IST = pytz.timezone("Asia/Kolkata")

api_key = os.getenv("OPENALGO_API_KEY", "")
host = os.getenv("HOST_SERVER") or os.getenv(
    "OPENALGO_HOST", "http://127.0.0.1:5000"
)

if not api_key:
    raise RuntimeError("OPENALGO_API_KEY is not set.")

client = api(api_key=api_key, host=host)


# ============================================================
# RUNTIME STATE
# ============================================================

class PositionState:
    def __init__(self):
        self.symbol = None
        self.quantity = 0
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.target_reached = False
        self.entry_order_id = None
        self.exit_order_id = None
        self.entry_timestamp = None

    @property
    def active(self):
        return self.symbol is not None and self.quantity > 0


position = PositionState()

# symbol -> signal information
pending_signals = {}

# symbol -> average daily volume
average_daily_volume = {}

trades_today = 0
trade_date = None

last_processed_candle = None
last_scan_candle = None

universe = []


# ============================================================
# UTILITY
# ============================================================

def now_ist():
    return datetime.now(IST)


def current_date_string():
    return now_ist().strftime("%Y-%m-%d")


def get_intraday_dates():
    today = current_date_string()
    return (
        INTRADAY_START_DATE or today,
        INTRADAY_END_DATE or today,
    )


def get_volume_dates():
    return (
        VOLUME_AVG_START_DATE,
        VOLUME_AVG_END_DATE or current_date_string(),
    )


def print_header():
    print("🔁 OpenAlgo Python Bot is running.")
    print(f"Strategy       : {STRATEGY_NAME}")
    print(f"Exchange       : {EXCHANGE}")
    print(f"Product        : {PRODUCT}")
    print(f"Timeframe      : {TIMEFRAME}")
    print(f"BB             : {BB_LENGTH}, {BB_MULTIPLIER} SMA")
    print(f"Capital        : ₹{CAPITAL:,.2f}")
    print(f"Leverage       : {LEVERAGE:.1f}x")
    print(f"Max Notional   : ₹{MAX_NOTIONAL:,.2f}")
    print(f"Risk/share     : ₹{RISK_PER_SHARE:,.2f}")
    print(f"Target R       : {REWARD_R_MULTIPLE:.1f}R")
    print(f"Live Trading   : {LIVE_TRADING}")
    print(f"Entry Window   : {ENTRY_START} - {ENTRY_END}")
    print(f"Square Off     : {SQUARE_OFF_TIME}")


def in_entry_window(dt):
    t = dt.time().replace(second=0, microsecond=0)
    return ENTRY_START <= t <= ENTRY_END


def is_after_square_off(dt):
    return dt.time() >= SQUARE_OFF_TIME


def normalize_index(df):
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    if df.index.tz is None:
        df.index = df.index.tz_localize(IST)
    else:
        df.index = df.index.tz_convert(IST)

    return df.sort_index()


def validate_ohlcv_dataframe(df):
    if df is None or df.empty:
        return False

    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(set(df.columns)):
        return False

    try:
        df[["open", "high", "low", "close", "volume"]] = (
            df[["open", "high", "low", "close", "volume"]]
            .apply(pd.to_numeric, errors="coerce")
        )
    except Exception:
        return False

    df.dropna(
        subset=["open", "high", "low", "close", "volume"],
        inplace=True,
    )

    return not df.empty


def get_completed_5m_data(df, current_dt):
    """
    History timestamps represent the beginning of each 5-minute candle.
    A candle is completed when its timestamp is before the current 5-minute
    bucket.
    """
    if not validate_ohlcv_dataframe(df):
        return None

    df = normalize_index(df)

    current_bucket = current_dt.replace(
        minute=(current_dt.minute // 5) * 5,
        second=0,
        microsecond=0,
    )

    completed = df[df.index < current_bucket].copy()

    if completed.empty:
        return None

    return completed


# ============================================================
# NIFTY 500 UNIVERSE
# ============================================================

def load_nifty500_universe():
    override = os.getenv("NIFTY500_SYMBOLS", "").strip()

    if override:
        symbols = [
            s.strip().upper()
            for s in override.split(",")
            if s.strip()
        ]
        print(f"Using NIFTY500_SYMBOLS override: {len(symbols)} symbols")
        return symbols

    print("Downloading NIFTY 500 constituent list...")

    request = urllib.request.Request(
        NIFTY500_URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()

    df = pd.read_csv(io.BytesIO(raw))

    symbol_col = None
    for col in df.columns:
        if str(col).strip().lower() == "symbol":
            symbol_col = col
            break

    if symbol_col is None:
        raise RuntimeError(
            f"Could not find Symbol column in NIFTY 500 CSV. "
            f"Columns: {list(df.columns)}"
        )

    symbols = (
        df[symbol_col]
        .astype(str)
        .str.strip()
        .str.upper()
        .replace("NAN", np.nan)
        .dropna()
        .drop_duplicates()
        .tolist()
    )

    if not symbols:
        raise RuntimeError("NIFTY 500 universe is empty.")

    print(f"NIFTY 500 universe loaded: {len(symbols)} symbols")
    return symbols


# ============================================================
# MARKET DATA
# ============================================================

def get_multiquotes(symbols):
    """
    Uses OpenAlgo multiquotes. The SDK documentation shows multiquotes
    returning status + results with symbol/exchange/data.
    """
    all_results = []

    for start in range(0, len(symbols), QUOTE_CHUNK_SIZE):
        chunk = symbols[start:start + QUOTE_CHUNK_SIZE]

        instruments = [
            {"symbol": symbol, "exchange": EXCHANGE}
            for symbol in chunk
        ]

        try:
            response = client.multiquotes(symbols=instruments)
            print(f"MultiQuotes response: {response}")

            if not isinstance(response, dict):
                continue

            if response.get("status") != "success":
                print(f"MultiQuotes failed: {response}")
                continue

            results = response.get("results", [])
            all_results.extend(results)

        except Exception as exc:
            print(f"MultiQuotes error: {exc}")

    return all_results


def fetch_intraday_history(symbol):
    start_date, end_date = get_intraday_dates()

    try:
        df = client.history(
            symbol=symbol,
            exchange=EXCHANGE,
            interval=TIMEFRAME,
            start_date=start_date,
            end_date=end_date,
        )
        print(
            f"History fetched: {symbol} | "
            f"{start_date} -> {end_date} | rows={0 if df is None else len(df)}"
        )
        return df
    except Exception as exc:
        print(f"History error {symbol}: {exc}")
        return None


def fetch_daily_volume_baseline(symbol):
    """
    Fetch explicit daily history range and use the latest 20 completed
    daily candles before today.
    """
    start_date, end_date = get_volume_dates()

    try:
        df = client.history(
            symbol=symbol,
            exchange=EXCHANGE,
            interval="D",
            start_date=start_date,
            end_date=end_date,
        )

        if not validate_ohlcv_dataframe(df):
            return None

        df = normalize_index(df)

        today = now_ist().date()
        completed = df[df.index.date < today].copy()

        if completed.empty:
            return None

        latest_20 = completed.tail(20)

        if len(latest_20) < 10:
            return None

        avg_volume = float(latest_20["volume"].mean())

        if not np.isfinite(avg_volume) or avg_volume <= 0:
            return None

        return avg_volume

    except Exception as exc:
        print(f"Daily volume baseline error {symbol}: {exc}")
        return None


def build_volume_baseline(symbols):
    print(
        "\nBuilding 20-day average daily-volume baseline. "
        "This can generate many API calls on first startup."
    )

    success = 0

    for i, symbol in enumerate(symbols, start=1):
        avg = fetch_daily_volume_baseline(symbol)

        if avg is not None:
            average_daily_volume[symbol] = avg
            success += 1

        if i % 25 == 0:
            print(
                f"Volume baseline progress: {i}/{len(symbols)} | "
                f"valid={success}"
            )

    print(
        f"Volume baseline completed: {success}/{len(symbols)} symbols"
    )


# ============================================================
# STOCK FILTER
# ============================================================

def rank_candidates(quote_results):
    candidates = []

    for item in quote_results:
        symbol = str(item.get("symbol", "")).strip().upper()
        data = item.get("data") or {}

        if not symbol:
            continue

        try:
            ltp = float(data.get("ltp", 0) or 0)
            prev_close = float(data.get("prev_close", 0) or 0)
            volume = float(data.get("volume", 0) or 0)
        except (TypeError, ValueError):
            continue

        if ltp <= 0 or prev_close <= 0:
            continue

        gain_pct = ((ltp - prev_close) / prev_close) * 100.0

        avg_volume = average_daily_volume.get(symbol)
        volume_ratio = 0.0

        if avg_volume and avg_volume > 0:
            volume_ratio = volume / avg_volume

        is_top_gainer = gain_pct >= TOP_GAINER_PCT
        is_volume_shocker = volume_ratio >= VOLUME_SHOCKER_MULTIPLIER

        if not (is_top_gainer or is_volume_shocker):
            continue

        score = max(
            gain_pct / max(TOP_GAINER_PCT, 0.01),
            volume_ratio / max(VOLUME_SHOCKER_MULTIPLIER, 0.01),
        )

        reasons = []

        if is_top_gainer:
            reasons.append(f"GAIN {gain_pct:.2f}%")

        if is_volume_shocker:
            reasons.append(f"RVOL-DAY {volume_ratio:.2f}x")

        candidates.append(
            {
                "symbol": symbol,
                "ltp": ltp,
                "gain_pct": gain_pct,
                "volume": volume,
                "volume_ratio": volume_ratio,
                "score": score,
                "reason": " + ".join(reasons),
            }
        )

    candidates.sort(key=lambda x: x["score"], reverse=True)

    return candidates[:MAX_CANDIDATES]


# ============================================================
# HEIKIN ASHI + INDICATORS
# ============================================================

def add_heikin_ashi(df):
    df = df.copy()

    ha_close = (
        df["open"] +
        df["high"] +
        df["low"] +
        df["close"]
    ) / 4.0

    ha_open = pd.Series(index=df.index, dtype=float)

    if len(df) > 0:
        ha_open.iloc[0] = (
            float(df["open"].iloc[0]) +
            float(df["close"].iloc[0])
        ) / 2.0

        for i in range(1, len(df)):
            ha_open.iloc[i] = (
                ha_open.iloc[i - 1] +
                ha_close.iloc[i - 1]
            ) / 2.0

    ha_high = pd.concat(
        [df["high"], ha_open, ha_close],
        axis=1,
    ).max(axis=1)

    ha_low = pd.concat(
        [df["low"], ha_open, ha_close],
        axis=1,
    ).min(axis=1)

    df["ha_open"] = ha_open
    df["ha_high"] = ha_high
    df["ha_low"] = ha_low
    df["ha_close"] = ha_close

    return df


def calculate_indicators(df):
    df = add_heikin_ashi(df)

    # BB is calculated on Heikin Ashi close to match the strategy wording:
    # "HA close crosses above Bollinger upper band."
    bb_upper, bb_middle, bb_lower = ta.bbands(
        df["ha_close"],
        period=BB_LENGTH,
        std_dev=BB_MULTIPLIER,
    )

    df["bb_upper"] = bb_upper
    df["bb_middle"] = bb_middle
    df["bb_lower"] = bb_lower

    # Session VWAP.
    df["vwap"] = ta.vwap(
        df["high"],
        df["low"],
        df["close"],
        df["volume"],
        source="hlc3",
        anchor="Session",
    )

    return df


def no_lower_wick(row):
    """
    For a bullish HA candle, no lower wick means HA low == HA open.

    A very small numerical tolerance is used because HA values are
    calculated from floating-point arithmetic.
    """
    if row["ha_close"] <= row["ha_open"]:
        return False

    tolerance = max(
        1e-8,
        abs(float(row["ha_open"])) * 1e-10,
    )

    return abs(
        float(row["ha_low"]) - float(row["ha_open"])
    ) <= tolerance


def bullish_ha(row):
    return float(row["ha_close"]) > float(row["ha_open"])


# ============================================================
# SIGNAL LOGIC
# ============================================================

def signal_candle_condition(df, i):
    if i <= 0:
        return False

    row = df.iloc[i]
    prev = df.iloc[i - 1]

    required = [
        "ha_open",
        "ha_high",
        "ha_low",
        "ha_close",
        "bb_upper",
        "bb_middle",
        "vwap",
    ]

    if any(pd.isna(row[c]) for c in required):
        return False

    if any(pd.isna(prev[c]) for c in ["ha_close", "bb_upper"]):
        return False

    # Cross above BB upper.
    crossed_upper = (
        float(prev["ha_close"]) <= float(prev["bb_upper"])
        and float(row["ha_close"]) > float(row["bb_upper"])
    )

    above_vwap = float(row["ha_close"]) > float(row["vwap"])

    return (
        crossed_upper
        and above_vwap
        and bullish_ha(row)
        and no_lower_wick(row)
    )


def entry_candle_condition(df, signal_i, entry_i):
    if entry_i != signal_i + 1:
        return False

    if entry_i >= len(df):
        return False

    signal = df.iloc[signal_i]
    entry = df.iloc[entry_i]

    required = [
        "ha_open",
        "ha_high",
        "ha_low",
        "ha_close",
        "bb_upper",
        "vwap",
    ]

    if any(pd.isna(entry[c]) for c in required):
        return False

    # "Cross above the signal candle" is implemented as:
    # previous signal HA close <= signal HA high
    # and entry HA close > signal HA high.
    crossed_signal_high = (
        float(signal["ha_close"]) <= float(signal["ha_high"])
        and float(entry["ha_close"]) > float(signal["ha_high"])
    )

    above_upper = float(entry["ha_close"]) > float(entry["bb_upper"])
    above_vwap = float(entry["ha_close"]) > float(entry["vwap"])

    return (
        crossed_signal_high
        and above_upper
        and above_vwap
        and bullish_ha(entry)
        and no_lower_wick(entry)
    )


def find_latest_signal(df):
    """
    Returns the latest signal candle index if the most recent completed
    candle is a signal candle.
    """
    if len(df) < BB_LENGTH + 2:
        return None

    i = len(df) - 1

    if signal_candle_condition(df, i):
        return i

    return None


# ============================================================
# POSITION SIZING
# ============================================================

def calculate_quantity(entry_price):
    if entry_price <= 0:
        return 0

    qty = math.floor(MAX_NOTIONAL / entry_price)

    return max(0, int(qty))


def calculate_risk_levels(entry_price):
    stop_price = entry_price - RISK_PER_SHARE
    target_price = (
        entry_price +
        (RISK_PER_SHARE * REWARD_R_MULTIPLE)
    )

    return stop_price, target_price


# ============================================================
# OPENALGO ORDER FUNCTIONS
# ============================================================

def order_success(response):
    if not isinstance(response, dict):
        return False

    return str(response.get("status", "")).lower() == "success"


def place_buy_order(symbol, quantity):
    if not LIVE_TRADING:
        print(
            f"[PAPER] BUY {symbol} qty={quantity} "
            f"(live order disabled)"
        )
        return {
            "status": "paper",
            "orderid": f"PAPER-BUY-{symbol}-{int(time.time())}",
        }

    try:
        response = client.placeorder(
            strategy=STRATEGY_NAME,
            symbol=symbol,
            action="BUY",
            exchange=EXCHANGE,
            price_type=PRICE_TYPE,
            product=PRODUCT,
            quantity=quantity,
        )

        print(f"BUY order response: {response}")
        return response

    except Exception as exc:
        print(f"BUY order exception: {exc}")
        return {"status": "error", "message": str(exc)}


def place_sell_order(symbol, quantity):
    if not LIVE_TRADING:
        print(
            f"[PAPER] SELL {symbol} qty={quantity} "
            f"(live order disabled)"
        )
        return {
            "status": "paper",
            "orderid": f"PAPER-SELL-{symbol}-{int(time.time())}",
        }

    try:
        response = client.placeorder(
            strategy=STRATEGY_NAME,
            symbol=symbol,
            action="SELL",
            exchange=EXCHANGE,
            price_type=PRICE_TYPE,
            product=PRODUCT,
            quantity=quantity,
        )

        print(f"SELL order response: {response}")
        return response

    except Exception as exc:
        print(f"SELL order exception: {exc}")
        return {"status": "error", "message": str(exc)}


def get_confirmed_fill_price(order_id, fallback_price):
    """
    Confirm order status. Never assume an order was filled merely because
    the initial placeorder call returned.
    """
    if not LIVE_TRADING:
        return fallback_price

    if not order_id:
        return None

    for _ in range(10):
        try:
            response = client.orderstatus(
                order_id=order_id,
                strategy=STRATEGY_NAME,
            )

            print(f"Order status response: {response}")

            if not isinstance(response, dict):
                time.sleep(1)
                continue

            if response.get("status") != "success":
                time.sleep(1)
                continue

            data = response.get("data") or {}
            order_status = str(
                data.get("order_status", "")
            ).lower()

            if order_status == "complete":
                avg_price = data.get("average_price")

                try:
                    avg_price = float(avg_price)
                except (TypeError, ValueError):
                    avg_price = fallback_price

                return avg_price

            if order_status in {
                "rejected",
                "cancelled",
                "expired",
            }:
                print(
                    f"Order not filled: status={order_status} "
                    f"reason={data.get('rejection_reason', '')}"
                )
                return None

        except Exception as exc:
            print(f"Order status exception: {exc}")

        time.sleep(1)

    print("Order fill confirmation timed out.")
    return None


def get_strategy_open_positions():
    """
    Read strategy position book so a restart does not blindly create
    another position.
    """
    try:
        response = client.positionbook()
        print(f"Positionbook response: {response}")

        if not isinstance(response, dict):
            return []

        if response.get("status") != "success":
            return []

        positions = response.get("data", [])

        if not isinstance(positions, list):
            return []

        result = []

        for row in positions:
            try:
                symbol = str(row.get("symbol", "")).upper()
                exchange = str(row.get("exchange", ""))
                product = str(row.get("product", ""))
                quantity = int(float(row.get("quantity", 0) or 0))
                average_price = float(
                    row.get("average_price", 0) or 0
                )
            except (TypeError, ValueError):
                continue

            if (
                exchange == EXCHANGE
                and product == PRODUCT
                and quantity != 0
            ):
                result.append(
                    {
                        "symbol": symbol,
                        "quantity": quantity,
                        "average_price": average_price,
                    }
                )

        return result

    except Exception as exc:
        print(f"Positionbook error: {exc}")
        return []


def initialize_existing_position():
    global position

    positions = get_strategy_open_positions()

    if not positions:
        return

    # Strategy is intended to maintain one position.
    row = positions[0]

    if row["quantity"] <= 0:
        print(
            "Existing short/non-long position detected. "
            "This long-only strategy will not manage it as a long."
        )
        return

    position.symbol = row["symbol"]
    position.quantity = row["quantity"]
    position.entry_price = row["average_price"]
    position.stop_price, position.target_price = (
        calculate_risk_levels(position.entry_price)
    )
    position.target_reached = False

    print(
        f"Existing LONG restored: {position.symbol} "
        f"qty={position.quantity} "
        f"entry={position.entry_price:.2f} "
        f"stop={position.stop_price:.2f} "
        f"target={position.target_price:.2f}"
    )


# ============================================================
# ENTRY / EXIT
# ============================================================

def enter_long(symbol, entry_candle):
    global trades_today, position

    if position.active:
        print("Entry skipped: position already active.")
        return False

    if trades_today >= MAX_TRADES_PER_DAY:
        print(
            f"Entry skipped: MAX_TRADES_PER_DAY={MAX_TRADES_PER_DAY}"
        )
        return False

    entry_reference_price = float(entry_candle["ha_close"])

    quantity = calculate_quantity(entry_reference_price)

    if quantity <= 0:
        print(
            f"Entry skipped: quantity=0 for price "
            f"{entry_reference_price:.2f}"
        )
        return False

    print(
        f"\nENTRY SIGNAL CONFIRMED | {symbol} | "
        f"reference={entry_reference_price:.2f} | "
        f"qty={quantity}"
    )

    response = place_buy_order(symbol, quantity)

    if not LIVE_TRADING:
        fill_price = entry_reference_price
    else:
        if not order_success(response):
            print("BUY rejected/failed. No position state created.")
            return False

        order_id = response.get("orderid")

        if not order_id:
            print(
                "BUY response has no orderid. "
                "No position state created."
            )
            return False

        fill_price = get_confirmed_fill_price(
            order_id,
            entry_reference_price,
        )

        if fill_price is None:
            print(
                "BUY was not confirmed filled. "
                "No position state created."
            )
            return False

    stop_price, target_price = calculate_risk_levels(fill_price)

    position.symbol = symbol
    position.quantity = quantity
    position.entry_price = fill_price
    position.stop_price = stop_price
    position.target_price = target_price
    position.target_reached = False
    position.entry_order_id = (
        response.get("orderid") if isinstance(response, dict) else None
    )
    position.entry_timestamp = now_ist()

    trades_today += 1

    print(
        f"LONG OPENED | {symbol} | qty={quantity} | "
        f"entry={fill_price:.2f} | "
        f"stop={stop_price:.2f} | "
        f"2R target={target_price:.2f} | "
        f"trades_today={trades_today}"
    )

    return True


def exit_position(reason, reference_price=None):
    global position

    if not position.active:
        return False

    symbol = position.symbol
    quantity = position.quantity

    print(
        f"\nEXIT REQUEST | {symbol} | qty={quantity} | "
        f"reason={reason} | "
        f"reference={reference_price}"
    )

    response = place_sell_order(symbol, quantity)

    if not LIVE_TRADING:
        position = PositionState()
        print(f"[PAPER] Position closed: {reason}")
        return True

    if not order_success(response):
        print(
            f"SELL rejected/failed. Position state retained. "
            f"Response={response}"
        )
        return False

    order_id = response.get("orderid")

    if not order_id:
        print(
            "SELL response has no orderid. "
            "Position state retained."
        )
        return False

    fill_price = get_confirmed_fill_price(
        order_id,
        reference_price or position.entry_price,
    )

    if fill_price is None:
        print(
            "SELL was not confirmed filled. "
            "Position state retained."
        )
        return False

    pnl = (
        (fill_price - position.entry_price)
        * position.quantity
    )

    print(
        f"LONG CLOSED | {symbol} | "
        f"exit={fill_price:.2f} | "
        f"entry={position.entry_price:.2f} | "
        f"qty={position.quantity} | "
        f"PnL≈₹{pnl:,.2f} | "
        f"reason={reason}"
    )

    position = PositionState()

    return True


def manage_position(symbol_df):
    if not position.active:
        return

    if symbol_df is None or symbol_df.empty:
        return

    row = symbol_df.iloc[-1]

    if pd.isna(row["ha_close"]) or pd.isna(row["bb_middle"]):
        return

    ha_close = float(row["ha_close"])
    bb_middle = float(row["bb_middle"])

    # 1) 2R target reached.
    if not position.target_reached:
        if ha_close >= position.target_price:
            print(
                f"2R reached: {position.symbol} | "
                f"HA close={ha_close:.2f} | "
                f"target={position.target_price:.2f}"
            )

            if TRAIL_AFTER_2R:
                position.target_reached = True
                print(
                    f"TRAIL ACTIVATED | Exit when HA close "
                    f"< BB middle ({bb_middle:.2f})"
                )
            else:
                exit_position(
                    "2R target reached",
                    reference_price=ha_close,
                )
                return

    # 2) Initial fixed risk stop before 2R.
    if not position.target_reached:
        if ha_close <= position.stop_price:
            exit_position(
                "Initial ₹10/share stop hit",
                reference_price=ha_close,
            )
            return

    # 3) BB middle trail.
    if ha_close < bb_middle:
        exit_position(
            "HA close below BB middle",
            reference_price=ha_close,
        )


# ============================================================
# CANDLE PROCESSING
# ============================================================

def process_symbol(symbol, current_dt):
    """
    Fetch current-day 5m history, use only completed candles,
    calculate indicators, manage an open position, and evaluate
    pending signal -> immediate next candle entry.
    """
    df = fetch_intraday_history(symbol)

    if df is None:
        return

    completed = get_completed_5m_data(df, current_dt)

    if completed is None:
        return

    if len(completed) < BB_LENGTH + 2:
        print(
            f"{symbol}: not enough completed candles "
            f"({len(completed)})"
        )
        return

    try:
        completed = calculate_indicators(completed)
    except Exception as exc:
        print(f"Indicator error {symbol}: {exc}")
        return

    completed = completed.dropna(
        subset=[
            "ha_open",
            "ha_high",
            "ha_low",
            "ha_close",
            "bb_upper",
            "bb_middle",
            "bb_lower",
            "vwap",
        ]
    )

    if completed.empty:
        return

    # Manage the open position only for its own symbol.
    if position.active and position.symbol == symbol:
        manage_position(completed)

        if not position.active:
            # Position was closed. Continue so no new entry is taken
            # from the same candle.
            return

    latest_timestamp = completed.index[-1]

    # Pending signal must be immediately followed by this candle.
    pending = pending_signals.get(symbol)

    if pending is not None:
        signal_timestamp = pending["timestamp"]
        signal_high = pending["ha_high"]

        expected_entry_timestamp = (
            signal_timestamp + pd.Timedelta(minutes=5)
        )

        if latest_timestamp == expected_entry_timestamp:
            signal_i = completed.index.get_loc(signal_timestamp)

            if isinstance(signal_i, slice):
                signal_i = signal_i.start

            entry_i = completed.index.get_loc(latest_timestamp)

            if isinstance(entry_i, slice):
                entry_i = entry_i.start

            if entry_i == signal_i + 1:
                valid_entry = entry_candle_condition(
                    completed,
                    signal_i,
                    entry_i,
                )

                print(
                    f"ENTRY CHECK | {symbol} | "
                    f"signal={signal_timestamp} | "
                    f"entry={latest_timestamp} | "
                    f"valid={valid_entry} | "
                    f"entry_close={completed.iloc[entry_i]['ha_close']:.2f} | "
                    f"signal_high={signal_high:.2f}"
                )

                if valid_entry:
                    if in_entry_window(current_dt):
                        entered = enter_long(
                            symbol,
                            completed.iloc[entry_i],
                        )

                        if entered:
                            pending_signals.pop(symbol, None)
                            return
                    else:
                        print(
                            f"Entry candle valid but outside entry window: "
                            f"{current_dt.time()}"
                        )

                # The immediate next candle has now been consumed.
                pending_signals.pop(symbol, None)

        elif latest_timestamp > expected_entry_timestamp:
            # We missed the exact next candle; invalidate the signal.
            pending_signals.pop(symbol, None)

    # Generate a new signal only if we are not already long.
    if position.active:
        return

    if not in_entry_window(current_dt):
        return

    signal_i = len(completed) - 1

    if signal_candle_condition(completed, signal_i):
        signal_row = completed.iloc[signal_i]
        signal_timestamp = completed.index[signal_i]

        pending_signals[symbol] = {
            "timestamp": signal_timestamp,
            "ha_high": float(signal_row["ha_high"]),
            "ha_close": float(signal_row["ha_close"]),
            "bb_upper": float(signal_row["bb_upper"]),
            "vwap": float(signal_row["vwap"]),
        }

        print(
            f"\nSIGNAL CANDLE | {symbol} | "
            f"time={signal_timestamp} | "
            f"HA close={signal_row['ha_close']:.2f} | "
            f"HA high={signal_row['ha_high']:.2f} | "
            f"BB upper={signal_row['bb_upper']:.2f} | "
            f"VWAP={signal_row['vwap']:.2f} | "
            f"NO LOWER WICK=True"
        )


# ============================================================
# SCANNER
# ============================================================

def scan_candidates():
    quote_results = get_multiquotes(universe)

    candidates = rank_candidates(quote_results)

    print("\n" + "=" * 90)
    print("STOCK FILTER")
    print(
        f"Universe=NIFTY500 | "
        f"TopGainer>={TOP_GAINER_PCT:.2f}% OR "
        f"DayVolume>={VOLUME_SHOCKER_MULTIPLIER:.2f}x 20D Avg"
    )
    print("=" * 90)

    if not candidates:
        print("No candidates.")
        return []

    for item in candidates:
        print(
            f"{item['symbol']:15s} "
            f"LTP={item['ltp']:10.2f} "
            f"GAIN={item['gain_pct']:7.2f}% "
            f"DAY_RVOL={item['volume_ratio']:7.2f}x "
            f"{item['reason']}"
        )

    return candidates


# ============================================================
# DAILY STATE
# ============================================================

def reset_daily_state_if_needed():
    global trade_date
    global trades_today
    global pending_signals

    today = current_date_string()

    if trade_date != today:
        trade_date = today
        trades_today = 0
        pending_signals = {}

        print(
            f"\nNEW TRADING DAY: {today} | "
            f"trades_today reset to 0"
        )


def force_square_off_if_required():
    if not position.active:
        return

    if is_after_square_off(now_ist()):
        exit_position(
            "Mandatory square-off at 15:20 IST",
            reference_price=position.entry_price,
        )


# ============================================================
# MAIN LOOP
# ============================================================

def run_strategy():
    global universe
    global last_scan_candle
    global last_processed_candle

    print_header()

    universe = load_nifty500_universe()

    # Building this at startup can take time because NIFTY500 has many symbols.
    # The resulting values are kept in memory for the process.
    build_volume_baseline(universe)

    initialize_existing_position()

    print(
        "\nStrategy started. "
        "Completed 5-minute candles are used for all signal conditions."
    )

    while True:
        try:
            reset_daily_state_if_needed()

            current_dt = now_ist()

            # Forced square-off has priority.
            if is_after_square_off(current_dt):
                force_square_off_if_required()
                time.sleep(POLL_SECONDS)
                continue

            # Outside market entry window: no new entries.
            if current_dt.time() < ENTRY_START:
                time.sleep(POLL_SECONDS)
                continue

            # A 5-minute bucket changes every 5 minutes.
            current_bucket = current_dt.replace(
                minute=(current_dt.minute // 5) * 5,
                second=0,
                microsecond=0,
            )

            # Process once for each completed candle.
            if last_processed_candle == current_bucket:
                time.sleep(POLL_SECONDS)
                continue

            last_processed_candle = current_bucket

            print(
                "\n" + "#" * 100
            )
            print(
                f"PROCESSING COMPLETED 5-MINUTE CANDLE | "
                f"bucket={current_bucket}"
            )
            print("#" * 100)

            # If an open position exists, only fetch/manage its symbol.
            if position.active:
                process_symbol(
                    position.symbol,
                    current_dt,
                )
                continue

            # Scan the NIFTY500 on every new 5-minute cycle.
            candidates = scan_candidates()

            if not candidates:
                continue

            if ONE_POSITION_AT_A_TIME and position.active:
                continue

            # Evaluate current candidates first, then also evaluate any
            # symbol with a pending signal. This is important because a stock
            # may fall out of the scanner after its signal candle, while its
            # immediate next candle is still the valid entry candle.
            symbols_to_process = []
            seen_symbols = set()

            for candidate in candidates:
                symbol = candidate["symbol"]
                if symbol not in seen_symbols:
                    symbols_to_process.append(symbol)
                    seen_symbols.add(symbol)

            for symbol in list(pending_signals.keys()):
                if symbol not in seen_symbols:
                    symbols_to_process.append(symbol)
                    seen_symbols.add(symbol)

            # Evaluate candidates/pending symbols in order.
            for symbol in symbols_to_process:
                if position.active:
                    break

                process_symbol(
                    symbol,
                    current_dt,
                )

        except KeyboardInterrupt:
            print("\nKeyboard interrupt received.")

            try:
                if position.active:
                    print(
                        "WARNING: Position is still active. "
                        "No automatic square-off was performed on Ctrl+C."
                    )
            except Exception:
                pass

            break

        except Exception as exc:
            print(f"Main loop error: {exc}")
            time.sleep(POLL_SECONDS)


def main():
    run_strategy()


if __name__ == "__main__":
    main()
