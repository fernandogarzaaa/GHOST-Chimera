"""Generate a simple AST-based module dependency graph."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def module_name(path: Path, package: Path) -> str:
    return ".".join(path.resolve().relative_to(package.resolve().parent).with_suffix("").parts)


def imports_for_module(path: Path, package_name: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == package_name or alias.name.startswith(f"{package_name}."):
                    imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                imports.add("." * node.level + (node.module or ""))
            elif node.module and (node.module == package_name or node.module.startswith(f"{package_name}.")):
                imports.add(node.module)
    return sorted(imports)


def build_graph(package: Path) -> dict[str, Any]:
    if not package.exists():
        raise FileNotFoundError(f"Package not found: {package}")
    package_name = package.name
    modules = {}
    for path in sorted(package.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        modules[module_name(path, package)] = imports_for_module(path, package_name)
    return {"package": package_name, "module_count": len(modules), "modules": modules}


def format_markdown(graph: dict[str, Any]) -> str:
    lines = ["# Dependency Graph", "", f"Package: `{graph['package']}`", f"Modules: {graph['module_count']}", ""]
    for module, imports in graph["modules"].items():
        lines.append(f"## `{module}`")
        if imports:
            for item in imports:
                lines.append(f"- `{item}`")
        else:
            lines.append("- No internal imports")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate package dependency graph")
    parser.add_argument("--package", default=str(ROOT / "ghostchimera"))
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    try:
        graph = build_graph(Path(args.package))
        output = json.dumps(graph, indent=2) if args.format == "json" else format_markdown(graph)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"Dependency graph written to {args.output}")
        else:
            print(output)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
