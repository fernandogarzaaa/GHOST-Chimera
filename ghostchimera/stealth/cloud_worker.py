"""Off-hot-path executor for Stealth Loop cloud calls (Nemotron UNDERSTAND/PREDICT).

``StealthLoop.emit()`` used to make the Nebius call inline, so every attended
event blocked its producer for a full model round-trip (3-17 s live, up to the
provider timeout on a stalled endpoint). :class:`CloudEnricher` moves those
calls onto a small bounded thread pool and adds the guards a per-event cloud
call needs:

* a TTL'd LRU cache, so identical events reuse one answer;
* in-flight de-duplication, so a burst of identical events makes one call;
* a sliding one-minute call budget;
* a cap on queued work (excess requests are dropped, not queued forever).

``mode="sync"`` keeps the same cache and budget but runs the call inline,
which is what ``ghost demo`` replay/record and deterministic tests use.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Hashable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..logging_config import get_logger

logger = get_logger("stealth_cloud_worker")

DEFAULT_WORKERS = 2
DEFAULT_MAX_PENDING = 32
DEFAULT_CALLS_PER_MINUTE = 30
DEFAULT_CACHE_TTL_S = 300.0
DEFAULT_CACHE_SIZE = 256

Status = str  # "cached" | "done" | "submitted" | "inflight" | "budget" | "queue_full" | "error" | "closed"


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, "") or default))
    except ValueError:
        return default


class CloudEnricher:
    """Bounded, cached, budgeted executor for best-effort cloud calls."""

    def __init__(
        self,
        *,
        mode: str = "async",
        workers: int | None = None,
        max_pending: int | None = None,
        calls_per_minute: int | None = None,
        cache_ttl_s: float | None = None,
        cache_size: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.mode = "sync" if str(mode).lower() == "sync" else "async"
        self.workers = workers or _env_int("GHOSTCHIMERA_NEMOTRON_WORKERS", DEFAULT_WORKERS, minimum=1)
        self.max_pending = (
            max_pending
            if max_pending is not None
            else _env_int("GHOSTCHIMERA_NEMOTRON_MAX_PENDING", DEFAULT_MAX_PENDING, minimum=1)
        )
        # 0 disables the budget.
        self.calls_per_minute = (
            calls_per_minute
            if calls_per_minute is not None
            else _env_int("GHOSTCHIMERA_NEMOTRON_CALLS_PER_MIN", DEFAULT_CALLS_PER_MINUTE)
        )
        self.cache_ttl_s = (
            cache_ttl_s
            if cache_ttl_s is not None
            else _env_float("GHOSTCHIMERA_NEMOTRON_CACHE_TTL_S", DEFAULT_CACHE_TTL_S)
        )
        self.cache_size = cache_size if cache_size is not None else DEFAULT_CACHE_SIZE
        self._clock = clock
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._cache: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._inflight: dict[Hashable, list[Callable[[Any], None]]] = {}
        self._calls: deque[float] = deque()
        self._pending = 0
        self._executor: ThreadPoolExecutor | None = None
        self._closed = False
        self.stats: dict[str, int] = {
            "submitted": 0,
            "done": 0,
            "cached": 0,
            "inflight": 0,
            "budget": 0,
            "queue_full": 0,
            "error": 0,
        }

    # -- public API --------------------------------------------------------

    def request(self, key: Hashable, fn: Callable[[], Any], on_result: Callable[[Any], None]) -> Status:
        """Run ``fn`` (or reuse a cached/in-flight result) and pass the value to ``on_result``.

        In async mode ``on_result`` runs on a worker thread when the call
        finishes; in sync mode (and for cache hits) it runs before returning.
        ``on_result`` is never called when the request is skipped.
        """
        executor: ThreadPoolExecutor | None = None
        with self._lock:
            if self._closed:
                return "closed"
            cached = self._cache_get(key)
            if cached is not _MISS:
                self.stats["cached"] += 1
                hit = cached
            else:
                hit = _MISS
                if key in self._inflight:
                    self._inflight[key].append(on_result)
                    self.stats["inflight"] += 1
                    return "inflight"
                if not self._take_budget():
                    self.stats["budget"] += 1
                    return "budget"
                if self.mode == "async":
                    if self._pending >= self.max_pending:
                        self._refund_budget()
                        self.stats["queue_full"] += 1
                        return "queue_full"
                    self._pending += 1
                    self._inflight[key] = [on_result]
                    self.stats["submitted"] += 1
                    executor = self._ensure_executor()
        if hit is not _MISS:
            _safe_call(on_result, hit)
            return "cached"
        if self.mode == "sync":
            try:
                value = fn()
            except Exception as exc:  # best-effort: never break the loop
                logger.warning("Cloud call failed: %s", exc)
                with self._lock:
                    self.stats["error"] += 1
                return "error"
            with self._lock:
                self._cache_put(key, value)
                self.stats["done"] += 1
            _safe_call(on_result, value)
            return "done"
        assert executor is not None
        executor.submit(self._run, key, fn)
        return "submitted"

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Block until no async call is pending (for tests, shutdown, recording)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._idle:
            while self._pending > 0:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._idle.wait(remaining)
        return True

    @property
    def pending(self) -> int:
        with self._lock:
            return self._pending

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": self.mode,
                "pending": self._pending,
                "cache_entries": len(self._cache),
                "calls_last_minute": len(self._calls),
                "calls_per_minute": self.calls_per_minute,
                **self.stats,
            }

    def close(self, *, wait: bool = False) -> None:
        with self._lock:
            self._closed = True
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=not wait)

    # -- internals ---------------------------------------------------------

    def _run(self, key: Hashable, fn: Callable[[], Any]) -> None:
        value: Any = None
        ok = False
        try:
            value = fn()
            ok = True
        except Exception as exc:
            logger.warning("Cloud call failed: %s", exc)
        with self._lock:
            callbacks = self._inflight.pop(key, [])
            if ok:
                self._cache_put(key, value)
                self.stats["done"] += 1
            else:
                self.stats["error"] += 1
        try:
            if ok:
                for callback in callbacks:
                    _safe_call(callback, value)
        finally:
            with self._idle:
                self._pending -= 1
                if self._pending <= 0:
                    self._idle.notify_all()

    def _ensure_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="ghost-nemotron")
        return self._executor

    def _take_budget(self) -> bool:
        if self.calls_per_minute <= 0:
            return True
        now = self._clock()
        while self._calls and now - self._calls[0] >= 60.0:
            self._calls.popleft()
        if len(self._calls) >= self.calls_per_minute:
            return False
        self._calls.append(now)
        return True

    def _refund_budget(self) -> None:
        if self._calls:
            self._calls.pop()

    def _cache_get(self, key: Hashable) -> Any:
        if self.cache_ttl_s <= 0:
            return _MISS
        entry = self._cache.get(key)
        if entry is None:
            return _MISS
        stored_at, value = entry
        if self._clock() - stored_at > self.cache_ttl_s:
            self._cache.pop(key, None)
            return _MISS
        self._cache.move_to_end(key)
        return value

    def _cache_put(self, key: Hashable, value: Any) -> None:
        # Failures (None) are not cached, so a transient error is retried
        # on the next identical event (subject to the budget).
        if self.cache_ttl_s <= 0 or value is None:
            return
        self._cache[key] = (self._clock(), value)
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)


class _Miss:
    __slots__ = ()


_MISS: Any = _Miss()


def _safe_call(callback: Callable[[Any], None], value: Any) -> None:
    try:
        callback(value)
    except Exception as exc:
        logger.warning("Cloud result callback failed: %s", exc)


__all__ = ["CloudEnricher"]
