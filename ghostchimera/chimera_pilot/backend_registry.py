"""Self-registering backend registry for Ghost Chimera.

Backends declare registration metadata as class-level attributes
(_description, _check_fn) which ``discover_builtin_backends()`` detects
via introspection, then imports and registers the module's exported class.

Unlike ``ResourceRegistry``, this registry supports:
- Declaration-based registration (class attributes)
- Introspection-based discovery of backends in the backends/ directory
- Thread-safe mutation and snapshot reads
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CHECK_FN_TTL_SECONDS = 30.0
_check_fn_cache: dict[Callable, tuple[float, bool]] = {}
_check_fn_cache_lock = threading.Lock()


def _module_has_registration_attrs(module_path: Path) -> bool:
    """Return True when the module exports a class with _description or _check_fn."""
    try:
        source = module_path.read_text(encoding="utf-8")
    except OSError:
        return False
    # Quick heuristic: look for _description or _check_fn in the source
    return "_description" in source or "_check_fn" in source


def discover_builtin_backends(backend_dir: Path | None = None) -> list[str]:
    """Discover, import, and register all self-registering backend modules.

    Each backend module must export a class with either:
    - ``_description: str`` – human-readable description
    - ``_check_fn: Callable`` – availability check function

    Returns:
        List of imported module names.
    """
    backend_path = Path(backend_dir) if backend_dir is not None else Path(__file__).resolve().parent / "backends"
    candidates = [
        path.stem
        for path in sorted(backend_path.glob("*.py"))
        if path.name not in {"__init__.py", "base.py"}
        and _module_has_registration_attrs(path)
    ]

    # Import the registry singleton
    from ghostchimera.chimera_pilot.backend_registry import default

    imported: list[str] = []
    for stem in candidates:
        mod_name = f"ghostchimera.chimera_pilot.backends.{stem}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:
            logger.warning("Could not import backend module %s: %s", mod_name, exc)
            continue

        # Find the backend class (first class with _description or _check_fn)
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if not isinstance(obj, type):
                continue
            desc = getattr(obj, "_description", None)
            check_fn = getattr(obj, "_check_fn", None)
            if desc is not None or check_fn is not None:
                default.register(obj, check_fn=check_fn, description=desc or "")
                imported.append(mod_name)
                break

    return imported


@dataclass(frozen=True)
class BackendEntry:
    """Metadata for a single registered backend."""
    backend_class: type
    check_fn: Callable | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_class": self.backend_class.__name__,
            "check_fn": self.check_fn.__name__ if self.check_fn else None,
            "description": self.description,
        }


def _check_fn_cached(fn: Callable) -> bool:
    """Return bool(fn()), TTL-cached across calls."""
    now = time.monotonic()
    with _check_fn_cache_lock:
        cached = _check_fn_cache.get(fn)
        if cached is not None:
            ts, value = cached
            if now - ts < _CHECK_FN_TTL_SECONDS:
                return value
    try:
        value = bool(fn())
    except Exception:
        value = False
    with _check_fn_cache_lock:
        _check_fn_cache[fn] = (now, value)
    return value


def invalidate_check_fn_cache() -> None:
    """Drop all cached ``check_fn`` results."""
    with _check_fn_cache_lock:
        _check_fn_cache.clear()


class BackendRegistry:
    """Singleton registry that collects backend classes from self-registering modules."""

    _instance: BackendRegistry | None = None
    _lock = threading.RLock()

    def __new__(cls) -> BackendRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._backends: dict[str, BackendEntry] = {}
                    cls._instance._check_fns: dict[str, Callable] = {}
                    cls._instance._generation = 0
        return cls._instance

    def _snapshot_backends(self) -> list[BackendEntry]:
        with self._lock:
            return list(self._backends.values())

    def register(
        self,
        backend_class: type,
        check_fn: Callable | None = None,
        description: str = "",
    ) -> None:
        """Register a backend class."""
        with self._lock:
            backend_id = backend_class.__name__
            self._backends[backend_id] = BackendEntry(
                backend_class=backend_class,
                check_fn=check_fn,
                description=description,
            )
            if check_fn is not None:
                self._check_fns[backend_id] = check_fn
            self._generation += 1

    def deregister(self, backend_id: str) -> None:
        with self._lock:
            self._backends.pop(backend_id, None)
            self._check_fns.pop(backend_id, None)
            self._generation += 1

    def get_all_classes(self) -> list[type]:
        """Return all registered backend classes as a stable snapshot."""
        return [entry.backend_class for entry in self._snapshot_backends()]

    def is_available(self, backend_id: str) -> bool:
        """Check if a backend's requirements are met."""
        with self._lock:
            check = self._check_fns.get(backend_id)
        if not check:
            return True
        try:
            return _check_fn_cached(check)
        except Exception:
            return False

    def get_registered_ids(self) -> list[str]:
        """Return sorted backend IDs."""
        return sorted(self._backends.keys())

    def get_check_fns(self) -> dict[str, Callable]:
        with self._lock:
            return dict(self._check_fns)

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation


# Singleton instance (class remains accessible as BackendRegistry)
default = BackendRegistry()
