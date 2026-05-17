"""
Dependency Audit Tool for Ghost Chimera.

Analyzes pyproject.toml dependencies and provides specification audit report.
Part of IBM Bob Phase 1: Developer Tools.
"""

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


VERSION_OPERATOR_RE = re.compile(r"(===|==|~=|!=|<=|>=|<|>)\s*([A-Za-z0-9.*!+_-]+)")
PRE_RELEASE_RE = re.compile(r"(?:a|alpha|b|beta|rc|dev)\d*(?:[.\-+_]|$)", re.IGNORECASE)


def _requirement_part(dep_spec: str) -> str:
    """Return the package requirement before any environment marker."""
    return dep_spec.split(";", 1)[0].strip()


def _has_version_constraint(requirement: str) -> bool:
    """Return True when a requirement contains a version operator or direct reference."""
    return bool(VERSION_OPERATOR_RE.search(requirement) or re.search(r"\s@\s", requirement))


def _has_prerelease_version(requirement: str) -> bool:
    """Detect prerelease markers in version tokens, not package names."""
    return any(PRE_RELEASE_RE.search(version) for _operator, version in VERSION_OPERATOR_RE.findall(requirement))


def parse_pyproject(pyproject_path: Path) -> dict[str, Any]:
    """
    Parse pyproject.toml file.

    Args:
        pyproject_path: Path to pyproject.toml

    Returns:
        Parsed TOML data
    """
    if not pyproject_path.exists():
        raise FileNotFoundError(f"pyproject.toml not found: {pyproject_path}")

    try:
        with open(pyproject_path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        raise ValueError(f"Error parsing pyproject.toml: {e}") from e


def analyze_dependency_spec(dep_spec: str) -> dict[str, Any]:
    """
    Analyze a dependency specification for risks.

    Args:
        dep_spec: Dependency specification (e.g., "package>=1.0.0")

    Returns:
        Analysis results
    """
    analysis = {"spec": dep_spec, "risks": [], "notes": []}
    requirement = _requirement_part(dep_spec)

    # Check for unpinned dependencies
    if ">=" in requirement and "," not in requirement and "<" not in requirement:
        analysis["risks"].append("Unpinned upper bound (>=)")
        analysis["notes"].append("Consider adding upper bound for stability")

    # Check for very broad ranges
    if requirement.startswith("*") or requirement == "" or not _has_version_constraint(requirement):
        analysis["risks"].append("No version constraint")
        analysis["notes"].append("Specify version range for reproducibility")

    # Check for pre-release versions
    if _has_prerelease_version(requirement):
        analysis["risks"].append("Pre-release version")
        analysis["notes"].append("Pre-release versions may be unstable")

    # Check for direct reference dependencies
    if "git+" in requirement:
        analysis["risks"].append("Git dependency")
        analysis["notes"].append("Git dependencies may not be reproducible")
    elif re.search(r"\s@\s", requirement):
        analysis["risks"].append("Direct reference dependency")
        analysis["notes"].append("Direct references may be harder to reproduce than index versions")

    return analysis


def audit_dependencies(pyproject_data: dict[str, Any]) -> dict[str, Any]:
    """
    Audit dependencies from pyproject.toml.

    Args:
        pyproject_data: Parsed pyproject.toml data

    Returns:
        Audit results
    """
    results = {
        "base_dependencies": [],
        "optional_extras": {},
        "dev_dependencies": [],
        "risk_summary": {"total_dependencies": 0, "dependencies_with_risks": 0, "common_risks": []},
    }

    # Extract base dependencies
    project = pyproject_data.get("project", {})
    base_deps = project.get("dependencies", [])

    for dep in base_deps:
        analysis = analyze_dependency_spec(dep)
        results["base_dependencies"].append(analysis)
        results["risk_summary"]["total_dependencies"] += 1
        if analysis["risks"]:
            results["risk_summary"]["dependencies_with_risks"] += 1

    # Extract optional dependencies
    optional_deps = project.get("optional-dependencies", {})
    for extra_name, deps in optional_deps.items():
        results["optional_extras"][extra_name] = []
        for dep in deps:
            analysis = analyze_dependency_spec(dep)
            results["optional_extras"][extra_name].append(analysis)
            results["risk_summary"]["total_dependencies"] += 1
            if analysis["risks"]:
                results["risk_summary"]["dependencies_with_risks"] += 1

    # Check for expected extras
    expected_extras = ["dev", "gateway", "mcp"]
    missing_extras = [extra for extra in expected_extras if extra not in optional_deps]
    if missing_extras:
        results["risk_summary"]["missing_expected_extras"] = missing_extras

    # Collect common risks
    all_risks = []
    for dep in results["base_dependencies"]:
        all_risks.extend(dep["risks"])
    for extra_deps in results["optional_extras"].values():
        for dep in extra_deps:
            all_risks.extend(dep["risks"])

    # Count risk occurrences
    risk_counts = {}
    for risk in all_risks:
        risk_counts[risk] = risk_counts.get(risk, 0) + 1

    # Sort by frequency
    results["risk_summary"]["common_risks"] = [
        {"risk": risk, "count": count} for risk, count in sorted(risk_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    return results


def format_text(results: dict[str, Any]) -> str:
    """Format audit results as text."""
    lines = ["Ghost Chimera Dependency Specification Audit", "=" * 50, ""]

    # Summary
    lines.append("Summary:")
    lines.append(f"  Total dependencies: {results['risk_summary']['total_dependencies']}")
    lines.append(f"  Dependencies with risks: {results['risk_summary']['dependencies_with_risks']}")
    lines.append("")

    # Base dependencies
    if results["base_dependencies"]:
        lines.append("Base Dependencies:")
        lines.append("-" * 50)
        for dep in results["base_dependencies"]:
            risk_marker = " [RISK]" if dep["risks"] else ""
            lines.append(f"  {dep['spec']}{risk_marker}")
            for risk in dep["risks"]:
                lines.append(f"    - {risk}")
        lines.append("")

    # Optional extras
    if results["optional_extras"]:
        lines.append("Optional Extras:")
        lines.append("-" * 50)
        for extra_name, deps in results["optional_extras"].items():
            lines.append(f"  [{extra_name}]")
            for dep in deps:
                risk_marker = " [RISK]" if dep["risks"] else ""
                lines.append(f"    {dep['spec']}{risk_marker}")
                for risk in dep["risks"]:
                    lines.append(f"      - {risk}")
        lines.append("")

    # Missing expected extras
    if "missing_expected_extras" in results["risk_summary"]:
        lines.append("Missing Expected Extras:")
        for extra in results["risk_summary"]["missing_expected_extras"]:
            lines.append(f"  - {extra}")
        lines.append("")

    # Common risks
    if results["risk_summary"]["common_risks"]:
        lines.append("Common Risks:")
        lines.append("-" * 50)
        for risk_info in results["risk_summary"]["common_risks"]:
            lines.append(f"  {risk_info['risk']}: {risk_info['count']} occurrences")
        lines.append("")

    # Disclaimer
    lines.append("Note: This is a dependency specification audit, not a vulnerability scan.")
    lines.append("For vulnerability scanning, use tools like pip-audit or safety.")

    return "\n".join(lines)


def format_markdown(results: dict[str, Any]) -> str:
    """Format audit results as markdown."""
    lines = ["# Ghost Chimera Dependency Specification Audit", ""]

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total dependencies:** {results['risk_summary']['total_dependencies']}")
    lines.append(f"- **Dependencies with risks:** {results['risk_summary']['dependencies_with_risks']}")
    lines.append("")

    # Base dependencies
    if results["base_dependencies"]:
        lines.append("## Base Dependencies")
        lines.append("")
        for dep in results["base_dependencies"]:
            risk_marker = " :warning:" if dep["risks"] else ""
            lines.append(f"- `{dep['spec']}`{risk_marker}")
            for risk in dep["risks"]:
                lines.append(f"  - {risk}")
        lines.append("")

    # Optional extras
    if results["optional_extras"]:
        lines.append("## Optional Extras")
        lines.append("")
        for extra_name, deps in results["optional_extras"].items():
            lines.append(f"### [{extra_name}]")
            lines.append("")
            for dep in deps:
                risk_marker = " :warning:" if dep["risks"] else ""
                lines.append(f"- `{dep['spec']}`{risk_marker}")
                for risk in dep["risks"]:
                    lines.append(f"  - {risk}")
            lines.append("")

    # Missing expected extras
    if "missing_expected_extras" in results["risk_summary"]:
        lines.append("## Missing Expected Extras")
        lines.append("")
        for extra in results["risk_summary"]["missing_expected_extras"]:
            lines.append(f"- `{extra}`")
        lines.append("")

    # Common risks
    if results["risk_summary"]["common_risks"]:
        lines.append("## Common Risks")
        lines.append("")
        for risk_info in results["risk_summary"]["common_risks"]:
            lines.append(f"- **{risk_info['risk']}:** {risk_info['count']} occurrences")
        lines.append("")

    # Disclaimer
    lines.append("---")
    lines.append("")
    lines.append("**Note:** This is a dependency specification audit, not a vulnerability scan.")
    lines.append("For vulnerability scanning, use tools like `pip-audit` or `safety`.")

    return "\n".join(lines)


def format_json_output(results: dict[str, Any]) -> str:
    """Format audit results as JSON."""
    return json.dumps(results, indent=2)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Audit Ghost Chimera dependencies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Audit current project dependencies
  python scripts/audit_dependencies.py

  # Audit specific pyproject.toml
  python scripts/audit_dependencies.py --pyproject /path/to/pyproject.toml

  # Output as markdown
  python scripts/audit_dependencies.py --format markdown

  # Save to file
  python scripts/audit_dependencies.py --format markdown --output docs/dependency_audit.md
        """,
    )

    parser.add_argument(
        "--format", choices=["text", "markdown", "json"], default="text", help="Output format (default: text)"
    )
    parser.add_argument("--pyproject", help="Path to pyproject.toml (default: ./pyproject.toml)")
    parser.add_argument("--output", help="Output file path (default: stdout)")

    args = parser.parse_args()

    # Determine pyproject.toml path
    pyproject_path = Path(args.pyproject) if args.pyproject else ROOT / "pyproject.toml"

    # Parse and audit
    try:
        pyproject_data = parse_pyproject(pyproject_path)
        results = audit_dependencies(pyproject_data)

        # Format output
        if args.format == "json":
            output = format_json_output(results)
        elif args.format == "markdown":
            output = format_markdown(results)
        else:
            output = format_text(results)

        # Write or print output
        if args.output:
            output_path = Path(args.output)
            output_path.write_text(output, encoding="utf-8")
            print(f"Dependency audit written to {args.output}")
        else:
            print(output)

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob
