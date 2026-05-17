#!/usr/bin/env python3
"""Release validation gate for Ghost Chimera."""

from __future__ import annotations

import compileall
import importlib
import io
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REQUIRED_FILES = [
    "README.md",
    "LICENSE",
    "NOTICE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "CHIMERA_PILOT.md",
    "CHANGES.md",
    "pyproject.toml",
    "MANIFEST.in",
    "docs/ARCHITECTURE.md",
    "docs/CLEAN_ROOM.md",
    "docs/BOB_OPTIONAL_TOOLING.md",
    "docs/COMPETITIVE_CAPABILITY_MATRIX.md",
    "docs/RELEASE_CHECKLIST.md",
    "scripts/smoke_installed_wheel.py",
]

BOB_RUNTIME_MARKERS = (
    "IBM Bob",
    "Bob-to-Ghost",
    "bob_accelerator",
    "bob_delivery_package",
)

BOB_TOOLING_FILES = [
    ".github/pull_request_template.md",
    ".github/workflows/bob-quality.yml",
    ".github/workflows/test-matrix.yml",
    "docs/BOB_POST_HACKATHON_ROADMAP.md",
    "docs/bob-tools.md",
    "docs/sbom-lite.md",
    "examples/basic_config.py",
    "examples/bob_coverage_report.py",
    "examples/production_guardrails.py",
    "examples/test_scaffold_preview.py",
    "mkdocs.yml",
    "scripts/analyze_logs.py",
    "scripts/audit_dependencies.py",
    "scripts/bob_accelerator.py",
    "scripts/bob_delivery_package.py",
    "scripts/coverage_report.py",
    "scripts/dependency_graph.py",
    "scripts/dev_env.py",
    "scripts/generate_api_reference.py",
    "scripts/generate_changelog.py",
    "scripts/generate_sbom.py",
    "scripts/generate_test_scaffold.py",
    "scripts/validate_config.py",
    "tests/integration/test_bob_toolchain.py",
    "tests/performance/test_bob_tool_performance.py",
    "tests/test_api_reference_generator.py",
    "tests/test_dependency_graph.py",
    "tests/test_dev_env.py",
    "tests/test_docs_site.py",
    "tests/test_examples.py",
    "tests/test_log_analyzer.py",
    "tests/test_sbom_generator.py",
    "tests/test_workflows_and_pr_template.py",
]

BOB_TOOLING_COMMANDS = (
    "python scripts/bob_accelerator.py",
    "python scripts/audit_dependencies.py --format markdown",
    "python scripts/bob_delivery_package.py --output docs/bob_delivery_package.md",
    "python scripts/generate_api_reference.py",
    "python scripts/generate_sbom.py",
    "python scripts/dependency_graph.py",
    "python scripts/analyze_logs.py --demo",
    "python scripts/dev_env.py",
    "python -m pytest tests/integration/test_bob_toolchain.py -q",
    "python -m pytest tests/performance/test_bob_tool_performance.py -q",
)


def check_required_files() -> dict[str, Any]:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    return {"ok": not missing, "missing": missing}


def check_pyproject() -> dict[str, Any]:
    path = ROOT / "pyproject.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    scripts = project.get("scripts", {})
    required = ["name", "version", "description", "readme", "requires-python", "license"]
    missing = [key for key in required if not project.get(key)]
    if scripts.get("ghostchimera") != "ghostchimera.control_plane.cli:_main":
        missing.append("project.scripts.ghostchimera")
    if scripts.get("chimera-pilot") != "ghostchimera.chimera_pilot.cli:main":
        missing.append("project.scripts.chimera-pilot")
    if scripts.get("ghostchimera-eval") != "ghostchimera.evals.__main__:main":
        missing.append("project.scripts.ghostchimera-eval")
    return {"ok": not missing, "missing": missing, "name": project.get("name"), "version": project.get("version")}


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data.get("project", {}).get("version") or "")


def check_imports() -> dict[str, Any]:
    modules = [
        "ghostchimera",
        "ghostchimera.agent_core.core",
        "ghostchimera.chimera_pilot",
        "ghostchimera.chimera_pilot.cli",
        "ghostchimera.cognition_layer.workspace_state",
        "ghostchimera.control_plane.cli",
        "ghostchimera.mcp.server",
        "ghostchimera.mcp.client",
        "ghostchimera.chimera_pilot.backends.mcp",
    ]
    imported: list[str] = []
    for module in modules:
        try:
            importlib.import_module(module)
            imported.append(module)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "imported": imported}
    return {"ok": True, "modules": imported}


def check_policy_defaults() -> dict[str, Any]:
    from ghostchimera.chimera_pilot import ChimeraPilotKernel

    kernel = ChimeraPilotKernel.default(include_deterministic_backend=True)
    status = kernel.status()
    policy = status["policy"]
    ok = policy["allow_python_execution"] is False and policy["allow_network"] is False
    denied = False
    try:
        kernel.run("python: print(2 + 3)")
    except PermissionError:
        denied = True
    return {"ok": ok and denied, "policy": policy, "python_denied_by_default": denied}


def check_compileall() -> dict[str, Any]:
    # In some mounted artifact directories the source tree may be read-only to
    # the current Python process.  Write bytecode into a temporary pycache
    # prefix so the syntax check stays independent from checkout ownership.
    previous_prefix = sys.pycache_prefix
    with tempfile.TemporaryDirectory(prefix="ghostchimera-compile-") as cache_dir:
        sys.pycache_prefix = cache_dir
        try:
            ok = compileall.compile_dir(str(ROOT / "ghostchimera"), quiet=1) and compileall.compile_dir(
                str(ROOT / "tests"), quiet=1
            )
        finally:
            sys.pycache_prefix = previous_prefix
    return {"ok": bool(ok)}


def check_beta_features() -> dict[str, Any]:
    """Check that required beta feature surfaces exist."""
    errors: list[str] = []

    # rate_limiter.py
    rl = ROOT / "ghostchimera" / "safety_layer" / "rate_limiter.py"
    if not rl.exists():
        errors.append("rate_limiter.py missing")
    elif "RateLimiter" not in rl.read_text():
        errors.append("RateLimiter class not found in rate_limiter.py")

    # schema.py
    sc = ROOT / "ghostchimera" / "chimera_pilot" / "schema.py"
    if not sc.exists():
        errors.append("schema.py missing")
    elif "validate_task" not in sc.read_text():
        errors.append("validate_task not found in schema.py")

    # logging_config.py
    lc = ROOT / "ghostchimera" / "logging_config.py"
    if not lc.exists():
        errors.append("logging_config.py missing")
    elif "get_logger" not in lc.read_text():
        errors.append("get_logger not found in logging_config.py")

    # mcp/ directory
    mcp = ROOT / "ghostchimera" / "mcp"
    if not mcp.is_dir():
        errors.append("mcp/ directory missing")
    elif not (mcp / "server.py").exists():
        errors.append("mcp/server.py missing")
    elif not (mcp / "client.py").exists():
        errors.append("mcp/client.py missing")

    # router.py
    rt = ROOT / "ghostchimera" / "model_layer" / "router.py"
    if not rt.exists():
        errors.append("router.py missing")

    # telemetry export methods
    tel = ROOT / "ghostchimera" / "chimera_pilot" / "telemetry.py"
    if tel.exists():
        content = tel.read_text()
        if "export_json" not in content:
            errors.append("export_json not found in telemetry.py")
        if "export_csv" not in content:
            errors.append("export_csv not found in telemetry.py")
    else:
        errors.append("telemetry.py missing")

    # audit integrity
    aud = ROOT / "ghostchimera" / "safety_layer" / "audit.py"
    if aud.exists():
        content = aud.read_text()
        if "verify_integrity" not in content:
            errors.append("verify_integrity not found in audit.py")
    else:
        errors.append("audit.py missing")

    # version check
    init_py = ROOT / "ghostchimera" / "__init__.py"
    if init_py.exists():
        content = init_py.read_text()
        expected_version = project_version()
        if f'__version__ = "{expected_version}"' not in content:
            errors.append(f"version not {expected_version} in __init__.py")

    return {"ok": not errors, "errors": errors}


def check_release_hardening() -> dict[str, Any]:
    """Check that the beta release gate includes operator-journey coverage."""

    from ghostchimera.control_plane.console import RELEASE_CHECKS
    from ghostchimera.evals.runner import EVAL_SUITES

    errors: list[str] = []
    if "user-journey" not in EVAL_SUITES:
        errors.append("user-journey eval suite missing")
    if "competitive" not in EVAL_SUITES:
        errors.append("competitive eval suite missing")

    release_checklist = (ROOT / "docs" / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    missing_docs = [
        token
        for token in (
            "python -m ghostchimera.evals run --suite user-journey",
            "python -m ghostchimera.evals run --suite competitive",
            "python scripts/smoke_installed_wheel.py",
            "python scripts/smoke_installed_wheel.py --extras gateway",
            "ghostchimera capabilities --format json",
            "ghostchimera review-pr --base HEAD --head HEAD",
            "docs/COMPETITIVE_CAPABILITY_MATRIX.md",
            "ghostchimera workspace show",
            "ghostchimera workspace sync-memory",
            "--stale-after-days 30",
            "stale/conflicting",
            "clean virtual environment",
            "gateway extras",
        )
        if token not in release_checklist
    ]
    errors.extend(f"release checklist missing {token!r}" for token in missing_docs)

    commands = [check["command"] for check in RELEASE_CHECKS]
    for command in (
        "python -m ruff check .",
        "python -m pytest -q",
        "python -m ghostchimera.evals run --suite autonomy",
        "python -m ghostchimera.evals run --suite user-journey",
        "python -m ghostchimera.evals run --suite competitive",
        "python scripts/smoke_installed_wheel.py",
        "python scripts/smoke_installed_wheel.py --extras gateway",
        "ghostchimera capabilities --format json",
        "ghostchimera review-pr --base HEAD --head HEAD",
        "ghostchimera workspace show",
        "ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 --min-confidence 0.8 --stale-after-days 30",
    ):
        if command not in commands:
            errors.append(f"console readiness missing {command!r}")

    if "python -m pytest -q" not in release_checklist:
        errors.append("release checklist missing full pytest gate")

    eval_runner = (ROOT / "ghostchimera" / "evals" / "runner.py").read_text(encoding="utf-8")
    if "/api/console/workspace" not in eval_runner:
        errors.append("user-journey eval does not exercise console workspace state")
    if "workspace_sync_feeds_retrieval" not in eval_runner:
        errors.append("user-journey eval does not verify workspace sync feeds retrieval")
    if "workspace_sync_quality_flags" not in eval_runner:
        errors.append("user-journey eval does not verify workspace sync quality flags")
    if "competitive_capability_score" not in eval_runner:
        errors.append("competitive eval does not verify capability score")
    if "competitive_pr_review_cli" not in eval_runner:
        errors.append("competitive eval does not verify PR review CLI")

    smoke_script = (ROOT / "scripts" / "smoke_installed_wheel.py").read_text(encoding="utf-8")
    if "ghostchimera[{normalized}] @" not in smoke_script:
        errors.append("installed-wheel smoke script does not install extras from built wheel metadata")
    if '"workspace", "show", "--state-dir"' not in smoke_script:
        errors.append("installed-wheel smoke script does not exercise workspace CLI")
    if '"sync-memory"' not in smoke_script:
        errors.append("installed-wheel smoke script does not exercise workspace memory sync")

    return {"ok": not errors, "errors": errors}


def check_optional_tooling_boundary() -> dict[str, Any]:
    """Check optional hackathon/developer tooling does not enter runtime code."""

    errors: list[str] = []
    boundary_doc = ROOT / "docs" / "BOB_OPTIONAL_TOOLING.md"
    if not boundary_doc.exists():
        errors.append("docs/BOB_OPTIONAL_TOOLING.md missing")
    else:
        content = boundary_doc.read_text(encoding="utf-8")
        for token in (
            "not required to run Ghost Chimera",
            "Users who do not care about IBM Bob can ignore all Bob-named files",
            "Do not import Bob tooling from `ghostchimera/`",
        ):
            if token not in content:
                errors.append(f"Bob optional tooling doc missing {token!r}")

    runtime_dir = ROOT / "ghostchimera"
    for path in runtime_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in BOB_RUNTIME_MARKERS:
            if marker in text:
                errors.append(
                    f"runtime package references optional Bob tooling: {path.relative_to(ROOT)} contains {marker!r}"
                )

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject.get("project", {}).get("dependencies", [])
    optional_dependencies = pyproject.get("project", {}).get("optional-dependencies", {})
    dep_text = "\n".join([*dependencies, *[dep for deps in optional_dependencies.values() for dep in deps]]).lower()
    if "ibm" in dep_text and "bob" in dep_text:
        errors.append("pyproject dependencies appear to require IBM Bob")

    return {"ok": not errors, "errors": errors}


def check_bob_tooling_artifacts() -> dict[str, Any]:
    """Check that completed Bob roadmap claims remain backed by real artifacts."""

    errors: list[str] = []
    missing = [path for path in BOB_TOOLING_FILES if not (ROOT / path).exists()]
    errors.extend(f"Bob tooling artifact missing: {path}" for path in missing)

    roadmap = (ROOT / "docs" / "BOB_POST_HACKATHON_ROADMAP.md").read_text(encoding="utf-8")
    for token in (
        "Phase 1: Developer Tools (COMPLETE)",
        "Phase 2: Testing Infrastructure (COMPLETE)",
        "Phase 3: Documentation (COMPLETE)",
        "Phase 4: CI/CD and Release (COMPLETE)",
        "Phase 5: Advanced Developer Intelligence (COMPLETE)",
        "Do Not Fake Completion Policy",
        "Runtime Boundary",
    ):
        if token not in roadmap:
            errors.append(f"Bob roadmap missing {token!r}")

    bob_workflow = (ROOT / ".github" / "workflows" / "bob-quality.yml").read_text(encoding="utf-8")
    for token in (
        "python scripts/bob_accelerator.py",
        "python scripts/audit_dependencies.py --format markdown",
        "python scripts/bob_delivery_package.py --output docs/bob_delivery_package.md",
        "tests/integration/test_bob_toolchain.py",
        "tests/performance/test_bob_tool_performance.py",
    ):
        if token not in bob_workflow:
            errors.append(f"Bob quality workflow missing {token!r}")

    matrix_workflow = (ROOT / ".github" / "workflows" / "test-matrix.yml").read_text(encoding="utf-8")
    for token in ("ubuntu-latest", "macos-latest", "windows-latest", '"3.11"', '"3.12"', '"3.13"'):
        if token not in matrix_workflow:
            errors.append(f"test matrix workflow missing {token!r}")

    docs_site = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    for token in ("IBM Bob Tools: bob-tools.md", "API Reference: api-reference.md", "Roadmap: BOB_POST_HACKATHON_ROADMAP.md"):
        if token not in docs_site:
            errors.append(f"mkdocs navigation missing {token!r}")

    release_checklist = (ROOT / "docs" / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    missing_commands = [command for command in BOB_TOOLING_COMMANDS if command not in release_checklist]
    errors.extend(f"release checklist missing Bob tooling command {command!r}" for command in missing_commands)

    return {"ok": not errors, "errors": errors, "artifact_count": len(BOB_TOOLING_FILES)}


def check_unittest() -> dict[str, Any]:
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        [
            "tests.test_agent_core_pilot",
            "tests.test_chimera_pilot",
            "tests.test_code_search",
            "tests.test_config",
            "tests.test_conscious_workspace",
            "tests.test_console",
            "tests.test_cwr_backend",
            "tests.test_evals",
            "tests.test_llamacpp_backend",
            "tests.test_local_model_profiles",
            "tests.test_release_package",
            "tests.test_safety_policy",
        ]
    )
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    output = stream.getvalue()
    return {
        "ok": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "output_tail": "\n".join(output.splitlines()[-30:]),
    }


def main() -> int:
    checks = {
        "required_files": check_required_files(),
        "pyproject": check_pyproject(),
        "imports": check_imports(),
        "beta_features": check_beta_features(),
        "release_hardening": check_release_hardening(),
        "optional_tooling_boundary": check_optional_tooling_boundary(),
        "bob_tooling_artifacts": check_bob_tooling_artifacts(),
        "policy_defaults": check_policy_defaults(),
        "compileall": check_compileall(),
        "unittest": check_unittest(),
    }
    ok = all(item["ok"] for item in checks.values())
    payload = {"ok": ok, "checks": checks}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
