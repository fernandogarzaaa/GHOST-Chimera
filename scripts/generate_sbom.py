"""Generate an SBOM-lite report from pyproject.toml."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


def parse_pyproject(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"pyproject.toml not found: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _dependency_name(spec: str) -> str:
    match = NAME_RE.match(spec.split(";", 1)[0].split("[", 1)[0])
    return match.group(1) if match else spec


def build_sbom(pyproject: dict[str, Any]) -> dict[str, Any]:
    project = pyproject.get("project", {})
    components = []
    for spec in project.get("dependencies", []):
        components.append({"name": _dependency_name(spec), "spec": spec, "scope": "runtime"})
    for extra, specs in project.get("optional-dependencies", {}).items():
        for spec in specs:
            components.append({"name": _dependency_name(spec), "spec": spec, "scope": f"optional:{extra}"})
    return {
        "type": "sbom-lite",
        "project": {"name": project.get("name", "unknown"), "version": project.get("version", "unknown")},
        "component_count": len(components),
        "components": components,
        "limitations": [
            "Generated from declared dependency specifications only.",
            "Does not resolve transitive dependencies.",
            "Does not perform vulnerability scanning.",
        ],
    }


def format_markdown(sbom: dict[str, Any]) -> str:
    lines = [
        "# SBOM-lite",
        "",
        f"Project: `{sbom['project']['name']}`",
        f"Version: `{sbom['project']['version']}`",
        f"Components: {sbom['component_count']}",
        "",
        "## Components",
        "",
    ]
    for component in sbom["components"]:
        lines.append(f"- `{component['name']}` ({component['scope']}): `{component['spec']}`")
    lines.extend(["", "## Limitations", ""])
    for item in sbom["limitations"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SBOM-lite from pyproject.toml")
    parser.add_argument("--pyproject", default=str(ROOT / "pyproject.toml"))
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    try:
        sbom = build_sbom(parse_pyproject(Path(args.pyproject)))
        output = format_markdown(sbom) if args.format == "markdown" else json.dumps(sbom, indent=2)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"SBOM-lite written to {args.output}")
        else:
            print(output)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
