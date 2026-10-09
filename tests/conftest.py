"""Shared fixtures for integration tests."""

import os

import pytest

from ghostchimera.chimera_pilot import ChimeraPilotKernel
from ghostchimera.chimera_pilot.backends.deterministic import DeterministicBackend
from ghostchimera.chimera_pilot.scheduler import ChimeraScheduler
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def pytest_configure(config):
    """Bypass any HTTP(S)_PROXY for loopback calls made by the tests.

    Many tests start an in-process gateway on 127.0.0.1 and call it with
    urllib. When a proxy is configured (corporate networks, sandboxed CI)
    urllib would send those loopback requests to the proxy and fail with
    404/502, so make sure loopback hosts are always in NO_PROXY.
    """
    for var in ("NO_PROXY", "no_proxy"):
        existing = [h.strip() for h in os.environ.get(var, "").split(",") if h.strip()]
        os.environ[var] = ",".join(existing + [h for h in _LOOPBACK if h not in existing])


@pytest.fixture
def kernel():
    """Kernel with deterministic backend for reliable integration tests."""
    return ChimeraPilotKernel.default(include_deterministic_backend=True)


@pytest.fixture
def deterministic_backend():
    """Standalone deterministic backend."""
    return DeterministicBackend()


@pytest.fixture
def scheduler(deterministic_backend):
    """Scheduler with deterministic backend."""
    return ChimeraScheduler([deterministic_backend])


@pytest.fixture
def client(scheduler):
    """Executor with deterministic backend and scheduler."""
    from ghostchimera.chimera_pilot.executor import ChimeraPilotExecutor
    from ghostchimera.chimera_pilot.policy import PilotPolicy
    from ghostchimera.chimera_pilot.telemetry import InMemoryTelemetryStore

    return ChimeraPilotExecutor(scheduler, policy=PilotPolicy(), telemetry=InMemoryTelemetryStore())


@pytest.fixture
def reasoning_task():
    """Sample reasoning task for testing."""
    return TaskSpec.create(kind=TaskKind.REASONING, objective="Test objective", inputs={"prompt": "hello"})
