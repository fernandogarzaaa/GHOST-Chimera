"""Per-provider rate limiting (token bucket, stdlib only).

Cost control starts with call control: each provider gets a token bucket
configured via environment, e.g. ``GHOSTCHIMERA_RL_OPENAI_RPS=2`` and
``GHOSTCHIMERA_RL_OPENAI_BURST=5``. Unconfigured providers are unlimited,
so existing behavior never changes unless limits are set.

Usage::

    from ghostchimera.model_layer.rate_limit import get_limiter

    limiter = get_limiter("openai")
    limiter.acquire(timeout=5.0)  # blocks or raises RateLimitExceeded
"""

from __future__ import annotations

import math
import os
import threading
import time


class RateLimitExceeded(RuntimeError):
    """Raised when a rate-limit acquire times out."""


def _env_float(name: str, default: float) -> float:
    """Env override or *default*; missing/non-numeric/non-finite/non-positive → default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value) or value <= 0.0:
        return default
    return value


class RateLimiter:
    """Thread-safe token-bucket limiter with an injectable clock (for tests)."""

    def __init__(
        self,
        rate_per_second: float = 0.0,
        burst: int = 0,
        *,
        clock: callable = time.monotonic,  # type: ignore[valid-type]
    ) -> None:
        self.rate_per_second = max(0.0, rate_per_second)
        self.burst = max(1, int(burst)) if rate_per_second > 0 else 0
        self._clock = clock
        self._tokens = float(self.burst)
        self._updated = self._clock()
        self._lock = threading.Lock()

    @property
    def unlimited(self) -> bool:
        return self.rate_per_second <= 0.0

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._updated)
        self._tokens = min(float(self.burst), self._tokens + elapsed * self.rate_per_second)
        self._updated = now

    def try_acquire(self, tokens: int = 1) -> bool:
        """Take *tokens* without blocking; False when the bucket is empty.

        Unlimited limiters always succeed.
        """
        if self.unlimited:
            return True
        if tokens <= 0:
            return True
        with self._lock:
            self._refill(self._clock())
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def acquire(self, tokens: int = 1, *, timeout: float = 30.0) -> None:
        """Block until *tokens* are available or *timeout* elapses."""
        if self.unlimited or tokens <= 0:
            return
        deadline = self._clock() + max(0.0, timeout)
        while True:
            with self._lock:
                self._refill(self._clock())
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait = deficit / self.rate_per_second if self.rate_per_second > 0 else float("inf")
            remaining = deadline - self._clock()
            if remaining <= 0 or wait > remaining:
                raise RateLimitExceeded(f"Rate limit exceeded (waited {timeout:.1f}s)")
            time.sleep(min(wait, remaining, 0.05))

    def to_dict(self) -> dict[str, float | bool]:
        return {
            "rate_per_second": self.rate_per_second,
            "burst": self.burst,
            "unlimited": self.unlimited,
        }


def limiter_from_env(provider_name: str, *, default_rps: float = 0.0, default_burst: int = 0) -> RateLimiter:
    """Build a limiter from ``GHOSTCHIMERA_RL_<NAME>_RPS/BURST`` env vars."""
    key = provider_name.upper().replace("-", "_")
    rps = _env_float(f"GHOSTCHIMERA_RL_{key}_RPS", _env_float("GHOSTCHIMERA_RL_DEFAULT_RPS", default_rps))
    burst_default = default_burst or max(1, int(rps))
    burst_raw = os.environ.get(f"GHOSTCHIMERA_RL_{key}_BURST", os.environ.get("GHOSTCHIMERA_RL_DEFAULT_BURST", ""))
    try:
        burst = int(burst_raw) if str(burst_raw).strip() else burst_default
        if burst <= 0:
            burst = burst_default
    except (TypeError, ValueError, OverflowError):
        burst = burst_default
    return RateLimiter(rps, burst)


_limiters: dict[str, RateLimiter] = {}
_limiters_lock = threading.Lock()


def get_limiter(provider_name: str) -> RateLimiter:
    """Process-wide limiter per provider, configured once from env."""
    with _limiters_lock:
        limiter = _limiters.get(provider_name)
        if limiter is None:
            limiter = limiter_from_env(provider_name)
            _limiters[provider_name] = limiter
        return limiter


def reset_limiters() -> None:
    """Drop cached limiters (tests; picks up env changes)."""
    with _limiters_lock:
        _limiters.clear()


__all__ = ["RateLimitExceeded", "RateLimiter", "get_limiter", "limiter_from_env", "reset_limiters"]
