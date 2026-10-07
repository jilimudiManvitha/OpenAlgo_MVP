"""TradeSmart's separate quote budget and shared general rolling windows.

Pins the two-budget contract introduced by upstream change b8e4cbdd9 (#1928).
The former tests predated that change and still required quotes to share history.
"""

import threading
import time
from collections import deque

import pytest

from broker.tradesmart.api import rate_limiter as rl


def reserve_general():
    return rl._reserve_slot(
        rl._lock,
        rl._reserved_call_times,
        rl.TRADESMART_MAX_PER_SECOND,
        rl.TRADESMART_MAX_PER_MINUTE,
    )


def reserve_quotes():
    return rl._reserve_slot(
        rl._quote_lock,
        rl._reserved_quote_times,
        rl.TRADESMART_QUOTE_MAX_PER_SECOND,
        rl.TRADESMART_QUOTE_MAX_PER_MINUTE,
    )


@pytest.fixture(autouse=True)
def _reset_gate():
    """Each test starts with a cold window, and leaves one behind."""
    rl._reserved_call_times = deque()
    rl._reserved_quote_times = deque()
    yield
    rl._reserved_call_times = deque()
    rl._reserved_quote_times = deque()


class TestCeilings:
    def test_per_second_pace_stays_under_the_broker_cap(self):
        """Broker rejects the 11th call in a second; we stop short of that."""
        assert rl.TRADESMART_MAX_PER_SECOND < 10

    def test_per_minute_pace_stays_under_the_broker_cap(self):
        """Broker rejects the 121st call in a minute; we stop short of that."""
        assert rl.TRADESMART_MAX_PER_MINUTE < 120

    def test_quotes_use_their_own_per_second_budget(self):
        assert rl.TRADESMART_QUOTE_MAX_PER_SECOND < 100
        assert rl.TRADESMART_QUOTE_MAX_PER_MINUTE is None
        for _ in range(rl.TRADESMART_QUOTE_MAX_PER_SECOND):
            assert reserve_quotes() < 0.1
        assert reserve_quotes() > 0.9
        assert reserve_general() < 0.1

    def test_general_calls_keep_the_per_minute_budget(self):
        for _ in range(rl.TRADESMART_MAX_PER_MINUTE):
            reserve_general()
        assert reserve_general() > 30.0


class TestPacing:
    def test_a_burst_up_to_the_cap_goes_out_immediately(self):
        """Burst-friendly: the gate does not space calls that fit the window."""
        started = time.monotonic()
        for _ in range(rl.TRADESMART_MAX_PER_SECOND):
            rl.apply_rate_limit("/TPSeries")
        assert time.monotonic() - started < 0.1

    def test_the_call_after_the_cap_waits_a_full_second(self):
        for _ in range(rl.TRADESMART_MAX_PER_SECOND):
            reserve_general()
        wait = reserve_general()
        assert 0.9 <= wait <= 1.05, f"expected ~1s wait, got {wait:.3f}s"

    def test_a_general_batch_is_paced_not_rejected(self):
        """A burst of general requests queues instead of exceeding its ceiling."""
        waits = [reserve_general() for _ in range(82)]
        expected = (82 - 1) // rl.TRADESMART_MAX_PER_SECOND
        assert expected - 0.5 <= max(waits) <= expected + 0.5

    def test_history_and_orders_share_one_budget(self):
        """No independent gates -- the broker counts per user, not per path."""
        for _ in range(rl.TRADESMART_MAX_PER_SECOND):
            rl.apply_rate_limit("/TPSeries")
        assert reserve_general() > 0.9


class TestWindowBookkeeping:
    def test_entries_older_than_a_minute_stop_constraining(self):
        """A stale window must not throttle a fresh burst."""
        rl._reserved_call_times = deque([time.time() - 120.0] * rl.TRADESMART_MAX_PER_MINUTE)
        assert reserve_general() == pytest.approx(0.0, abs=0.05)

    def test_reservations_stay_ordered(self):
        for _ in range(50):
            reserve_general()
        stamps = list(rl._reserved_call_times)
        assert stamps == sorted(stamps)


class TestConcurrency:
    def test_threads_space_out_rather_than_firing_together(self):
        """The slot is reserved under the lock, so waiters do not collide.

        If the timestamp were only written after sleeping, every thread would
        measure against the same stale window and fire at once.
        """
        stamps: list[float] = []
        stamps_lock = threading.Lock()

        def call():
            rl.apply_rate_limit("/TPSeries")
            with stamps_lock:
                stamps.append(time.monotonic())

        n = rl.TRADESMART_MAX_PER_SECOND * 2
        threads = [threading.Thread(target=call) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(stamps) == n
        stamps.sort()
        # The second half must land a second after the first, not alongside it.
        assert stamps[-1] - stamps[0] >= 0.9

    def test_sleep_happens_outside_the_lock(self):
        """A waiter must not block others from computing their slot.

        Holding the lock across sleep would serialise the threads into
        sequential sleeps; with the sleep outside, total wall time stays close
        to the span of the reserved slots rather than their sum.
        """
        started = time.monotonic()
        threads = [
            threading.Thread(target=rl.apply_rate_limit, args=("/TPSeries",))
            for _ in range(rl.TRADESMART_MAX_PER_SECOND * 2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert time.monotonic() - started < 2.0


class TestRateLimitDetection:
    def test_detects_the_per_minute_message(self):
        assert rl.is_rate_limit_error(
            {
                "stat": "Not_Ok",
                "emsg": "Invalid Input :  Order Recieved 121 in a current minute "
                "exceeds Limit 120 for user",
            }
        )

    def test_detects_the_per_second_message(self):
        assert rl.is_rate_limit_error(
            {
                "stat": "Not_Ok",
                "emsg": "Invalid Input :  Order Recieved 11 in a current second "
                "exceeds Limit 10 for user",
            }
        )

    def test_matches_a_changed_ceiling(self):
        """The number is not hardcoded, so a new limit is still recognised."""
        assert rl.is_rate_limit_error(
            {"stat": "Not_Ok", "emsg": "Order Recieved 101 exceeds Limit 100 for user"}
        )

    @pytest.mark.parametrize(
        "response",
        [
            {"stat": "Ok", "lp": "100"},
            {"stat": "Not_Ok", "emsg": "Session expired"},
            {"stat": "Not_Ok"},
            {"stat": "Not_Ok", "emsg": None},
            None,
            [],
            "not a dict",
        ],
    )
    def test_ignores_everything_else(self, response):
        assert rl.is_rate_limit_error(response) is False


class TestRetryDelay:
    def test_backs_off_exponentially(self):
        assert [rl.retry_delay(i) for i in range(3)] == [2.0, 4.0, 8.0]


def test_endpoint_dispatch_uses_the_expected_bucket(monkeypatch):
    asked = []

    def reserve(lock, reserved, per_second, per_minute):
        asked.append((reserved, per_second, per_minute))
        return 0

    monkeypatch.setattr(rl, "_reserve_slot", reserve)
    rl.apply_rate_limit("/GetQuotes")
    rl.apply_rate_limit("/TPSeries")
    rl.apply_rate_limit("/PlaceOrder")
    assert asked[0][0] is rl._reserved_quote_times
    assert asked[0][1:] == (90, None)
    assert all(call[0] is rl._reserved_call_times for call in asked[1:])
    assert all(call[1:] == (8, 110) for call in asked[1:])
