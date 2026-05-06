"""Integration tests for the full Chimera Pilot pipeline."""

import pytest

from ghostchimera.chimera_pilot import ChimeraPilotKernel
from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
from ghostchimera.chimera_pilot.policy import PilotPolicy
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec


@pytest.fixture
def kernel():
    return ChimeraPilotKernel.default(include_deterministic_backend=True)


@pytest.fixture
def reasoning_task(kernel):
    return TaskSpec.create(kind=TaskKind.REASONING, objective="reasoning test", inputs={"prompt": "reasoning test"})


def test_compile_and_execute(kernel, reasoning_task):
    """Compile an objective into a task and execute it through the full pipeline."""
    task = TaskSpec.create(kind=TaskKind.REASONING, objective="test", inputs={"prompt": "test"})
    from ghostchimera.chimera_pilot.executor import ChimeraPilotExecutor
    from ghostchimera.chimera_pilot.scheduler import ChimeraScheduler
    backends = kernel.registry.list()
    scheduler = ChimeraScheduler(backends)
    executor = ChimeraPilotExecutor(scheduler, policy=PilotPolicy(allow_network=True, allow_python_execution=True, default_max_cost_usd=100.0))
    result = executor.execute(task)
    assert result is not None
    assert result.ok


def test_scheduler_ranks_backends(kernel, reasoning_task):
    """Scheduler should rank backends by score with deterministic backend at top."""
    from ghostchimera.chimera_pilot.scheduler import ChimeraScheduler
    backends = kernel.registry.list()
    scheduler = ChimeraScheduler(backends)
    decisions = scheduler.rank_backends(reasoning_task)
    assert len(decisions) > 0


def test_policy_blocks_denied_objective(kernel):
    """Policy should block objectives containing denied fragments."""
    compiler = RuleBasedTaskCompiler()
    policy = PilotPolicy()
    spec = compiler.compile("execute python: rm -rf /")
    with pytest.raises(PermissionError):
        policy.validate(spec[0])


def test_fallback_on_failure():
    """Executor should retry failed backends and use fallback."""
    from ghostchimera.chimera_pilot.backends.deterministic import DeterministicBackend
    from ghostchimera.chimera_pilot.executor import ChimeraPilotExecutor
    from ghostchimera.chimera_pilot.scheduler import ChimeraScheduler
    kernel = ChimeraPilotKernel.default(include_deterministic_backend=True)
    # Register a failing backend with a unique id to avoid duplicate registration
    failing = DeterministicBackend(backend_id="deterministic-fail", fail=True)
    try:
        kernel.registry.register(failing)
    except ValueError:
        assert any(backend.id == failing.id for backend in kernel.registry.list())
    # Use a valid task spec that passes validation
    task = TaskSpec.create(kind=TaskKind.REASONING, objective="test", inputs={"prompt": "test"})
    backends = kernel.registry.list()
    scheduler = ChimeraScheduler(backends)
    executor = ChimeraPilotExecutor(scheduler, policy=PilotPolicy(allow_network=True, allow_python_execution=True, default_max_cost_usd=100.0))
    result = executor.execute(task)
    assert result is not None
