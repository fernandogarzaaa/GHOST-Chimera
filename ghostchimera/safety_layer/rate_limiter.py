"""Token-bucket rate limiter for Ghost Chimera safety layer."""

from __future__ import annotations

import threading
import time
from typing import Dict


class RateLimiter:
    """Token-bucket rate limiter.

    Parameters
    ----------
    rate : float
        Refill rate in tokens (requests) per second.
    burst : int
        Maximum bucket capacity (max concurrent requests).
    """

    def __init__(self, rate: float = 10.0, burst: int = 20) -> None:
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """Return True if a request is allowed under this limiter."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


class RateLimiterStore:
    """Manage per-name rate limiters."""

    def __init__(self, default_rate: float = 10.0, default_burst: int = 20) -> None:
        self.default_rate = default_rate
        self.default_burst = default_burst
        self._limiters: Dict[str, RateLimiter] = {}
        self._lock = threading.Lock()

    def limiter(self, name: str) -> RateLimiter:
        """Return (creating if necessary) a :class:`RateLimiter` for *name*."""
        with self._lock:
            if name not in self._limiters:
                self._limiters[name] = RateLimiter(self.default_rate, self.default_burst)
            return self._limiters[name]

    def allow(self, name: str) -> bool:
        """Delegate *allow* to the named bucket."""
        return self.limiter(name).allow()
