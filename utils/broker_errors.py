"""Typed expected broker failures shared by adapters and service boundaries."""

import math


class BrokerDataRateLimitError(RuntimeError):
    """A market-data request was throttled; retain the broker's retry delay."""

    def __init__(self, delay, message="Market-data rate limit active"):
        self.retry_after = max(1, math.ceil(delay))
        super().__init__(message)
