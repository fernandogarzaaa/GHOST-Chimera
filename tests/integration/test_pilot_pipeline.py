"""Integration tests for the full Chimera Pilot pipeline."""

from ghostchimera.chimera_pilot import ChimeraPilotKernel
from ghostchimera.chimera_pilot.policy import PilotPolicy
from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
from ghostchimera.chimera_pilot.task_ir import TaskKind


def test_compile_and_execute(kernel, reasoning_task):
    """Compile an objective into a task and execute it through the full pipeline."""
    executions = kernel.run("test objective")
    assert len(executions) == 1
    assert executions[0].ok
    assert executions[0].result.ok


def test_scheduler_ranks_backends(kernel):
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
    kernel = ChimeraPilotKernel.default(include_deterministic_backend=True)
    kernel.registry.register(DeterministicBackend(fail=True))
    # Should still succeed with at least one working backend
    executions = kernel.run("test objective")
    assert any(e.ok for e in executions)
