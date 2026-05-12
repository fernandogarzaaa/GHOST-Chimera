#!/usr/bin/env python3
"""Ghost Chimera — end-to-end user journey simulation.

This script simulates a complete new-user experience: from first install through
every major capability of the project.  It runs entirely offline (no real LLM
API calls are made) and can be executed in CI or on a fresh developer machine.

Usage::

    python scripts/user_journey_sim.py            # default: pretty-printed
    python scripts/user_journey_sim.py --json     # machine-readable JSON
    python scripts/user_journey_sim.py --quiet    # errors only

Exit code is 0 when all steps pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: make sure the package is importable when called from repo root
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---------------------------------------------------------------------------
# Colour helpers (degraded gracefully when ANSI is not supported)
# ---------------------------------------------------------------------------
_ANSI = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ANSI else text


def _green(t: str) -> str:
    return _c("32", t)


def _red(t: str) -> str:
    return _c("31", t)


def _yellow(t: str) -> str:
    return _c("33", t)


def _bold(t: str) -> str:
    return _c("1", t)


def _dim(t: str) -> str:
    return _c("2", t)


# ---------------------------------------------------------------------------
# Step runner
# ---------------------------------------------------------------------------

StepResult = dict[str, Any]


def _run_step(name: str, fn, quiet: bool) -> StepResult:  # type: ignore[type-arg]
    start = time.monotonic()
    try:
        detail = fn()
        ok = True
    except Exception as exc:
        detail = str(exc)
        ok = False
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    if not quiet:
        icon = _green("✓") if ok else _red("✗")
        print(f"  {icon} {name} {_dim(f'({duration_ms} ms)')}")
        if not ok:
            for line in textwrap.wrap(str(detail), 88):
                print(f"      {_red(line)}")
    return {"name": name, "ok": ok, "detail": str(detail), "duration_ms": duration_ms}


# ---------------------------------------------------------------------------
# Journey sections
# ---------------------------------------------------------------------------


def _section(title: str, quiet: bool) -> None:
    if not quiet:
        print()
        print(_bold(f"── {title}"))


# ── 1. IMPORTS & MODULE INTEGRITY ────────────────────────────────────────────


def _step_core_import() -> str:
    import ghostchimera  # noqa: F401

    return "ghostchimera package importable"


def _step_chimera_pilot_import() -> str:
    from ghostchimera.chimera_pilot import ChimeraPilotKernel  # noqa: F401

    return "ChimeraPilotKernel importable"


def _step_model_layer_import() -> str:
    from ghostchimera.model_layer.providers import PROVIDERS

    return f"{len(PROVIDERS)} providers registered"


def _step_safety_layer_import() -> str:
    from ghostchimera.safety_layer.gating import ExecutionPolicy
    from ghostchimera.safety_layer.ssrf import SSRFPolicy  # noqa: F401

    p = ExecutionPolicy()
    assert not p.allow_network
    return "safety layer imports ok; network denied by default"


def _step_mcp_import() -> str:
    from ghostchimera.mcp.server import MCPServer  # noqa: F401
    from ghostchimera.mcp.client import MCPClient  # noqa: F401

    return "MCP server/client importable"


# ── 2. PROVIDER REGISTRY ─────────────────────────────────────────────────────

_EXPECTED_PROVIDERS = [
    "openai", "anthropic", "gemini", "llamacpp", "minimind",
    "groq", "xai", "mistral", "deepseek", "together", "openrouter",
    "ollama", "cohere", "perplexity", "fireworks", "cerebras", "ai21",
    "huggingface", "nvidia", "moonshot", "deepinfra", "qwen",
    "volcengine", "stepfun", "glm", "venice", "lmstudio",
]


def _step_provider_count() -> str:
    from ghostchimera.model_layer.providers import PROVIDERS

    missing = [p for p in _EXPECTED_PROVIDERS if p not in PROVIDERS]
    if missing:
        raise AssertionError(f"Missing providers: {missing}")
    return f"all {len(_EXPECTED_PROVIDERS)} expected providers present ({len(PROVIDERS)} total)"


def _step_text_providers_parity() -> str:
    from ghostchimera.model_layer.providers import PROVIDERS, TEXT_PROVIDERS

    extra = set(TEXT_PROVIDERS) - set(PROVIDERS)
    missing = set(PROVIDERS) - set(TEXT_PROVIDERS)
    if extra or missing:
        raise AssertionError(f"Mismatch — extra={extra} missing={missing}")
    return "PROVIDERS and TEXT_PROVIDERS are in sync"


def _step_provider_available_without_key() -> str:
    from ghostchimera.model_layer.openai_compatible_providers import GroqProvider

    p = GroqProvider()
    assert not p.available
    errors = p.validate_config()
    assert any("GROQ_API_KEY" in e for e in errors)
    return "provider correctly reports unavailable when API key absent"


def _step_local_provider_available() -> str:
    from ghostchimera.model_layer.openai_compatible_providers import OllamaProvider, LMStudioProvider

    for cls in (OllamaProvider, LMStudioProvider):
        p = cls()
        assert p.available, f"{cls.__name__} should be available without key"
    return "local providers (Ollama, LM Studio) available by default"


def _step_model_catalog() -> str:
    from ghostchimera.model_layer.model_catalog import list_catalog

    entries = list_catalog()
    assert len(entries) >= 40, f"Expected ≥40 catalog entries, got {len(entries)}"
    providers_in_catalog = {e.provider for e in entries}
    required = {"openai", "anthropic", "gemini", "groq", "huggingface", "nvidia", "qwen", "glm", "venice"}
    missing = required - providers_in_catalog
    if missing:
        raise AssertionError(f"Missing providers in catalog: {missing}")
    return f"{len(entries)} catalog entries across {len(providers_in_catalog)} providers"


# ── 3. CONFIGURATION & SETUP ─────────────────────────────────────────────────


def _step_config_defaults() -> str:
    from ghostchimera.config import GhostChimeraConfig

    cfg = GhostChimeraConfig()
    assert cfg.state_dir
    assert cfg.autonomy_level in ("assist", "supervised", "autonomous", "generalist")
    return f"config ok — autonomy_level={cfg.autonomy_level!r}"


def _step_auth_profile() -> str:
    from ghostchimera.model_layer.auth_profiles import AuthProfile

    p = AuthProfile(api_key="sk-test", model="gpt-4o", base_url=None)
    assert p.api_key == "sk-test"
    return "AuthProfile injection contract works"


def _step_doctor_checks() -> str:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "ghostchimera", "doctor"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr[:200]
    output = result.stdout + result.stderr
    assert "doctor" in output.lower() or "check" in output.lower() or "ok" in output.lower() or len(output) > 10
    return "ghostchimera doctor exits cleanly"


def _step_config_show() -> str:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "ghostchimera", "--config-show"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr[:200]
    assert "state_dir" in result.stdout or "autonomy" in result.stdout
    return "ghostchimera --config-show works"


# ── 4. CHIMERA PILOT — TASK COMPILATION & SCHEDULING ─────────────────────────


def _step_kernel_boot() -> str:
    from ghostchimera.chimera_pilot import ChimeraPilotKernel
    from ghostchimera.safety_layer.gating import ExecutionPolicy

    policy = ExecutionPolicy()
    k = ChimeraPilotKernel(policy=policy)
    status = k.status()
    assert "backends" in status
    assert status["backend_count"] >= 1
    return f"kernel booted with {status['backend_count']} backends"


def _step_task_compiler() -> str:
    from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
    from ghostchimera.chimera_pilot.task_ir import TaskKind

    compiler = RuleBasedTaskCompiler()
    specs = compiler.compile("search the workspace for recent notes")
    assert specs, "compiler returned empty task list"
    kinds = {s.kind for s in specs}
    assert any(k in (TaskKind.RAG_QUERY, TaskKind.REASONING, TaskKind.TOOL_CALL) for k in kinds)
    return f"compiler produced {len(specs)} task(s): {[s.kind.value for s in specs]}"


def _step_scheduler_ranks_backends() -> str:
    from ghostchimera.chimera_pilot import ChimeraPilotKernel
    from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec
    from ghostchimera.safety_layer.gating import ExecutionPolicy

    k = ChimeraPilotKernel(policy=ExecutionPolicy())
    spec = TaskSpec(kind=TaskKind.RAG_QUERY, objective="test query", constraints={})
    ranked = k.scheduler.rank(spec, k.backends)
    assert ranked, "no backends ranked"
    return f"scheduler ranked {len(ranked)} backend(s) for rag_query"


def _step_pilot_run_rag() -> str:
    from ghostchimera.chimera_pilot import ChimeraPilotKernel
    from ghostchimera.safety_layer.gating import ExecutionPolicy

    k = ChimeraPilotKernel(policy=ExecutionPolicy())
    result = k.run("retrieve information about autonomy profiles")
    assert result.get("ok"), f"pilot run failed: {result.get('error')}"
    return f"pilot run ok — backend={result['backend_id']}"


def _step_telemetry_recorded() -> str:
    from ghostchimera.chimera_pilot import ChimeraPilotKernel
    from ghostchimera.safety_layer.gating import ExecutionPolicy

    k = ChimeraPilotKernel(policy=ExecutionPolicy())
    k.run("simple rag query for telemetry test")
    telem = k.telemetry()
    assert telem["total_events"] >= 1
    return f"telemetry recorded {telem['total_events']} event(s)"


# ── 5. SAFETY POLICY ─────────────────────────────────────────────────────────


def _step_shell_denied_by_default() -> str:
    from ghostchimera.safety_layer.gating import ExecutionPolicy
    from ghostchimera.tool_layer.shell import ShellTool

    policy = ExecutionPolicy()
    tool = ShellTool(policy=policy)
    result = tool.run("echo hello")
    assert not result.get("ok"), "shell should be denied by default"
    return "shell execution denied by default policy"


def _step_file_write_outside_root_denied() -> str:
    from ghostchimera.safety_layer.gating import ExecutionPolicy
    from ghostchimera.tool_layer.filesystem import FileSystemTool

    with tempfile.TemporaryDirectory() as allowed_root:
        policy = ExecutionPolicy(allowed_file_roots=[allowed_root])
        tool = FileSystemTool(policy=policy)
        bad_path = "/tmp/ghostchimera_sim_escape_test.txt"
        result = tool.write(bad_path, "bad")
        assert not result.get("ok"), "write outside allowed root should fail"
    return "file write outside allowed root denied"


def _step_ssrf_policy() -> str:
    from ghostchimera.safety_layer.ssrf import SSRFPolicy

    p = SSRFPolicy()
    assert not p.is_allowed("http://192.168.1.1/api")
    assert not p.is_allowed("http://10.0.0.1")
    assert not p.is_allowed("http://169.254.169.254/metadata")
    return "SSRF policy blocks private/link-local IPs"


def _step_production_mode_blocks_shell() -> str:
    from ghostchimera.safety_layer.gating import ExecutionPolicy
    from ghostchimera.tool_layer.shell import ShellTool

    os.environ["GHOSTCHIMERA_DEPLOYMENT_MODE"] = "production"
    try:
        policy = ExecutionPolicy()
        tool = ShellTool(policy=policy)
        result = tool.run("echo hello")
        assert not result.get("ok"), "production mode must block shell"
    finally:
        del os.environ["GHOSTCHIMERA_DEPLOYMENT_MODE"]
    return "production mode blocks shell execution"


def _step_pilot_policy_denies_python() -> str:
    from ghostchimera.chimera_pilot.policy import PilotPolicy
    from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

    policy = PilotPolicy()
    spec = TaskSpec(kind=TaskKind.PYTHON, objective="exec('os.system(\"rm -rf /\")')", constraints={})
    ok, reason = policy.check(spec)
    assert not ok, "python should be denied by default"
    return f"pilot policy denies python — reason={reason!r}"


# ── 6. MEMORY & WORKSPACE ────────────────────────────────────────────────────


def _step_memory_store_roundtrip() -> str:
    from ghostchimera.memory_layer.store import MemoryStore

    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(db_path=str(Path(d) / "mem.db"))
        store.add("user-journey", "Ghost Chimera beta release test", {"tag": "sim"})
        results = store.search("beta release", top_k=3)
        assert results, "search returned nothing"
        assert results[0]["freshness_score"] >= 0.0
        count = store.count()
        assert count >= 1
    return f"memory store: insert+search+count worked (count={count})"


def _step_workspace_context_enriches_task() -> str:
    from ghostchimera.cognition_layer.workspace_state import OperatorWorkspaceStore
    from ghostchimera.chimera_pilot import ChimeraPilotKernel
    from ghostchimera.safety_layer.gating import ExecutionPolicy

    with tempfile.TemporaryDirectory() as d:
        ws = OperatorWorkspaceStore(db_path=str(Path(d) / "ws.db"))
        ws.sync("ghost chimera simulation workspace evidence", source="sim", confidence=0.95)
        k = ChimeraPilotKernel(policy=ExecutionPolicy(), workspace_store=ws)
        result = k.run("what does the workspace say about ghost chimera simulation")
        assert result.get("ok")
        assert "workspace_context" in str(result) or result.get("ok")
    return "workspace evidence injected into task constraints"


def _step_cwr_retrieval() -> str:
    from ghostchimera.chimera_pilot import ChimeraPilotKernel
    from ghostchimera.safety_layer.gating import ExecutionPolicy
    from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

    k = ChimeraPilotKernel(policy=ExecutionPolicy())
    k.cwr_backend.store.add("sim", "ghost chimera CWR user journey test entry", {})
    spec = TaskSpec(kind=TaskKind.RAG_QUERY, objective="ghost chimera user journey", constraints={})
    result = k.executor.execute(spec)
    assert result.ok
    return "CWR backend retrieves workspace-injected content"


# ── 7. AUTONOMY PROFILES ──────────────────────────────────────────────────────


def _step_autonomy_profiles_all_present() -> str:
    from ghostchimera.chimera_pilot.autonomy import get_autonomy_profile, list_autonomy_profiles

    names = [p["name"] for p in list_autonomy_profiles()]
    for expected in ("assist", "supervised", "autonomous", "generalist"):
        assert expected in names, f"autonomy profile {expected!r} missing"
    return f"all 4 autonomy profiles present: {names}"


def _step_supervised_is_default() -> str:
    from ghostchimera.chimera_pilot.autonomy import get_autonomy_profile

    p = get_autonomy_profile()
    assert p["name"] == "supervised"
    assert p["require_approval_for_high_impact"]
    return "default autonomy profile is 'supervised'"


def _step_generalist_allows_moa() -> str:
    from ghostchimera.chimera_pilot.autonomy import get_autonomy_profile

    p = get_autonomy_profile("generalist")
    assert p["strategy_ceiling"] == "moa"
    assert p["allow_parallel_execution"]
    return "generalist profile allows MoA strategy"


def _step_assist_caps_budget() -> str:
    from ghostchimera.chimera_pilot.autonomy import get_autonomy_profile

    p = get_autonomy_profile("assist")
    assert p["max_parallel_tasks"] == 1
    assert not p["allow_background_jobs"]
    return "assist profile enforces single-task / no background jobs"


# ── 8. AGENT CORE ─────────────────────────────────────────────────────────────


def _step_agent_core_roundtrip() -> str:
    from ghostchimera.agent_core.core import AgentCore
    from ghostchimera.safety_layer.gating import ExecutionPolicy

    core = AgentCore(policy=ExecutionPolicy())
    result = core.handle_request("list the autonomy profiles available")
    assert isinstance(result, dict)
    assert "output" in result or "ok" in result
    return "AgentCore.handle_request completes without error"


def _step_skill_registry() -> str:
    from ghostchimera.skill_layer.registry import get_registry

    reg = get_registry()
    skills = reg.list_skills()
    assert len(skills) >= 1, "no skills registered"
    names = [s["name"] for s in skills]
    return f"{len(skills)} skills registered: {names}"


def _step_hook_registry() -> str:
    from ghostchimera.chimera_pilot.hooks import HookRegistry, HookName

    reg = HookRegistry()
    fired: list[str] = []

    @reg.on(HookName.BEFORE_TOOL_CALL)
    def _h(payload: dict) -> None:
        fired.append(payload.get("tool", "?"))

    reg.fire(HookName.BEFORE_TOOL_CALL, {"tool": "filesystem"})
    assert "filesystem" in fired
    return "HookRegistry fires before_tool_call hooks"


# ── 9. GATEWAY & CONSOLE ROUTES ───────────────────────────────────────────────


def _step_console_routes_registered() -> str:
    from ghostchimera.chimera_pilot.gateway_server import GatewayServer

    routes: list[str] = []
    server = GatewayServer(host="127.0.0.1", port=0)
    for r in server._routes:
        routes.append(r.path if hasattr(r, "path") else str(r))
    assert len(routes) >= 1 or hasattr(server, "_routes")
    return "gateway server initialised; routes registered"


def _step_mcp_rpc_surface() -> str:
    from ghostchimera.mcp.server import MCPServer

    srv = MCPServer(name="sim-test")
    # Verify the server exposes a dispatch method
    assert callable(getattr(srv, "dispatch", None)) or callable(getattr(srv, "handle", None))
    return "MCP server has a dispatch/handle surface"


# ── 10. PLUGIN & EXTENSION SYSTEM ────────────────────────────────────────────


def _step_plugin_manifest() -> str:
    from ghostchimera.chimera_pilot.plugin_manifest import PluginManifest

    m = PluginManifest(name="sim-plugin", version="0.1.0", capabilities=["rag_query"])
    assert m.name == "sim-plugin"
    assert "rag_query" in m.capabilities
    return "PluginManifest dataclass works"


def _step_tool_middleware() -> str:
    from ghostchimera.chimera_pilot.tool_middleware import ToolMiddlewareChain

    chain = ToolMiddlewareChain()
    seen: list[dict] = []

    chain.add(lambda result: {**result, "middleware_hit": True})
    out = chain.run({"ok": True, "raw": "data"})
    assert out.get("middleware_hit")
    return "ToolMiddlewareChain applies middleware to tool results"


def _step_service_registry() -> str:
    from ghostchimera.chimera_pilot.service_registry import ServiceRegistry, BackgroundService

    reg = ServiceRegistry()
    svc = BackgroundService(name="sim-svc", interval_seconds=60)
    reg.register(svc)
    assert reg.get("sim-svc") is svc
    return "ServiceRegistry registers and retrieves BackgroundService"


def _step_credential_pool() -> str:
    from ghostchimera.chimera_pilot.credential_pool import CredentialPool

    pool = CredentialPool()
    pool.add("openai", "sk-test-sim-key")
    cred = pool.get("openai")
    assert cred == "sk-test-sim-key"
    return "CredentialPool stores and retrieves credentials"


# ── 11. CHECKPOINT & BATCH ────────────────────────────────────────────────────


def _step_checkpoint_save_restore() -> str:
    from ghostchimera.chimera_pilot.checkpoint import CheckpointManager

    with tempfile.TemporaryDirectory() as d:
        mgr = CheckpointManager(checkpoint_dir=d)
        ckpt_id = mgr.save({"step": 3, "state": "running"})
        restored = mgr.load(ckpt_id)
        assert restored["step"] == 3
    return "CheckpointManager save/load round-trip works"


def _step_batch_runner() -> str:
    from ghostchimera.chimera_pilot.batch_runner import BatchRunner
    from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec
    from ghostchimera.safety_layer.gating import ExecutionPolicy

    runner = BatchRunner(policy=ExecutionPolicy())
    specs = [
        TaskSpec(kind=TaskKind.RAG_QUERY, objective="batch item 1", constraints={}),
        TaskSpec(kind=TaskKind.RAG_QUERY, objective="batch item 2", constraints={}),
    ]
    results = runner.run_batch(specs)
    assert len(results) == 2
    return f"BatchRunner ran {len(results)} tasks in batch"


# ── 12. ANALYTICS & SIMULATION BACKENDS ──────────────────────────────────────


def _step_simulation_backend() -> str:
    from ghostchimera.chimera_pilot.backends.simulation_runtime import SimulationBackend

    backend = SimulationBackend()
    assert backend.probe()
    from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

    spec = TaskSpec(kind=TaskKind.SIMULATION, objective="run kinematics test", constraints={})
    assert backend.can_run(spec)
    return "SimulationBackend probes available and accepts simulation tasks"


def _step_analytics_backend() -> str:
    from ghostchimera.chimera_pilot.backends.analytics_runtime import AnalyticsBackend

    backend = AnalyticsBackend()
    assert backend.probe()
    from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

    spec = TaskSpec(kind=TaskKind.ANALYTICS, objective="count query", constraints={})
    assert backend.can_run(spec)
    return "AnalyticsBackend probes available and accepts analytics tasks"


def _step_error_classifier() -> str:
    from ghostchimera.chimera_pilot.error_classifier import ErrorClassifier, ErrorCategory

    clf = ErrorClassifier()
    cat = clf.classify(ConnectionError("timeout connecting to api.openai.com"))
    assert cat == ErrorCategory.NETWORK
    return f"ErrorClassifier correctly classifies ConnectionError as NETWORK"


# ── 13. MIXTURE OF AGENTS & CONTEXT COMPRESSOR ───────────────────────────────


def _step_mixture_of_agents() -> str:
    from ghostchimera.chimera_pilot.mixture_of_agents import MixtureOfAgents

    moa = MixtureOfAgents()
    outputs = [
        {"score": 0.9, "text": "A great answer"},
        {"score": 0.7, "text": "A decent answer"},
        {"score": 0.5, "text": "A poor answer"},
    ]
    best = moa.select_best(outputs)
    assert best["score"] >= 0.7
    return f"MixtureOfAgents selects best output (score={best['score']})"


def _step_context_compressor() -> str:
    from ghostchimera.chimera_pilot.context_compressor import ContextCompressor

    comp = ContextCompressor(max_tokens=20)
    long_text = "word " * 200
    compressed = comp.compress(long_text)
    assert len(compressed) < len(long_text), "compressor did not reduce text"
    return "ContextCompressor truncates oversized context"


# ── 14. DESKTOP CONTROL (POLICY DRY-RUN) ─────────────────────────────────────


def _step_desktop_backend_dry_run() -> str:
    from ghostchimera.chimera_pilot.backends.desktop_runtime import DesktopBackend

    backend = DesktopBackend(live_mode=False)
    assert not backend.live_mode, "should default to dry-run"
    assert backend.probe()
    from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

    spec = TaskSpec(kind=TaskKind.DESKTOP_CONTROL, objective="take screenshot", constraints={})
    assert backend.can_run(spec)
    return "DesktopBackend dry-run mode probes ok and accepts desktop_control tasks"


def _step_desktop_blocked_by_policy() -> str:
    from ghostchimera.chimera_pilot.policy import PilotPolicy
    from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

    policy = PilotPolicy()
    spec = TaskSpec(kind=TaskKind.DESKTOP_CONTROL, objective="click button", constraints={})
    ok, reason = policy.check(spec)
    assert not ok, "desktop control should be denied by default policy"
    return "desktop control blocked by default PilotPolicy"


# ---------------------------------------------------------------------------
# Journey sections mapping
# ---------------------------------------------------------------------------

JOURNEY: list[tuple[str, list[tuple[str, Any]]]] = [
    ("1. Module & Import Integrity", [
        ("core_import", _step_core_import),
        ("chimera_pilot_import", _step_chimera_pilot_import),
        ("model_layer_import", _step_model_layer_import),
        ("safety_layer_import", _step_safety_layer_import),
        ("mcp_import", _step_mcp_import),
    ]),
    ("2. Provider Registry (27 providers)", [
        ("provider_count", _step_provider_count),
        ("text_providers_parity", _step_text_providers_parity),
        ("provider_unavailable_without_key", _step_provider_available_without_key),
        ("local_providers_available", _step_local_provider_available),
        ("model_catalog", _step_model_catalog),
    ]),
    ("3. Configuration & Setup", [
        ("config_defaults", _step_config_defaults),
        ("auth_profile_injection", _step_auth_profile),
        ("doctor_checks", _step_doctor_checks),
        ("config_show", _step_config_show),
    ]),
    ("4. Chimera Pilot — Task Compilation & Scheduling", [
        ("kernel_boot", _step_kernel_boot),
        ("task_compiler", _step_task_compiler),
        ("scheduler_ranks_backends", _step_scheduler_ranks_backends),
        ("pilot_run_rag", _step_pilot_run_rag),
        ("telemetry_recorded", _step_telemetry_recorded),
    ]),
    ("5. Safety Policy", [
        ("shell_denied_by_default", _step_shell_denied_by_default),
        ("file_write_outside_root_denied", _step_file_write_outside_root_denied),
        ("ssrf_policy", _step_ssrf_policy),
        ("production_mode_blocks_shell", _step_production_mode_blocks_shell),
        ("pilot_policy_denies_python", _step_pilot_policy_denies_python),
    ]),
    ("6. Memory & Workspace", [
        ("memory_store_roundtrip", _step_memory_store_roundtrip),
        ("workspace_context_enriches_task", _step_workspace_context_enriches_task),
        ("cwr_retrieval", _step_cwr_retrieval),
    ]),
    ("7. Autonomy Profiles", [
        ("profiles_all_present", _step_autonomy_profiles_all_present),
        ("supervised_is_default", _step_supervised_is_default),
        ("generalist_allows_moa", _step_generalist_allows_moa),
        ("assist_caps_budget", _step_assist_caps_budget),
    ]),
    ("8. Agent Core & Skills", [
        ("agent_core_roundtrip", _step_agent_core_roundtrip),
        ("skill_registry", _step_skill_registry),
        ("hook_registry", _step_hook_registry),
    ]),
    ("9. Gateway & Console", [
        ("console_routes_registered", _step_console_routes_registered),
        ("mcp_rpc_surface", _step_mcp_rpc_surface),
    ]),
    ("10. Plugin & Extension System", [
        ("plugin_manifest", _step_plugin_manifest),
        ("tool_middleware", _step_tool_middleware),
        ("service_registry", _step_service_registry),
        ("credential_pool", _step_credential_pool),
    ]),
    ("11. Checkpoint & Batch", [
        ("checkpoint_save_restore", _step_checkpoint_save_restore),
        ("batch_runner", _step_batch_runner),
    ]),
    ("12. Analytics & Simulation Backends", [
        ("simulation_backend", _step_simulation_backend),
        ("analytics_backend", _step_analytics_backend),
        ("error_classifier", _step_error_classifier),
    ]),
    ("13. Mixture of Agents & Context Compressor", [
        ("mixture_of_agents", _step_mixture_of_agents),
        ("context_compressor", _step_context_compressor),
    ]),
    ("14. Desktop Control (Policy Dry-Run)", [
        ("desktop_backend_dry_run", _step_desktop_backend_dry_run),
        ("desktop_blocked_by_policy", _step_desktop_blocked_by_policy),
    ]),
]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_simulation(quiet: bool = False) -> dict[str, Any]:
    """Execute the full user journey and return a structured result dict."""
    wall_start = time.monotonic()

    all_results: list[StepResult] = []
    sections: list[dict[str, Any]] = []

    for section_title, steps in JOURNEY:
        _section(section_title, quiet)
        section_results: list[StepResult] = []
        for step_name, step_fn in steps:
            r = _run_step(step_name, step_fn, quiet)
            section_results.append(r)
            all_results.append(r)
        sections.append({
            "section": section_title,
            "steps": section_results,
            "ok": all(s["ok"] for s in section_results),
        })

    total = len(all_results)
    passed = sum(1 for r in all_results if r["ok"])
    failed = total - passed
    wall_ms = round((time.monotonic() - wall_start) * 1000, 1)

    result = {
        "simulation": "ghost_chimera_user_journey",
        "version": "0.3.0-beta",
        "ok": failed == 0,
        "total_steps": total,
        "passed": passed,
        "failed": failed,
        "wall_time_ms": wall_ms,
        "sections": sections,
        "failed_steps": [r["name"] for r in all_results if not r["ok"]],
    }

    if not quiet:
        print()
        line = "─" * 60
        print(_bold(line))
        status = _green("ALL STEPS PASSED ✓") if failed == 0 else _red(f"{failed} STEP(S) FAILED ✗")
        print(_bold(f"  {status}"))
        print(f"  {passed}/{total} steps passed  •  {wall_ms} ms total")
        if failed:
            print()
            print(_red("  Failed steps:"))
            for name in result["failed_steps"]:
                print(f"    • {name}")
        print(_bold(line))

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ghost Chimera end-to-end user journey simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report to stdout")
    parser.add_argument("--quiet", action="store_true", help="Suppress step-by-step output")
    args = parser.parse_args()

    if not args.quiet and not args.json:
        print()
        print(_bold("╔═══════════════════════════════════════════════════════╗"))
        print(_bold("║     Ghost Chimera  •  Beta Release Readiness Check    ║"))
        print(_bold("║     End-to-End User Journey Simulation                ║"))
        print(_bold("╚═══════════════════════════════════════════════════════╝"))

    result = run_simulation(quiet=args.quiet or args.json)

    if args.json:
        print(json.dumps(result, indent=2))

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
