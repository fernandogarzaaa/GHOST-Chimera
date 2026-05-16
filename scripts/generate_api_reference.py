"""Generate markdown API reference docs from Python source using AST."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _public(name: str) -> bool:
    return not name.startswith("_")


def _first_sentence(node: ast.AST) -> str:
    doc = ast.get_docstring(node) or ""
    if not doc:
        return ""
    return _ascii(doc.strip().splitlines()[0].strip())


def _ascii(value: str) -> str:
    """Keep generated docs ASCII-friendly for cross-platform diffs."""
    return value.encode("ascii", "replace").decode("ascii")


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [arg.arg for arg in node.args.posonlyargs + node.args.args]
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    args.extend(arg.arg for arg in node.args.kwonlyargs)
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
    return f"{node.name}({', '.join(args)})"


def analyze_module(path: Path, package_root: Path) -> dict[str, Any]:
    """Analyze one Python module without importing it."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.resolve().relative_to(package_root.resolve().parent).with_suffix("")
    module = ".".join(rel.parts)
    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    function_nodes = (ast.FunctionDef, ast.AsyncFunctionDef)

    for node in tree.body:
        if isinstance(node, function_nodes) and _public(node.name):
            functions.append(
                {
                    "name": node.name,
                    "signature": _signature(node),
                    "doc": _first_sentence(node),
                    "line": node.lineno,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                }
            )
        elif isinstance(node, ast.ClassDef) and _public(node.name):
            methods = []
            for item in node.body:
                if isinstance(item, function_nodes) and (_public(item.name) or item.name == "__init__"):
                    methods.append(
                        {
                            "name": item.name,
                            "signature": _signature(item),
                            "doc": _first_sentence(item),
                            "line": item.lineno,
                            "async": isinstance(item, ast.AsyncFunctionDef),
                        }
                    )
            classes.append({"name": node.name, "doc": _first_sentence(node), "line": node.lineno, "methods": methods})

    return {"module": module, "path": str(path), "functions": functions, "classes": classes}


def collect_api(package: Path, max_modules: int | None = None) -> list[dict[str, Any]]:
    """Collect public API metadata for a package path."""
    if not package.exists() or not package.is_dir():
        raise FileNotFoundError(f"Package directory not found: {package}")

    modules = [p for p in sorted(package.rglob("*.py")) if "__pycache__" not in p.parts]
    if max_modules is not None:
        modules = modules[:max_modules]
    return [analyze_module(path, package) for path in modules]


def format_markdown(api: list[dict[str, Any]]) -> str:
    """Format API metadata as markdown."""
    lines = ["# API Reference", "", "Generated from source using AST. Modules are not imported.", ""]
    for module in api:
        if not module["functions"] and not module["classes"]:
            continue
        lines.append(f"## `{module['module']}`")
        lines.append("")
        if module["functions"]:
            lines.append("### Functions")
            lines.append("")
            for func in module["functions"]:
                lines.append(f"- `{func['signature']}`")
                if func["doc"]:
                    lines.append(f"  - {func['doc']}")
            lines.append("")
        if module["classes"]:
            lines.append("### Classes")
            lines.append("")
            for cls in module["classes"]:
                lines.append(f"- `{cls['name']}`")
                if cls["doc"]:
                    lines.append(f"  - {cls['doc']}")
                for method in cls["methods"]:
                    lines.append(f"  - `{method['signature']}`")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate markdown API reference from Python source")
    parser.add_argument("--package", default=str(ROOT / "ghostchimera"), help="Package directory to analyze")
    parser.add_argument("--output", default=str(ROOT / "docs" / "api-reference.md"), help="Markdown output path")
    parser.add_argument("--max-modules", type=int, default=None, help="Limit modules for quick previews")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    try:
        api = collect_api(Path(args.package), max_modules=args.max_modules)
        output = json.dumps(api, indent=2) if args.format == "json" else format_markdown(api)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"API reference written to {args.output}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
