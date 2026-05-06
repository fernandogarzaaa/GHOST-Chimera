"""Async executor for Chimera Pilot.

Wraps the synchronous ChimeraPilotExecutor so that callers can run tasks
from async contexts or obtain a synchronous wrapper that works from any
thread.  Patterned after hermes-agent/model_tools.py's async bridging
logic (persistent event loops, thread-local worker loops, safe
sync->async transitions).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Coroutine
from typing import Any

from .executor import ChimeraPilotExecutor, PilotExecution
from .policy import PilotPolicy
from .scheduler import ChimeraScheduler
from .task_ir import TaskSpec
from .telemetry import InMemoryTelemetryStore

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300  # seconds

# -- persistent-event-loop state (mirrors model_tools.py) ---------- #

_async_loop: asyncio.AbstractEventLoop | None = None
_async_loop_lock = threading.Lock()
_worker_thread_local = threading.local()  # per-thread persistent loops

# Thread-local flag: set True when inside execute_async (an async context).
# This prevents _run_async from trying to use run_until_complete on a loop
# that's already running inside a nested executor thread.
_async_context_flag = threading.local()


def _get_async_loop() -> asyncio.AbstractEventLoop:
    """Return a long-lived event loop for the main thread.

    Using a persistent loop (instead of *asyncio.run()* which creates and
    closes a fresh loop every time) prevents "Event loop is closed" errors
    when cached async clients attempt to close their transport on a dead
    loop during garbage collection.
    """
    global _async_loop
    with _async_loop_lock:
        if _async_loop is None or _async_loop.is_closed():
            _async_loop = asyncio.new_event_loop()
        return _async_loop


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop for the current worker thread.

    Each worker thread gets its own long-lived loop stored in thread-local
    storage, avoiding contention with the main thread's shared loop.
    """
    loop = getattr(_worker_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _worker_thread_local.loop = loop
    return loop


def _run_async(coro: Coroutine) -> Any:
    """Run an async coroutine from a sync context.

    Strategy (three paths, matching model_tools.py):

    1. **Inside a running event loop** (async context): spawn a fresh
       one-shot thread so the coroutine runs on its own loop without
       conflicting with the outer loop.

    2. **Inside a worker thread** (not main): use the per-thread
       persistent loop.

    3. **Main thread, no running loop** (most common): use the global
       persistent main-loop.

    Timeout is enforced at DEFAULT_TIMEOUT seconds.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    # Path 1 -- inside a running event loop: use a fresh thread
    if loop and loop.is_running():
        worker_loop: asyncio.AbstractEventLoop | None = None
        loop_ready = threading.Event()

        def _run_in_worker() -> Any:
            nonlocal worker_loop
            worker_loop = asyncio.new_event_loop()
            loop_ready.set()
            try:
                asyncio.set_event_loop(worker_loop)
                return worker_loop.run_until_complete(coro)
            finally:
                try:
                    pending = asyncio.all_tasks(worker_loop)
                    for t in pending:
                        t.cancel()
                    if pending:
                        worker_loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except Exception:
                    logger.debug("Worker event-loop cleanup failed", exc_info=True)
                worker_loop.close()

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_run_in_worker)
        try:
            return future.result(timeout=DEFAULT_TIMEOUT)
        except concurrent.futures.TimeoutError:
            if loop_ready.wait(timeout=1.0) and worker_loop is not None:
                try:
                    for t in asyncio.all_tasks(worker_loop):
                        worker_loop.call_soon_threadsafe(t.cancel)
                except RuntimeError:
                    logger.debug("Worker loop was closed before cancellation could be scheduled", exc_info=True)
            raise
        finally:
            pool.shutdown(wait=False)

    # Path 2 -- worker thread (not main): use per-thread persistent loop
    if threading.current_thread() is not threading.main_thread():
        worker_loop = _get_worker_loop()
        return worker_loop.run_until_complete(coro)

    # Path 3 -- main thread, no running loop: use global persistent loop
    main_loop = _get_async_loop()
    return main_loop.run_until_complete(coro)


# ------------------  Public API  ------------------------  ---------------


class AsyncChimeraPilotExecutor:
    """Async-aware wrapper around *ChimeraPilotExecutor*.

    Every ``execute_*`` call transparently routes the blocking sync executor
    through the appropriate event-loop strategy (see ``_run_async``).
    """

    def __init__(
        self,
        scheduler: ChimeraScheduler,
        *,
        policy: PilotPolicy | None = None,
        verifier: Any = None,
        telemetry: InMemoryTelemetryStore | None = None,
    ) -> None:
        self._inner = ChimeraPilotExecutor(
            scheduler,
            policy=policy,
            verifier=verifier,
            telemetry=telemetry,
        )

    # -- async entry point ------

    async def execute_async(self, task: TaskSpec) -> PilotExecution:
        """Run *task* asynchronously (awaitable).

        If called *from* a running event loop, this method internally spins
        up a fresh one-shot thread with its own event loop so that the
        caller's loop is never blocked.

        If called from the main thread (no running loop), delegates to
        ``execute`` which uses the persistent main-loop.
        """
        try:
            inner_loop = asyncio.get_running_loop()
        except RuntimeError:
            inner_loop = None

        if inner_loop is not None:
            # Inside an async context -- spawn a fresh thread to avoid
            # blocking the caller's event loop.
            result_holder: PilotExecution
            error_holder: BaseException | None

            def _run_in_fresh_thread() -> PilotExecution:
                nonlocal result_holder, error_holder
                _async_context_flag.flag = True
                try:
                    return self._inner.execute(task)
                except BaseException as exc:
                    error_holder = exc
                    raise

            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = pool.submit(_run_in_fresh_thread)
            try:
                result_holder = future.result(timeout=DEFAULT_TIMEOUT)
            except concurrent.futures.TimeoutError:
                raise
            finally:
                _async_context_flag.flag = False
                pool.shutdown(wait=False)

            return result_holder
        else:
            # No running loop -- just delegate to sync wrapper
            return self.execute(task)

    # -- sync entry point (backward compat) ------

    def execute(self, task: TaskSpec) -> PilotExecution:
        """Synchronous wrapper for backward compatibility.

        Routes to the correct loop strategy via ``_run_async``.  If the
        current thread is already inside an async context (``_async_context_flag``
        is set), the sync executor runs in a fresh thread to avoid deadlock.
        """
        if getattr(_async_context_flag, "flag", False):
            # We're inside an async context -- use a fresh thread
            def _run_sync(task: TaskSpec) -> PilotExecution:
                return _run_async(self._execute_coro(task))

            return _run_sync(task)

        # Normal sync path -- _run_async will pick the right loop
        return _run_async(self._execute_coro(task))

    def _execute_coro(self, task: TaskSpec) -> Coroutine[Any, Any, PilotExecution]:
        """Build a coroutine that runs ``self._inner.execute``."""

        async def _run() -> PilotExecution:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._inner.execute, task)

        return _run()


__all__ = ["AsyncChimeraPilotExecutor"]
