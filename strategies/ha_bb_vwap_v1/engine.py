"""Event-driven strategy logic; emits intents and requires explicit fill acknowledgement.

There are no broker clients, data downloads, backtests, background threads or
automatic orders. Use one instance per symbol/timeframe/version. A future adapter
must acknowledge/reject each intent before the next market update; this reference
contract deliberately does not pretend that a requested order is already filled.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from math import floor, isfinite

from .models import IST, Config, OrderIntent, Position, Snapshot


def no_adverse_wick(snapshot: Snapshot, direction: int) -> bool:
    tolerance = max(abs(snapshot.ha_open), 1.0) * 1e-10
    if direction == 1:
        return snapshot.ha_low >= snapshot.ha_open - tolerance
    return snapshot.ha_high <= snapshot.ha_open + tolerance


def signal_qualifies(snapshot: Snapshot, config: Config) -> bool:
    values = snapshot.indicators
    band = values.bb_upper if config.direction == 1 else values.bb_lower
    extreme = snapshot.ha_high if config.direction == 1 else snapshot.ha_low
    return (
        snapshot.candle.complete
        and all(isfinite(v) for v in (band, values.vwap))
        and no_adverse_wick(snapshot, config.direction)
        and config.direction * (extreme - band) > 0
        and config.direction * (extreme - values.vwap) > 0
    )


def indicator_exit(rule: str, current: Snapshot, previous: Snapshot | None, direction: int) -> bool:
    if rule == "none":
        return False
    indicator, mode = rule.rsplit("_", 1)
    if mode == "full" and not current.candle.complete:
        return False
    values = current.indicators
    if indicator == "rsi":
        # RSI is an oscillator, not a price: compare RSI itself to 60/40.
        return isfinite(values.rsi) and (values.rsi < 60 if direction == 1 else values.rsi > 40)
    if indicator == "macd":
        if previous is None:
            return False
        before = previous.indicators.macd - previous.indicators.macd_signal
        now = values.macd - values.macd_signal
        return all(isfinite(v) for v in (before, now)) and direction * before >= 0 > direction * now
    level = getattr(values, indicator)
    if not isfinite(level):
        return False
    if indicator == "supertrend":
        if values.supertrend_direction != direction:  # +1 red for buy, -1 green for sell
            return False
        if mode == "tick":
            return True
    if mode == "full":
        # Entire HA range must be on the adverse side, not just its close.
        price = current.ha_high if direction == 1 else current.ha_low
    else:
        price = current.candle.close  # last real traded price observed so far
    return direction * (price - level) < 0


@dataclass
class Pending:
    intent: OrderIntent
    initial_stop: float | None = None


class Strategy:
    def __init__(self, symbol: str, is_fo: bool, config: Config = Config()):
        if not symbol or type(is_fo) is not bool:
            raise ValueError("Supply a symbol and explicit F&O-stock membership")
        self.symbol = symbol
        self.is_fo = is_fo
        self.config = config
        self.position: Position | None = None
        self.pending: Pending | None = None
        self._signal: Snapshot | None = None
        self._previous: Snapshot | None = None
        self._closed: Snapshot | None = None
        self._used_signal = None
        self._counter = 0
        self._latest_time = None
        self._position_day = None

    @property
    def cutoff(self):
        return time(15, 5) if self.is_fo else time(15, 20)

    def _intent(self, side, quantity, price, reason, observed_at, initial_stop=None):
        self._counter += 1
        intent = OrderIntent(self._counter, side, quantity, price, reason, observed_at)
        self.pending = Pending(intent, initial_stop)
        return intent

    def on_snapshot(self, current: Snapshot) -> list[OrderIntent]:
        """Evaluate a forming or completed snapshot using information available now.

        A pending order must be resolved explicitly before the next update. This
        is a synchronous research interface, not an asynchronous broker adapter.
        """
        if self.pending:
            raise RuntimeError("Acknowledge the completed fill or reject the pending intent first")
        bar = current.candle
        bar.validate(self.config.timeframe_minutes)
        if self._latest_time and bar.observed_at < self._latest_time:
            raise ValueError("Market update predates the latest clock/market event")
        previous = self._previous
        if previous:
            old = previous.candle
            if bar.observed_at < old.observed_at or bar.start < old.start:
                raise ValueError("Market updates must be chronological")
            if old.complete and bar.start == old.start:
                if current == previous:
                    return []
                raise ValueError("Cannot revise an already completed candle")
            if bar.start == old.start and (
                bar.open != old.open
                or bar.high < old.high
                or bar.low > old.low
                or bar.volume < old.volume
            ):
                raise ValueError("Forming candles must contain cumulative, non-retracting OHLCV")
        local = bar.observed_at.astimezone(IST)
        same_day = self._signal and self._signal.candle.start.astimezone(IST).date() == local.date()
        if not same_day:
            self._signal = None
        results = []
        position_at_start = self.position is not None
        if self.position:
            order = self._exit(current)
            if order:
                results.append(order)
        elif time(9, 15) <= local.time() < self.cutoff:
            order = self._entry(current)
            if order:
                results.append(order)
        if bar.complete:
            if not position_at_start and self.pending is None and local.time() < self.cutoff:
                self._signal = current if signal_qualifies(current, self.config) else None
            self._closed = current
        self._previous = current
        self._latest_time = bar.observed_at
        return results

    def _entry(self, current):
        signal = self._signal
        if signal is None or signal.candle.start == self._used_signal:
            return None
        expected = signal.candle.start + timedelta(minutes=self.config.timeframe_minutes)
        if current.candle.start != expected:
            if current.candle.start > expected:
                self._signal = None
            return None
        # Final-only bars cannot prove that the wick/indicator checks passed at
        # the earlier breakout. Entry requires an actual forming update.
        if current.candle.complete or not no_adverse_wick(current, self.config.direction):
            return None
        d = self.config.direction
        values = current.indicators
        band = values.bb_upper if d == 1 else values.bb_lower
        threshold = signal.ha_high if d == 1 else signal.ha_low
        price = current.candle.close
        if not all(isfinite(v) for v in (band, values.vwap)):
            return None
        if not all(d * (price - level) > 0 for level in (threshold, band, values.vwap)):
            return None
        if d == 1:
            stop = signal.ha_low - self.config.sl_buffer
        else:
            anchor = signal.ha_high if self.config.short_stop_anchor == "high" else signal.ha_low
            stop = anchor + self.config.sl_buffer
        risk = d * (price - stop)
        if stop <= 0 or risk <= 0:
            return None
        if price + d * self.config.reward_risk * risk <= 0:
            return None
        quantity = floor(self.config.capital / price)
        if quantity < 1:
            return None
        self._used_signal = signal.candle.start
        return self._intent(
            self.config.side, quantity, price, "entry", current.candle.observed_at, stop
        )

    def _exit(self, current):
        p = self.position
        cfg = self.config
        d = cfg.direction
        price = current.candle.close
        now = current.candle.observed_at
        reason, quantity = None, p.quantity
        if now.astimezone(IST).time() >= self.cutoff or (
            self._position_day and now.astimezone(IST).date() > self._position_day
        ):
            reason = "square_off"
        elif d * (price - p.stop) <= 0:
            reason = "stop_loss"
        else:
            # Move the stop only in the favourable direction; original risk
            # remains fixed after entry, including after partial exits.
            p.best_price = max(p.best_price, price) if d == 1 else min(p.best_price, price)
            favourable = d * (p.best_price - p.entry)
            if cfg.trail_fraction and cfg.reward_risk >= 2 and favourable >= p.risk:
                base = (
                    cfg.reward_risk * p.risk if cfg.trail_basis == "target_distance" else favourable
                )
                candidate = p.best_price - d * cfg.trail_fraction * base
                candidate = max(p.entry, candidate) if d == 1 else min(p.entry, candidate)
                p.stop = max(p.stop, candidate) if d == 1 else min(p.stop, candidate)
            full_previous = self._closed
            tick_previous = self._previous
            previous = full_previous if cfg.stop_rule.endswith("_full") else tick_previous
            if d * (price - p.stop) <= 0:
                reason = "trailing_stop"
            elif indicator_exit(cfg.stop_rule, current, previous, d):
                reason = "indicator_stop"
            elif d * (price - p.target) >= 0:
                reason = "fixed_target"
            elif (
                indicator_exit(
                    cfg.target_rule,
                    current,
                    full_previous if cfg.target_rule.endswith("_full") else tick_previous,
                    d,
                )
                and d * (price - p.entry) > 0
            ):
                reason = "indicator_target"
            elif cfg.partial != "none":
                first, last, fraction = (
                    (1.0, 2.0, 0.5) if cfg.partial == "half_1r_2r" else (1.5, 2.5, 0.25)
                )
                profit_r = d * (price - p.entry) / p.risk
                if profit_r >= last:
                    reason = "partial_final"
                elif not p.partial_done and profit_r >= first:
                    quantity = min(floor(p.original_quantity * fraction), p.quantity - 1)
                    if quantity > 0:
                        reason = "partial_first"
        if reason:
            return self._intent("sell" if d == 1 else "buy", quantity, price, reason, now)
        return None

    def on_clock(self, now: datetime, last_price: float) -> list[OrderIntent]:
        """A future adapter must call this at cutoff, even without a fresh tick.

        last_price is only a reference; execution must acknowledge its actual
        price. No internal timer or background process is started by this code.
        """
        if now.tzinfo is None or not isfinite(last_price) or last_price <= 0:
            raise ValueError("Supply aware time and a positive reference price")
        if self.pending:
            raise RuntimeError("Resolve/cancel pending orders before square-off")
        if self._latest_time and now < self._latest_time:
            raise ValueError("Clock cannot move backwards")
        self._latest_time = now
        if now.astimezone(IST).time() >= self.cutoff or (
            self._position_day and now.astimezone(IST).date() > self._position_day
        ):
            self._signal = None
            if self.position:
                return [
                    self._intent(
                        "sell" if self.config.direction == 1 else "buy",
                        self.position.quantity,
                        last_price,
                        "square_off",
                        now,
                    )
                ]
        return []

    def acknowledge_fill(self, order_id: int, price: float, quantity: int):
        """Accept one fully completed order at its actual average fill price.

        Partial broker fills must be reconciled by a future adapter; they cannot
        be silently assumed complete. No fill is synthesized by this package.
        """
        pending = self.pending
        if pending is None or pending.intent.order_id != order_id:
            raise ValueError("Unknown pending order")
        if quantity != pending.intent.quantity or type(quantity) is not int:
            raise ValueError("Acknowledgement must match the complete requested quantity")
        if not isfinite(price) or price <= 0:
            raise ValueError("Fill price must be positive and finite")
        if pending.intent.reason == "entry":
            d = self.config.direction
            risk = d * (price - pending.initial_stop)
            if (
                risk <= 0
                or price * quantity > self.config.capital + 1e-8
                or (price + d * self.config.reward_risk * risk <= 0)
            ):
                raise ValueError(
                    "Fill violates risk/capital contract; execution adapter must reconcile"
                )
            self.position = Position(
                quantity,
                quantity,
                price,
                pending.initial_stop,
                pending.initial_stop,
                risk,
                price + d * self.config.reward_risk * risk,
                price,
            )
            self._position_day = pending.intent.observed_at.astimezone(IST).date()
        else:
            if self.position is None or quantity > self.position.quantity:
                raise ValueError("Exit fill exceeds the open position")
            self.position.quantity -= quantity
            if pending.intent.reason == "partial_first":
                self.position.partial_done = True
            if self.position.quantity == 0:
                self.position = None
                self._position_day = None
        self.pending = None

    def reject_order(self, order_id: int):
        """Reject/cancel an unfilled intent; rejected entries consume their signal."""
        if self.pending is None or self.pending.intent.order_id != order_id:
            raise ValueError("Unknown pending order")
        self.pending = None
