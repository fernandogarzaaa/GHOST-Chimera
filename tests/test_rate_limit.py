"""Tests for per-provider rate limiting (fake clock, no sleeping)."""

from __future__ import annotations

import unittest
from unittest import mock

from ghostchimera.model_layer.rate_limit import (
    RateLimiter,
    RateLimitExceeded,
    get_limiter,
    limiter_from_env,
    reset_limiters,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RateLimiterTests(unittest.TestCase):
    def test_unlimited_always_succeeds(self) -> None:
        limiter = RateLimiter(0.0, 0)
        self.assertTrue(limiter.unlimited)
        for _ in range(100):
            self.assertTrue(limiter.try_acquire())

    def test_bucket_caps_at_burst(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(10.0, 3, clock=clock)
        self.assertTrue(limiter.try_acquire())
        self.assertTrue(limiter.try_acquire())
        self.assertTrue(limiter.try_acquire())
        self.assertFalse(limiter.try_acquire())

    def test_refill_over_time(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(2.0, 2, clock=clock)
        self.assertTrue(limiter.try_acquire())
        self.assertTrue(limiter.try_acquire())
        self.assertFalse(limiter.try_acquire())
        clock.advance(0.6)  # 1.2 tokens refill
        self.assertTrue(limiter.try_acquire())
        self.assertFalse(limiter.try_acquire())

    def test_acquire_timeout_raises(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(1.0, 1, clock=clock)
        limiter.try_acquire()
        # Refill needs 1.0s; the 0.5s budget expires first.
        with (
            mock.patch("ghostchimera.model_layer.rate_limit.time.sleep", lambda s: clock.advance(s)),
            self.assertRaises(RateLimitExceeded),
        ):
            limiter.acquire(timeout=0.5)

    def test_acquire_succeeds_after_refill(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(10.0, 1, clock=clock)
        limiter.try_acquire()
        with mock.patch("ghostchimera.model_layer.rate_limit.time.sleep", lambda s: clock.advance(s)):
            limiter.acquire(timeout=5.0)  # refills 0.1s in, succeeds


class LimiterEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_limiters()

    def tearDown(self) -> None:
        reset_limiters()

    def test_default_is_unlimited(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(get_limiter("openai").unlimited)

    def test_env_configures_limiter(self) -> None:
        env = {"GHOSTCHIMERA_RL_OPENAI_RPS": "4", "GHOSTCHIMERA_RL_OPENAI_BURST": "2"}
        with mock.patch.dict("os.environ", env, clear=True):
            limiter = limiter_from_env("openai")
            self.assertEqual(limiter.rate_per_second, 4.0)
            self.assertEqual(limiter.burst, 2)
            cached = get_limiter("openai")
            self.assertIs(cached, get_limiter("openai"))

    def test_bad_env_falls_back_to_zero(self) -> None:
        with mock.patch.dict("os.environ", {"GHOSTCHIMERA_RL_X_RPS": "nonsense"}, clear=True):
            self.assertTrue(limiter_from_env("x").unlimited)


if __name__ == "__main__":
    unittest.main()
