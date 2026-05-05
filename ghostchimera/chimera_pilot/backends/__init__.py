"""Built-in Chimera Pilot backends."""

from .base import BackendCapabilities, BackendHealth, ChimeraBackend, ExecutionResult
from .cwr import CWRBackend
from .deterministic import DeterministicBackend
from .llamacpp import LlamaCppBackend
from .mcp import MCPBackend
from .pyqpanda3_backend import PyQPanda3Backend
from .python_runtime import PythonRuntimeBackend


def discover_builtin_backends():
    """Discover and register all self-registering backends.

    Each backend module calls ``BackendRegistry.register()`` at import time.
    This function uses AST inspection to find which modules self-register,
    then imports them to trigger registration.
    """
    from ghostchimera.chimera_pilot.backend_registry import discover_builtin_backends as _discover
    return _discover()


__all__ = [
    "BackendCapabilities",
    "BackendHealth",
    "ChimeraBackend",
    "CWRBackend",
    "DeterministicBackend",
    "ExecutionResult",
    "LlamaCppBackend",
    "MCPBackend",
    "PyQPanda3Backend",
    "PythonRuntimeBackend",
    "discover_builtin_backends",
]
