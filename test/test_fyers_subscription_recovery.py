"""No broker calls: exercise token failures through the real subscription worker."""

from threading import Event, Thread, Timer, active_count
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from broker.fyers.streaming import fyers_adapter as inner
from broker.fyers.streaming import fyers_token_converter as tokens
from broker.fyers.streaming import fyers_websocket_adapter as outer


def response(status=200, payload=None, content=None, headers=None):
    kwargs = {"content": content} if content is not None else {"json": payload}
    return httpx.Response(
        status,
        request=httpx.Request("POST", "https://fixture/symbol-token"),
        headers=headers,
        **kwargs,
    )


def valid_response(symbols):
    return response(
        payload={
            "s": "ok",
            "validSymbol": {s: f"1010000000{i + 1}" for i, s in enumerate(symbols)},
            "invalidSymbol": [],
        }
    )


@pytest.fixture
def http(monkeypatch):
    client = Mock()
    client.post.side_effect = lambda **kw: valid_response(kw["json"]["symbols"])
    limiter = Mock()
    monkeypatch.setattr(tokens, "get_httpx_client", lambda: client)
    monkeypatch.setattr(tokens, "apply_rate_limit", limiter)
    return client, limiter


@pytest.mark.parametrize(
    "reply,retryable,delay",
    [
        (response(content=b""), True, 5),
        (response(502, content=b"<html>bad gateway</html>"), True, 5),
        (response(429, content=b"", headers={"Retry-After": "180"}), True, 180),
        (response(429, headers={"X-Retry-After-Ms": "90000"}), True, 90),
        (response(401, content=b"unauthorized"), False, 5),
        (response(403, content=b"forbidden"), False, 5),
        (response(payload={"s": "error", "code": -429}), True, 60),
        (response(payload={"s": "error", "code": -16}), False, 5),
        (response(payload=[]), True, 5),
        (response(payload={"s": "ok", "validSymbol": {}}), True, 5),
    ],
)
def test_service_failures_are_not_invalid_symbols(http, reply, retryable, delay):
    client, limiter = http
    client.post.side_effect = None
    client.post.return_value = reply
    with pytest.raises(tokens.TokenConversionError) as failure:
        tokens.FyersTokenConverter("fixture").convert_symbols_to_hsm(["NSE:TCS-EQ"])
    assert failure.value.retryable is retryable
    assert failure.value.retry_after == delay
    assert "fixture" not in str(failure.value)
    client.post.assert_called_once()
    limiter.assert_called_once()


def test_transport_failure_is_retryable(http):
    http[0].post.side_effect = httpx.ReadTimeout("fixture secret must not be logged")
    with pytest.raises(tokens.TokenConversionError, match="connection failed") as failure:
        tokens.FyersTokenConverter("fixture").convert_symbols_to_hsm(["NSE:TCS-EQ"])
    assert failure.value.retryable
    assert "secret" not in str(failure.value)


def test_large_conversion_is_bounded_and_each_request_is_paced(http):
    symbols = [f"NSE:S{i}-EQ" for i in range(205)]
    converted, _, invalid = tokens.FyersTokenConverter("fixture").convert_symbols_to_hsm(symbols)
    assert len(converted) == 205 and invalid == []
    assert [len(call.kwargs["json"]["symbols"]) for call in http[0].post.call_args_list] == [
        100,
        100,
        5,
    ]
    assert http[1].call_count == 3


def test_only_explicit_rejections_are_invalid(http):
    http[0].post.side_effect = None
    http[0].post.return_value = response(
        payload={
            "s": "ok",
            "validSymbol": {"NSE:TCS-EQ": "1010000000115"},
            "invalidSymbol": ["NSE:BAD-EQ"],
        }
    )
    converted, mapping, invalid = tokens.FyersTokenConverter("fixture").convert_symbols_to_hsm(
        ["NSE:TCS-EQ", "NSE:BAD-EQ"]
    )
    assert converted == ["sf|nse_cm|115"]
    assert mapping == {"sf|nse_cm|115": "NSE:TCS-EQ"}
    assert invalid == ["NSE:BAD-EQ"]


@pytest.fixture
def worker(monkeypatch, http):
    clock = [1000.0]
    timers = []

    class Timer:
        def __init__(self, delay, callback, args=()):
            self.delay, self.callback, self.args = delay, callback, args
            self.cancelled = False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

        def fire(self):
            clock[0] += self.delay
            if not self.cancelled:
                self.callback(*self.args)

    def base_init(self):
        self.subscriptions = {}
        self.socket = self.context = None
        self.connected = False

    def broker_symbol(symbol, exchange):
        return f"{exchange}:{symbol}-EQ"

    monkeypatch.setattr(outer.BaseBrokerWebSocketAdapter, "__init__", base_init)
    monkeypatch.setattr(outer.BaseBrokerWebSocketAdapter, "cleanup_zmq", lambda self: None)
    monkeypatch.setattr(outer.threading, "Timer", Timer)
    monkeypatch.setattr(outer.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(tokens, "get_br_symbol", broker_symbol)
    monkeypatch.setattr(inner, "get_br_symbol", broker_symbol)
    adapter = outer.FyersWebSocketAdapter()
    adapter.connected = adapter.running = True
    adapter.fyers_adapter = inner.FyersAdapter("fixture", "fixture")
    adapter.fyers_adapter.connected = True
    adapter.fyers_adapter.ws_client = Mock()
    adapter.logger = Mock()
    adapter.fyers_adapter.logger = Mock()
    state = SimpleNamespace(adapter=adapter, http=http[0], timers=timers, clock=clock)
    yield state
    adapter.disconnect()


def test_empty_response_retries_then_dispatches_real_subscription(worker):
    w = worker
    w.http.post.side_effect = [response(content=b""), valid_response(["NSE:TCS-EQ"])]
    assert w.adapter.subscribe("TCS", "NSE")["status"] == "success"
    w.timers[-1].fire()
    assert w.adapter.get_subscriptions()["stream_status_counts"] == {"retrying": 1}
    assert w.adapter.fyers_adapter.active_subscriptions == {}
    w.adapter.fyers_adapter.ws_client.subscribe_symbols.assert_not_called()
    assert w.timers[-1].delay == 5
    w.timers[-1].fire()
    w.adapter.fyers_adapter.ws_client.subscribe_symbols.assert_called_once()
    assert w.adapter.get_subscriptions()["stream_status_counts"] == {"dispatched": 1}
    assert w.adapter._hsm_batch_queue == {}
    assert w.adapter._hsm_batch_timer is None


def test_rate_limit_cooldown_also_delays_new_symbols(worker):
    w = worker
    w.http.post.side_effect = [
        response(429, headers={"Retry-After": "180"}),
        valid_response(["NSE:TCS-EQ", "NSE:INFY-EQ"]),
    ]
    w.adapter.subscribe("TCS", "NSE")
    w.timers[-1].fire()
    assert w.timers[-1].delay == pytest.approx(180)
    w.adapter.subscribe("INFY", "NSE")
    assert len(w.timers) == 2
    w.timers[-1].fire()
    assert w.http.post.call_count == 2
    assert w.adapter.get_subscriptions()["stream_status_counts"] == {"dispatched": 2}


def test_exhaustion_is_visible_and_stops_retrying(worker):
    w = worker
    w.http.post.side_effect = lambda **kw: response(content=b"")
    w.adapter.subscribe("TCS", "NSE")
    for _ in range(3):
        w.timers[-1].fire()
    assert w.http.post.call_count == 3
    assert w.adapter._hsm_batch_queue == {}
    assert w.adapter._hsm_batch_timer is None
    assert w.adapter.get_subscriptions()["stream_status_counts"] == {"failed": 1}


def test_auth_failure_does_not_retry_or_claim_active_subscription(worker):
    w = worker
    w.http.post.side_effect = [response(401, content=b"")]
    w.adapter.subscribe("TCS", "NSE")
    w.timers[-1].fire()
    assert w.adapter._hsm_batch_timer is None
    assert w.adapter.fyers_adapter.active_subscriptions == {}
    assert w.adapter.get_subscriptions()["stream_status_counts"] == {"failed": 1}


def test_partial_invalid_response_keeps_valid_symbol_and_marks_rejection(worker):
    w = worker
    w.http.post.side_effect = [
        response(
            payload={
                "s": "ok",
                "validSymbol": {"NSE:TCS-EQ": "1010000000115"},
                "invalidSymbol": ["NSE:BAD-EQ"],
            }
        )
    ]
    w.adapter.subscribe("TCS", "NSE")
    w.adapter.subscribe("BAD", "NSE")
    w.timers[-1].fire()
    assert w.adapter.get_subscriptions()["stream_status_counts"] == {"dispatched": 1, "rejected": 1}
    assert set(w.adapter.fyers_adapter.active_subscriptions) == {"NSE:TCS"}
    assert w.adapter._hsm_batch_timer is None


@pytest.mark.parametrize(
    "action", ["unsubscribe", "disconnect", "cleanup_all_resources", "force_cleanup"]
)
def test_stopping_cancels_pending_retry(worker, action):
    w = worker
    w.http.post.side_effect = lambda **kw: response(content=b"")
    w.adapter.subscribe("TCS", "NSE")
    w.timers[-1].fire()
    timer = w.timers[-1]
    if action == "unsubscribe":
        w.adapter.unsubscribe("TCS", "NSE")
    else:
        getattr(w.adapter, action)()
    assert timer.cancelled
    # Also simulate a callback that was already awakened before cancellation.
    timer.callback(*timer.args)
    assert w.http.post.call_count == 1
    assert w.adapter._hsm_batch_queue == {}
    assert w.adapter._hsm_callback_registry == {}


def test_unsubscribed_symbol_is_removed_from_retry_without_dropping_sibling(worker):
    w = worker
    w.http.post.side_effect = [response(content=b""), valid_response(["NSE:INFY-EQ"])]
    w.adapter.subscribe("TCS", "NSE")
    w.adapter.subscribe("INFY", "NSE")
    w.timers[-1].fire()
    w.adapter.unsubscribe("TCS", "NSE")
    w.timers[-1].fire()
    assert w.http.post.call_args.kwargs["json"]["symbols"] == ["NSE:INFY-EQ"]
    assert w.adapter.get_subscriptions()["stream_status_counts"] == {"dispatched": 1}


def test_large_queued_subscription_is_split_without_overlapping_workers(worker):
    w = worker
    for i in range(250):
        w.adapter.subscribe(f"S{i}", "NSE")
    assert len(w.timers) == 1
    for _ in range(3):
        w.timers[-1].fire()
    assert [len(c.kwargs["json"]["symbols"]) for c in w.http.post.call_args_list] == [100, 100, 50]
    assert w.adapter.get_subscriptions()["stream_status_counts"] == {"dispatched": 250}
    assert w.adapter._hsm_batch_timer is None


def test_disconnect_during_request_cannot_requeue_or_resurrect_subscription(worker):
    w = worker
    entered, release, cancelled = Event(), Event(), Event()

    def blocked_request(**kwargs):
        entered.set()
        assert release.wait(2)
        return response(content=b"")

    w.http.post.side_effect = blocked_request
    w.adapter.subscribe("TCS", "NSE")
    original_cancel = w.adapter._cancel_hsm_batches

    def cancel():
        original_cancel()
        cancelled.set()

    w.adapter._cancel_hsm_batches = cancel
    dispatch = Thread(target=w.timers[-1].fire)
    stopper = Thread(target=w.adapter.disconnect)
    dispatch.start()
    try:
        assert entered.wait(2)
        stopper.start()
        assert cancelled.wait(2)
    finally:
        release.set()
        dispatch.join(2)
        if stopper.ident:
            stopper.join(2)
    assert not dispatch.is_alive() and not stopper.is_alive()
    assert w.http.post.call_count == 1
    assert w.adapter._hsm_batch_timer is None
    assert w.adapter._hsm_batch_queue == {}
    assert w.adapter._hsm_callback_registry == {}
    assert w.adapter.subscriptions == {}


def test_repeated_failure_cleanup_keeps_retry_state_bounded(worker):
    w = worker
    w.http.post.side_effect = lambda **kw: response(content=b"")
    adapter = w.adapter
    for _ in range(100):
        adapter.connected = adapter.running = True
        adapter.fyers_adapter = inner.FyersAdapter("fixture", "fixture")
        adapter.fyers_adapter.logger = Mock()
        adapter.fyers_adapter.connected = True
        adapter.fyers_adapter.ws_client = Mock()
        adapter.subscribe("TCS", "NSE")
        for _ in range(3):
            w.timers[-1].fire()
        adapter.disconnect()
        assert adapter._hsm_batch_queue == {}
        assert adapter._hsm_callback_registry == {}
        assert adapter._hsm_batch_timer is None
        assert adapter.subscriptions == {}
        assert adapter.active_callbacks == {}
        assert not adapter._hsm_flush_running


def test_real_retry_timers_release_threads_and_descriptors(worker, monkeypatch):
    import psutil

    w = worker
    adapter = w.adapter
    created = []
    attempted = Event()

    def timer_factory(*args, **kwargs):
        timer = Timer(*args, **kwargs)
        created.append(timer)
        return timer

    def failure(**kwargs):
        attempted.set()
        return response(content=b"")

    monkeypatch.setattr(outer.threading, "Timer", timer_factory)
    adapter.HSM_BATCH_DELAY_SEC = 0.001
    w.http.post.side_effect = failure
    process = psutil.Process()
    fd_count = process.num_fds if hasattr(process, "num_fds") else process.num_handles
    before = (active_count(), fd_count())
    for _ in range(100):
        attempted.clear()
        adapter.connected = adapter.running = True
        adapter.fyers_adapter = inner.FyersAdapter("fixture", "fixture")
        adapter.fyers_adapter.logger = Mock()
        adapter.fyers_adapter.connected = True
        adapter.fyers_adapter.ws_client = Mock()
        adapter.subscribe("TCS", "NSE")
        try:
            assert attempted.wait(2)
            assert adapter.get_subscriptions()["stream_status_counts"] == {"retrying": 1}
        finally:
            adapter.disconnect()
            for timer in created:
                timer.join(2)
                assert not timer.is_alive()
            created.clear()
        assert adapter._hsm_batch_queue == {}
        assert adapter._hsm_batch_timer is None
    assert (active_count(), fd_count()) == before
