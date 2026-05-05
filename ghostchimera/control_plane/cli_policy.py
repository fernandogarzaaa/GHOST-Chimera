"""Policy management CLI subcommands."""

from __future__ import annotations

import argparse
import json
import sys

from ..safety_layer.material_policy import MaterialRegistry


def _cmd_policy_list() -> None:
    registry = MaterialRegistry()
    for p in registry.patterns:
        constraints = p.get("constraints", {})
        print(f"  {p['id']}")
        print(f"    {p['description']}")
        print(f"    min_confidence: {constraints.get('min_confidence', 0.0)}")
        print()


def _cmd_policy_scan(text: str, policy: str = "strict_factual") -> None:
    registry = MaterialRegistry()
    result = registry.check_security(text, policy)
    print(json.dumps(result, indent=2))


def _cmd_policy_set(task_type: str) -> None:
    recommendations = {
        "coding": "code_review",
        "research": "research_factcheck",
        "medical": "medical_cautious",
        "security": "mcp_security",
        "creative": "brainstorm",
        "general": "strict_factual",
    }
    policy = recommendations.get(task_type, "strict_factual")
    print(f"Recommended policy for '{task_type}': {policy}")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Policy management")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all policy patterns")

    scan_p = sub.add_parser("scan", help="Scan text against a policy")
    scan_p.add_argument("text", help="Text to scan")
    scan_p.add_argument("--policy", default="strict_factual")

    set_p = sub.add_parser("set", help="Set policy for task type")
    set_p.add_argument("task_type", choices=["coding", "research", "medical", "security", "creative", "general"])

    args = parser.parse_args(argv)

    if args.command == "list":
        _cmd_policy_list()
    elif args.command == "scan":
        _cmd_policy_scan(args.text, args.policy)
    elif args.command == "set":
        _cmd_policy_set(args.task_type)
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
