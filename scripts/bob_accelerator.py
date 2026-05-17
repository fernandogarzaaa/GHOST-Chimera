#!/usr/bin/env python3
"""IBM Bob - Ghost Chimera Delivery Accelerator

This tool provides a comprehensive developer productivity and repository health report,
implementing the backlog identified by IBM Bob's repository analysis.

Usage:
    python scripts/bob_accelerator.py
    python scripts/bob_accelerator.py --format json
    python scripts/bob_accelerator.py --section onboarding
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from coverage_report import analyze_coverage

ROOT = Path(__file__).resolve().parents[1]
GHOSTCHIMERA_DIR = ROOT / "ghostchimera"
TESTS_DIR = ROOT / "tests"
DOCS_DIR = ROOT / "docs"


def check_system_readiness() -> dict[str, Any]:
    """Check system prerequisites for Ghost Chimera development."""
    results = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_ok": sys.version_info >= (3, 11),
        "git_available": False,
        "venv_active": hasattr(sys, "real_prefix") or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix),
    }

    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        results["git_available"] = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return results


def analyze_test_coverage() -> dict[str, Any]:
    """Analyze test coverage by mapping source files to test files."""
    coverage = analyze_coverage()

    return {
        "total_source_files": coverage["total_modules"],
        "total_test_files": len(list(TESTS_DIR.rglob("test_*.py"))),
        "untested_modules": [item["source"] for item in coverage["untested"][:10]],
        "untested_count": coverage["untested_count"],
        "coverage_ratio": round(coverage["coverage_ratio"], 2),
        "status": "good" if coverage["coverage_ratio"] > 0.8 else "needs_improvement",
    }


def analyze_documentation() -> dict[str, Any]:
    """Analyze documentation completeness and organization."""
    doc_files = list(DOCS_DIR.rglob("*.md"))
    root_docs = list(ROOT.glob("*.md"))

    required_docs = [
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CHANGELOG.md",
        "docs/ARCHITECTURE.md",
        "docs/RELEASE_CHECKLIST.md",
    ]

    missing_docs = []
    for doc in required_docs:
        if not (ROOT / doc).exists():
            missing_docs.append(doc)

    # Check for ADR directory
    adr_dir = DOCS_DIR / "adr"
    has_adr = adr_dir.exists()

    return {
        "total_doc_files": len(doc_files) + len(root_docs),
        "docs_in_docs_dir": len(doc_files),
        "root_level_docs": len(root_docs),
        "missing_required": missing_docs,
        "has_adr_system": has_adr,
        "status": "good" if not missing_docs else "needs_improvement",
    }


def check_dependencies() -> dict[str, Any]:
    """Check dependency health and optional extras."""
    pyproject_path = ROOT / "pyproject.toml"

    if not pyproject_path.exists():
        return {"status": "error", "message": "pyproject.toml not found"}

    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})

    optional_deps = project.get("optional-dependencies", {})

    # Check which extras are installed
    installed_extras = []
    for extra_name in optional_deps:
        # Simple heuristic: check if key packages are importable
        if extra_name == "gateway":
            try:
                import websockets  # noqa: F401

                installed_extras.append(extra_name)
            except ImportError:
                pass
        elif extra_name == "mcp":
            try:
                import mcp  # noqa: F401

                installed_extras.append(extra_name)
            except ImportError:
                pass
        elif extra_name == "local":
            try:
                import llama_cpp  # noqa: F401

                installed_extras.append(extra_name)
            except ImportError:
                pass

    return {
        "base_dependencies": len(project.get("dependencies", [])),
        "optional_extras": list(optional_deps.keys()),
        "installed_extras": installed_extras,
        "total_extras": len(optional_deps),
        "status": "good",
    }


def analyze_release_readiness() -> dict[str, Any]:
    """Check release readiness based on RELEASE_CHECKLIST.md."""
    checklist_path = DOCS_DIR / "RELEASE_CHECKLIST.md"

    if not checklist_path.exists():
        return {"status": "error", "message": "RELEASE_CHECKLIST.md not found"}

    content = checklist_path.read_text(encoding="utf-8")

    # Count checklist items
    checklist_items = [line for line in content.split("\n") if line.strip().startswith("- [ ]")]

    # Check if key files exist
    key_files = ["CHANGELOG.md", "SECURITY.md", "scripts/validate_release.py"]
    missing_files = [f for f in key_files if not (ROOT / f).exists()]

    return {
        "checklist_items": len(checklist_items),
        "missing_key_files": missing_files,
        "has_validation_script": (ROOT / "scripts" / "validate_release.py").exists(),
        "status": "good" if not missing_files else "needs_improvement",
    }


def generate_onboarding_guide() -> dict[str, Any]:
    """Generate personalized onboarding recommendations."""
    system = check_system_readiness()
    deps = check_dependencies()

    recommendations = []

    if not system["python_ok"]:
        recommendations.append(
            {
                "priority": "critical",
                "action": "Upgrade Python to 3.11 or higher",
                "reason": "Ghost Chimera requires Python 3.11+",
            }
        )

    if not system["venv_active"]:
        recommendations.append(
            {
                "priority": "high",
                "action": "Create and activate a virtual environment",
                "command": "python -m venv .venv && source .venv/bin/activate",
            }
        )

    if not system["git_available"]:
        recommendations.append(
            {
                "priority": "high",
                "action": "Install Git",
                "reason": "Required for version control and development",
            }
        )

    # Recommend installing dev extras
    if "dev" not in deps["installed_extras"]:
        recommendations.append(
            {
                "priority": "medium",
                "action": "Install development dependencies",
                "command": "pip install -e '.[dev]'",
            }
        )

    if "gateway" not in deps["installed_extras"]:
        recommendations.append(
            {
                "priority": "low",
                "action": "Install gateway extras for console UI",
                "command": "pip install -e '.[gateway]'",
            }
        )

    return {
        "system_ready": system["python_ok"] and system["git_available"],
        "recommendations": recommendations,
        "quick_start_command": "pip install -e '.[dev,gateway]' && python -m pytest tests/ -q",
    }


def detect_bob_tools() -> dict[str, Any]:
    """Detect installed Bob developer tools."""
    scripts_dir = ROOT / "scripts"

    bob_tools = {
        "bob_accelerator.py": "Developer productivity report",
        "coverage_report.py": "Test coverage analysis",
        "bob_delivery_package.py": "PR-ready delivery package generator",
        "generate_changelog.py": "Automated changelog generator",
        "validate_config.py": "Configuration validator",
        "audit_dependencies.py": "Dependency specification audit",
        "generate_test_scaffold.py": "Intelligent test scaffold generator",
        "generate_api_reference.py": "AST-based API reference generator",
        "generate_sbom.py": "SBOM-lite generator",
        "dependency_graph.py": "Dependency graph visualizer",
        "analyze_logs.py": "Debug log analyzer",
        "dev_env.py": "Local dev environment manager",
    }

    installed = []
    missing = []

    for tool, description in bob_tools.items():
        tool_path = scripts_dir / tool
        if tool_path.exists():
            installed.append({"name": tool, "description": description})
        else:
            missing.append({"name": tool, "description": description})

    return {
        "expected_count": len(bob_tools),
        "installed_count": len(installed),
        "installed_tools": installed,
        "missing_count": len(missing),
        "missing_tools": missing,
    }


def identify_quick_wins() -> list[dict[str, Any]]:
    """Identify quick win improvements based on Bob's backlog."""
    coverage = analyze_test_coverage()
    docs = analyze_documentation()

    wins = []

    if coverage["untested_count"] > 0:
        wins.append(
            {
                "item": "Add test coverage for untested modules",
                "effort": "low",
                "impact": "high",
                "modules": coverage["untested_modules"][:3],
            }
        )

    if not docs["has_adr_system"]:
        wins.append(
            {
                "item": "Create Architecture Decision Records (ADR) system",
                "effort": "low",
                "impact": "medium",
                "action": "mkdir -p docs/adr && create ADR template",
            }
        )

    return wins


def generate_report(format_type: str = "text", section: str | None = None) -> str:
    """Generate comprehensive developer productivity report."""
    report_data = {
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_by": "IBM Bob - Ghost Chimera Delivery Accelerator",
        "sections": {},
    }

    sections_to_run = {
        "system": check_system_readiness,
        "bob_tools": detect_bob_tools,
        "test_coverage": analyze_test_coverage,
        "documentation": analyze_documentation,
        "dependencies": check_dependencies,
        "release_readiness": analyze_release_readiness,
        "onboarding": generate_onboarding_guide,
    }

    if section:
        if section not in sections_to_run:
            return f"Error: Unknown section '{section}'. Available: {', '.join(sections_to_run.keys())}"
        sections_to_run = {section: sections_to_run[section]}

    for section_name, func in sections_to_run.items():
        report_data["sections"][section_name] = func()

    report_data["quick_wins"] = identify_quick_wins()

    if format_type == "json":
        return json.dumps(report_data, indent=2)

    # Text format
    lines = []
    lines.append("=" * 80)
    lines.append("IBM Bob - Ghost Chimera Delivery Accelerator Report")
    lines.append("=" * 80)
    lines.append(f"Generated: {report_data['generated_at']}")
    lines.append("")

    # System Readiness
    if "system" in report_data["sections"]:
        sys_data = report_data["sections"]["system"]
        lines.append("## System Readiness")
        lines.append(f"  Python Version: {sys_data['python_version']} {'OK' if sys_data['python_ok'] else 'FAIL'}")
        lines.append(f"  Git Available: {'OK' if sys_data['git_available'] else 'FAIL'}")
        lines.append(f"  Virtual Environment: {'OK' if sys_data['venv_active'] else 'FAIL'}")
        lines.append("")

    # Bob Tools
    if "bob_tools" in report_data["sections"]:
        bob_data = report_data["sections"]["bob_tools"]
        lines.append("## IBM Bob Developer Tools")
        lines.append(f"  Installed Tools: {bob_data['installed_count']}/{bob_data['expected_count']}")
        if bob_data["installed_tools"]:
            lines.append("  Available:")
            for tool in bob_data["installed_tools"]:
                lines.append(f"    - {tool['name']}: {tool['description']}")
        if bob_data["missing_tools"]:
            lines.append("  Missing:")
            for tool in bob_data["missing_tools"]:
                lines.append(f"    - {tool['name']}: {tool['description']}")
        lines.append("")

    # Test Coverage
    if "test_coverage" in report_data["sections"]:
        cov_data = report_data["sections"]["test_coverage"]
        lines.append("## Test Coverage")
        lines.append(f"  Source Files: {cov_data['total_source_files']}")
        lines.append(f"  Test Files: {cov_data['total_test_files']}")
        lines.append(f"  Coverage Ratio: {cov_data['coverage_ratio']:.0%}")
        lines.append(f"  Untested Modules: {cov_data['untested_count']}")
        if cov_data["untested_modules"]:
            lines.append("  Sample untested:")
            for mod in cov_data["untested_modules"][:5]:
                lines.append(f"    - {mod}")
        lines.append("")

    # Documentation
    if "documentation" in report_data["sections"]:
        doc_data = report_data["sections"]["documentation"]
        lines.append("## Documentation")
        lines.append(f"  Total Documentation Files: {doc_data['total_doc_files']}")
        lines.append(f"  ADR System: {'OK' if doc_data['has_adr_system'] else 'MISSING'}")
        if doc_data["missing_required"]:
            lines.append(f"  Missing Required Docs: {', '.join(doc_data['missing_required'])}")
        lines.append("")

    # Dependencies
    if "dependencies" in report_data["sections"]:
        dep_data = report_data["sections"]["dependencies"]
        lines.append("## Dependencies")
        lines.append(f"  Base Dependencies: {dep_data['base_dependencies']}")
        lines.append(f"  Optional Extras: {dep_data['total_extras']}")
        lines.append(f"  Installed Extras: {', '.join(dep_data['installed_extras']) or 'none'}")
        lines.append("")

    # Release Readiness
    if "release_readiness" in report_data["sections"]:
        rel_data = report_data["sections"]["release_readiness"]
        lines.append("## Release Readiness")
        lines.append(f"  Checklist Items: {rel_data.get('checklist_items', 0)}")
        lines.append(f"  Validation Script: {'OK' if rel_data.get('has_validation_script') else 'MISSING'}")
        if rel_data.get("missing_key_files"):
            lines.append(f"  Missing Files: {', '.join(rel_data['missing_key_files'])}")
        lines.append("")

    # Onboarding
    if "onboarding" in report_data["sections"]:
        onb_data = report_data["sections"]["onboarding"]
        lines.append("## Onboarding Recommendations")
        lines.append(f"  System Ready: {'OK' if onb_data['system_ready'] else 'NEEDS_SETUP'}")
        if onb_data["recommendations"]:
            lines.append("  Actions:")
            for rec in onb_data["recommendations"]:
                priority = rec["priority"].upper()
                lines.append(f"    [{priority}] {rec['action']}")
                if "command" in rec:
                    lines.append(f"            $ {rec['command']}")
        lines.append(f"  Quick Start: {onb_data['quick_start_command']}")
        lines.append("")

    # Quick Wins
    if report_data["quick_wins"]:
        lines.append("## Quick Wins (Bob's Recommendations)")
        for i, win in enumerate(report_data["quick_wins"], 1):
            lines.append(f"  {i}. {win['item']}")
            lines.append(f"     Effort: {win['effort']} | Impact: {win['impact']}")
            if "action" in win:
                lines.append(f"     Action: {win['action']}")
        lines.append("")

    lines.append("=" * 80)
    lines.append("Run 'python scripts/bob_accelerator.py --format json' for machine-readable output")
    lines.append("=" * 80)

    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="IBM Bob - Ghost Chimera Delivery Accelerator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--section",
        choices=[
            "system",
            "bob_tools",
            "test_coverage",
            "documentation",
            "dependencies",
            "release_readiness",
            "onboarding",
        ],
        help="Run only specific section",
    )

    args = parser.parse_args()

    report = generate_report(format_type=args.format, section=args.section)
    print(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob
