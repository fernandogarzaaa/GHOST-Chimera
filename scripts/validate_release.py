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
    "docs/COMPETITIVE_CAPABILITY_MATRIX.md",
    "docs/RELEASE_CHECKLIST.md",
    "scripts/smoke_installed_wheel.py",
]


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
            ok = compileall.compile_dir(str(ROOT / "ghostchimera"), quiet=1) and compileall.compile_dir(str(ROOT / "tests"), quiet=1)
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
        "ghostchimera workspace show",
        "ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 --min-confidence 0.8 --stale-after-days 30",
    ):
        if command not in commands:
            errors.append(f"console readiness missing {command!r}")

    eval_runner = (ROOT / "ghostchimera" / "evals" / "runner.py").read_text(encoding="utf-8")
    if "/api/console/workspace" not in eval_runner:
        errors.append("user-journey eval does not exercise console workspace state")
    if "workspace_sync_feeds_retrieval" not in eval_runner:
        errors.append("user-journey eval does not verify workspace sync feeds retrieval")
    if "workspace_sync_quality_flags" not in eval_runner:
        errors.append("user-journey eval does not verify workspace sync quality flags")
    if "competitive_capability_score" not in eval_runner:
        errors.append("competitive eval does not verify capability score")

    smoke_script = (ROOT / "scripts" / "smoke_installed_wheel.py").read_text(encoding="utf-8")
    if "ghostchimera[{normalized}] @" not in smoke_script:
        errors.append("installed-wheel smoke script does not install extras from built wheel metadata")
    if '"workspace", "show", "--state-dir"' not in smoke_script:
        errors.append("installed-wheel smoke script does not exercise workspace CLI")
    if '"sync-memory"' not in smoke_script:
        errors.append("installed-wheel smoke script does not exercise workspace memory sync")

    return {"ok": not errors, "errors": errors}


def check_unittest() -> dict[str, Any]:
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromNames([
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
    ])
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
