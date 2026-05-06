"""Hook registry for Chimera Pilot lifecycle events.

Mirrors OpenClaw's ``PluginHookHandlerMap`` pattern.  Hooks are fire-and-
forget: registered callables receive keyword arguments but their return
values are ignored.  Exceptions inside a hook are caught and logged so they
never interrupt the main execution flow.

Usage::

    from ghostchimera.chimera_pilot.hooks import HookRegistry, HookName

    hooks = HookRegistry()

    @hooks.on(HookName.TASK_EXECUTE_POST)
    def my_hook(*, task, execution, **kwargs):
        print(f"Task {task.id} finished: ok={execution.result.ok}")

    # Or programmatically:
    hooks.register_hook(HookName.SESSION_START, my_startup_fn)

    # Fired internally by ChimeraPilotKernel:
    hooks.fire(HookName.TASK_COMPILE, objective="do something")
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from ..logging_config import get_logger

logger = get_logger("hooks")


class HookName(StrEnum):
    """Well-known lifecycle hook names for Chimera Pilot."""

    SESSION_START = "session_start"
    """Fired once when the kernel first executes a run."""

    TASK_COMPILE = "task_compile"
    """Fired after the compiler produces a TaskSpec list.

    Keyword args: ``objective`` (str), ``tasks`` (list[TaskSpec])
    """

    TASK_EXECUTE_PRE = "task_execute_pre"
    """Fired before a single task is dispatched to the scheduler/executor.

    Keyword args: ``task`` (TaskSpec)
    """

    TASK_EXECUTE_POST = "task_execute_post"
    """Fired after a single task execution completes (success or failure).

    Keyword args: ``task`` (TaskSpec), ``execution`` (PilotExecution)
    """

    BACKEND_FALLBACK = "backend_fallback"
    """Fired when the executor falls back from one backend to another.

    Keyword args: ``task`` (TaskSpec), ``failed_backend_id`` (str),
    ``fallback_backend_id`` (str), ``error`` (str)
    """

    SESSION_END = "session_end"
    """Fired after all tasks in a ``kernel.run()`` call complete."""


Handler = Callable[..., Any]


class HookRegistry:
    """Register and dispatch lifecycle hooks.

    Thread-safe: hooks are copied at dispatch time so registration during
    dispatch is safe.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[Handler]] = defaultdict(list)
        self._session_started = False

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_hook(self, name: HookName | str, fn: Handler) -> None:
        """Register *fn* to be called when *name* fires.

        Multiple handlers may be registered for the same hook; they are
        called in registration order.
        """
        key = name.value if isinstance(name, HookName) else str(name)
        self._hooks[key].append(fn)
        logger.debug("Registered hook %s -> %s", key, fn)

    def on(self, name: HookName | str) -> Callable[[Handler], Handler]:
        """Decorator shorthand for :meth:`register_hook`.

        Example::

            @hooks.on(HookName.TASK_COMPILE)
            def log_tasks(*, objective, tasks, **kwargs):
                print(f"{len(tasks)} tasks compiled for: {objective}")
        """
        def decorator(fn: Handler) -> Handler:
            self.register_hook(name, fn)
            return fn
        return decorator

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def fire(self, name: HookName | str, **kwargs: Any) -> None:
        """Invoke all handlers registered for *name*.

        Exceptions raised inside a handler are caught and logged; they
        never propagate to the caller.
        """
        key = name.value if isinstance(name, HookName) else str(name)
        handlers = list(self._hooks.get(key, []))
        for handler in handlers:
            try:
                handler(**kwargs)
            except Exception as exc:
                logger.warning("Hook %s handler %s raised: %s", key, handler, exc)

    def handler_count(self, name: HookName | str) -> int:
        """Return the number of handlers registered for *name*."""
        key = name.value if isinstance(name, HookName) else str(name)
        return len(self._hooks.get(key, []))

    def clear(self, name: HookName | str | None = None) -> None:
        """Remove handlers.  Clears a single hook if *name* is given, else all."""
        if name is None:
            self._hooks.clear()
        else:
            key = name.value if isinstance(name, HookName) else str(name)
            self._hooks.pop(key, None)


__all__ = ["HookName", "HookRegistry", "Handler"]
