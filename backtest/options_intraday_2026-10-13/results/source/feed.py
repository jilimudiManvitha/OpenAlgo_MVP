"""Incremental subscriptions: retain acknowledgements and retry without exiting."""

from datetime import date

from .selection import DataUnavailable, select_expiry


def required_contracts(contracts, expiries, profile, day, held_legs, active_expiry=None):
    """Use the requested and active cycle's full chains; keep the expiry calendar.

    A current-week strategy must not wait for unrelated next-week acknowledgements.
    No strike/premium pruning: the requested selection rules remain unchanged.
    """
    held = {leg["symbol"] for leg in held_legs}
    required = {date.fromisoformat(c["expiry"]) for c in contracts if c["symbol"] in held}
    if active_expiry:
        required.add(date.fromisoformat(active_expiry))
    try:
        required.add(select_expiry(day, expiries, profile.expiry))
    except DataUnavailable:
        # A missing new-cycle catalogue must not prevent managing existing risk.
        if not required:
            raise
    return [c for c in contracts if date.fromisoformat(c["expiry"]) in required]


def connection_delay(profile_index, has_positions=False, retry=False):
    """Spread the twelve independent handshakes without delaying held risk at start."""
    if retry:
        return 5 + profile_index * 0.5
    return 0 if has_positions else profile_index


class QuoteSubscriptions:
    def __init__(self, specs):
        self.specs = {(s["exchange"], s["symbol"]): s for s in specs}
        self.socket = None
        self.accepted = set()
        self.pending = list(self.specs)
        self.next_attempt = 0.0
        self.failures = 0
        self.error = "Waiting for quote connection"

    @property
    def ready(self):
        return self.socket is not None and not self.pending

    def reset(self):
        self.socket = None
        self.accepted.clear()
        self.pending = list(self.specs)
        self.next_attempt = 0.0
        self.failures = 0
        self.error = "Waiting for quote connection"

    def step(self, client, clock):
        """At most one batch per call, leaving the runner free to manage held risk."""
        if not client.connected or not client.authenticated:
            self.reset()
            return
        if client.ws is not self.socket:
            self.reset()
            self.socket = client.ws
        if not self.pending or clock < self.next_attempt:
            return
        batch = self.pending[:50]
        try:
            reply = client.subscribe([self.specs[key] for key in batch], "Quote")
        except Exception as exc:
            reply = {"status": "error", "message": type(exc).__name__}
        if client.ws is not self.socket or not client.connected:
            self.reset()
            return
        rows = reply.get("subscriptions") or []
        accepted = {
            (r.get("exchange"), r.get("symbol")) for r in rows if r.get("status") == "success"
        }.intersection(batch)
        # Legacy clients return only a whole-batch success acknowledgement.
        if not rows and reply.get("status") == "success":
            accepted = set(batch)
        self.accepted.update(accepted)
        missing = [key for key in batch if key not in accepted]
        self.pending = self.pending[len(batch) :] + missing
        if missing:
            self.failures = min(self.failures + 1, 5)
            self.next_attempt = clock + min(30, 2**self.failures)
            details = [
                f"{r.get('exchange')}:{r.get('symbol')}: {str(r.get('message', 'rejected'))[:160]}"
                for r in rows
                if r.get("status") != "success"
            ][:3]
            self.error = (
                f"Option subscriptions pending {len(self.pending)}/{len(self.specs)}; "
                + ("; ".join(details) or str(reply.get("message", "Missing acknowledgement"))[:240])
                + "; retrying"
            )
        else:
            self.failures = 0
            self.next_attempt = clock + 0.25
            self.error = (
                "" if self.ready else f"Subscribing: {len(self.accepted)}/{len(self.specs)}"
            )
