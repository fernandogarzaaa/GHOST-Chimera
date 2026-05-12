"""Built-in Chimera Pilot backends."""

from .analytics import AnalyticsBackend
from .base import BackendCapabilities, BackendHealth, ChimeraBackend, ExecutionResult
from .cwr import CWRBackend
from .desktop_runtime import DesktopRuntimeBackend
from .deterministic import DeterministicBackend
from .gemini import GeminiBackend
from .llamacpp import LlamaCppBackend
from .mcp import MCPBackend
from .pyqpanda3_backend import PyQPanda3Backend
from .python_runtime import PythonRuntimeBackend
from .simulation import SimulationBackend


def discover_builtin_backends():
    """Discover and register all self-registering backends.

    Each backend module calls ``BackendRegistry.register()`` at import time.
    This function uses AST inspection to find which modules self-register,
    then imports them to trigger registration.
    """
    from ghostchimera.chimera_pilot.backend_registry import discover_builtin_backends as _discover
    return _discover()


__all__ = [
    "AnalyticsBackend",
    "BackendCapabilities",
    "BackendHealth",
    "ChimeraBackend",
    "CWRBackend",
    "DeterministicBackend",
    "DesktopRuntimeBackend",
    "ExecutionResult",
    "GeminiBackend",
    "LlamaCppBackend",
    "MCPBackend",
    "PyQPanda3Backend",
    "PythonRuntimeBackend",
    "SimulationBackend",
    "discover_builtin_backends",
]
