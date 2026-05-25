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
    ".env.saas.example",
    "docker-compose.saas.yml",
    "docs/ARCHITECTURE.md",
    "docs/CLEAN_ROOM.md",
    "docs/BOB_OPTIONAL_TOOLING.md",
    "docs/COMPETITIVE_CAPABILITY_MATRIX.md",
    "docs/NATIVE_ABSORPTION.md",
    "docs/REMOTE_CONTROL.md",
    "docs/TRUST_RUNTIME.md",
    "docs/CAPABILITY_ADMISSION.md",
    "docs/PRODUCTION_DEPLOYMENT.md",
    "docs/PUBLIC_LAUNCH_SAAS.md",
    "docs/RELEASE_CHECKLIST.md",
    "docs/model_provider_catalog.json",
    "docs/model_provider_catalog.md",
    "docs/dependency_audit.md",
    "scripts/smoke_installed_wheel.py",
    "scripts/update_model_provider_catalog.py",
    ".github/dependabot.yml",
    ".github/workflows/daily-maintenance.yml",
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
        "ghostchimera.cognition_layer.trust",
        "ghostchimera.capability_pack",
        "ghostchimera.capability_admission",
        "ghostchimera.control_plane.cli",
        "ghostchimera.control_plane.host_execution",
        "ghostchimera.integrations.remote_control",
        "ghostchimera.model_layer.local_model_inventory",
        "ghostchimera.mcp.normalization",
        "ghostchimera.mcp.server",
        "ghostchimera.mcp.client",
        "ghostchimera.sandbox.journey",
        "ghostchimera.chimera_pilot.backends.mcp",
        "ghostchimera.trust_runtime",
        "ghostchimera.saas",
        "ghostchimera.saas.cli",
        "ghostchimera.saas.store",
        "ghostchimera.superiority",
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
            "ghostchimera local-model inventory",
            "ghostchimera local-model resolve --source Qwen/Qwen2.5-7B-Instruct",
            "ghostchimera cognition guard --confidence 0.9 --variance 0.01",
            'ghostchimera context compress --text "latency latency matters" --focus latency',
            "ghostchimera capability-pack list",
            "ghostchimera sandbox journey",
            "ghostchimera remote status",
            "ghostchimera trust eval-cases list",
            "ghostchimera capability-admission list",
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
        "ghostchimera capability-pack list",
        "ghostchimera local-model inventory",
        "ghostchimera cognition guard --confidence 0.9 --variance 0.01",
        "ghostchimera sandbox journey",
        "ghostchimera remote status",
        "ghostchimera trust eval-cases list",
        "ghostchimera capability-admission list",
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
    if '"remote", "status", "--state-dir"' not in smoke_script:
        errors.append("installed-wheel smoke script does not exercise remote control CLI")

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


def check_production_maintenance_artifacts() -> dict[str, Any]:
    """Check that production maintenance automation and generated reports are intact."""

    errors: list[str] = []

    daily_workflow = (ROOT / ".github" / "workflows" / "daily-maintenance.yml").read_text(encoding="utf-8")
    for token in (
        "schedule:",
        "workflow_dispatch:",
        "scripts/update_model_provider_catalog.py",
        "scripts/audit_dependencies.py --format markdown --output docs/dependency_audit.md",
        "tests/test_update_model_provider_catalog.py tests/test_model_discovery.py -q",
        "peter-evans/create-pull-request@v6",
        "No secrets are committed.",
    ):
        if token not in daily_workflow:
            errors.append(f"daily maintenance workflow missing {token!r}")

    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    for token in ("package-ecosystem: pip", "package-ecosystem: github-actions", "interval: daily"):
        if token not in dependabot:
            errors.append(f"dependabot config missing {token!r}")

    provider_catalog_path = ROOT / "docs" / "model_provider_catalog.json"
    try:
        provider_catalog = json.loads(provider_catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"model provider catalog is invalid JSON: {exc}")
        provider_catalog = {}

    if provider_catalog:
        policy = provider_catalog.get("policy", {})
        if policy.get("secrets_included") is not False:
            errors.append("model provider catalog policy must declare secrets_included=false")
        if policy.get("automatic_model_switching") is not False:
            errors.append("model provider catalog policy must declare automatic_model_switching=false")
        if not isinstance(provider_catalog.get("sources"), dict):
            errors.append("model provider catalog missing sources mapping")
        if not isinstance(provider_catalog.get("models"), list):
            errors.append("model provider catalog missing models list")
        if not provider_catalog.get("generated_at"):
            errors.append("model provider catalog missing generated_at")

    provider_catalog_md = (ROOT / "docs" / "model_provider_catalog.md").read_text(encoding="utf-8")
    for token in ("# Model Provider Catalog", "daily maintenance workflow", "never switches active models"):
        if token not in provider_catalog_md:
            errors.append(f"model provider catalog markdown missing {token!r}")

    dependency_audit = (ROOT / "docs" / "dependency_audit.md").read_text(encoding="utf-8")
    if "Ghost Chimera Dependency Specification Audit" not in dependency_audit:
        errors.append("dependency audit markdown missing expected title")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for token in (
        "Daily Production Maintenance",
        "docs/model_provider_catalog.md",
        "docs/dependency_audit.md",
        "scripts/update_model_provider_catalog.py",
    ):
        if token not in readme:
            errors.append(f"README missing production maintenance reference {token!r}")

    return {"ok": not errors, "errors": errors}


def check_public_launch_saas_artifacts() -> dict[str, Any]:
    """Check that the public-branch SaaS foundation remains wired and documented."""

    errors: list[str] = []
    doc = (ROOT / "docs" / "PUBLIC_LAUNCH_SAAS.md").read_text(encoding="utf-8")
    for token in (
        "generic OIDC",
        "organizations own workspaces",
        "Postgres is the SaaS source of truth",
        "ghostchimera saas status",
        "ghostchimera worker status",
        "docker-compose.saas.yml",
        "approval-first",
    ):
        if token not in doc:
            errors.append(f"public launch SaaS doc missing {token!r}")

    cli = (ROOT / "ghostchimera" / "control_plane" / "cli.py").read_text(encoding="utf-8")
    for token in ("sub.add_parser(\"saas\"", "sub.add_parser(\"worker\"", "run_saas_cli", "run_worker_cli"):
        if token not in cli:
            errors.append(f"CLI missing SaaS/worker surface {token!r}")

    schema = (ROOT / "ghostchimera" / "saas" / "store.py").read_text(encoding="utf-8")
    for table in (
        "organizations",
        "user_accounts",
        "memberships",
        "workspaces",
        "ghost_profiles",
        "tenant_secret_refs",
        "saas_runs",
        "saas_approvals",
        "audit_events",
        "worker_leases",
        "eval_baselines",
    ):
        if table not in schema:
            errors.append(f"SaaS schema missing {table!r}")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for token in ("Public Launch SaaS", "ghostchimera saas status", "ghostchimera worker status", "docker-compose.saas.yml"):
        if token not in readme:
            errors.append(f"README missing SaaS launch reference {token!r}")

    compose = (ROOT / "docker-compose.saas.yml").read_text(encoding="utf-8")
    for token in ("postgres:", "console:", "worker:", "no-new-privileges:true", "cap_drop:"):
        if token not in compose:
            errors.append(f"SaaS compose missing {token!r}")

    env_example = (ROOT / ".env.saas.example").read_text(encoding="utf-8")
    for token in (
        "GHOSTCHIMERA_DEPLOYMENT_TARGET=saas",
        "GHOSTCHIMERA_DATABASE_URL=",
        "GHOSTCHIMERA_OIDC_ISSUER=",
        "GHOSTCHIMERA_SESSION_SECRET=",
        "GHOSTCHIMERA_SECRETS_ENCRYPTION_KEY=",
        "GHOSTCHIMERA_WORKER_TOKEN=",
    ):
        if token not in env_example:
            errors.append(f"SaaS env example missing {token!r}")

    return {"ok": not errors, "errors": errors}


def check_public_superiority_artifacts() -> dict[str, Any]:
    """Check that the public superiority scorecard and Workbench proof are wired."""

    from ghostchimera.control_plane.console import RELEASE_CHECKS
    from ghostchimera.evals.runner import EVAL_SUITES
    from ghostchimera.superiority import build_superiority_scorecard

    errors: list[str] = []
    if "superiority" not in EVAL_SUITES:
        errors.append("superiority eval suite missing")

    commands = [check["command"] for check in RELEASE_CHECKS]
    for command in (
        "python -m ghostchimera.evals run --suite superiority",
        "ghostchimera superiority score --format json",
    ):
        if command not in commands:
            errors.append(f"console readiness missing {command!r}")

    html = (ROOT / "ghostchimera" / "control_plane" / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ghostchimera" / "control_plane" / "static" / "app.js").read_text(encoding="utf-8")
    for token in (
        "operatorWorkbench",
        "operatorCommandSearch",
        "nextBestActions",
        "superiorityScorecards",
        "browserE2EStatus",
        "/api/console/superiority",
        "renderSuperiorityScorecard",
    ):
        if token not in html + app:
            errors.append(f"Operator Workbench missing {token!r}")

    if not (ROOT / "scripts" / "run_operator_workbench_e2e.py").exists():
        errors.append("operator workbench browser E2E script missing")

    payload = build_superiority_scorecard(
        operator_summary={"ok": True, "warnings": [], "trust": {"ready": True}, "counts": {"approved_sources": 1}},
        capabilities={"ok": True, "score_ratio": 1.0, "capability_count": 14, "top_gaps": []},
        routes=[
            "/api/console/operator/summary",
            "/api/console/models/discovery",
            "/api/console/trust/summary",
            "/api/console/trust/runs",
            "/api/console/trust/approvals",
            "/api/console/trust/evals",
            "/api/console/evolution/candidates",
            "/api/console/remote/status",
            "/api/console/conversation/status",
            "/api/console/sandbox/journey",
            "/api/console/local-models/inventory",
            "/api/console/capability-pack",
            "/api/console/mcp/trust",
            "/api/console/autonomy/jobs",
            "/api/console/autonomy/schedules",
        ],
        static_html=html,
        static_app=app,
    ).to_dict()
    if payload.get("score_ratio", 0) < 0.85:
        errors.append(f"superiority score below launch threshold: {payload.get('score_ratio')}")
    serialized = json.dumps(payload)
    if "sk-" in serialized or "ghp_" in serialized:
        errors.append("superiority payload appears to expose raw secret-like content")

    return {"ok": not errors, "errors": errors, "score_ratio": payload.get("score_ratio")}


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
        "production_maintenance_artifacts": check_production_maintenance_artifacts(),
        "public_launch_saas_artifacts": check_public_launch_saas_artifacts(),
        "public_superiority_artifacts": check_public_superiority_artifacts(),
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
