"""Shared fixtures for integration tests."""

from ghostchimera.chimera_pilot import ChimeraPilotKernel
from ghostchimera.chimera_pilot.backends.deterministic import DeterministicBackend
from ghostchimera.chimera_pilot.scheduler import ChimeraScheduler
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec
import pytest


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
    from ghostchimera.chimera_pilot.policy import PilotPolicy
    from ghostchimera.chimera_pilot.telemetry import InMemoryTelemetryStore
    from ghostchimera.chimera_pilot.executor import ChimeraPilotExecutor
    return ChimeraPilotExecutor(scheduler, policy=PilotPolicy(), telemetry=InMemoryTelemetryStore())


@pytest.fixture
def reasoning_task():
    """Sample reasoning task for testing."""
    return TaskSpec.create(kind=TaskKind.REASONING, objective="Test objective", inputs={"prompt": "hello"})
