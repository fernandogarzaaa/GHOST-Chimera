"""Print local development environment setup commands by profile."""

from __future__ import annotations

import argparse
import json
from typing import Any

PROFILES: dict[str, dict[str, Any]] = {
    "minimal": {"extras": "", "commands": ["python -m pip install -e ."]},
    "dev": {"extras": "dev", "commands": ["python -m pip install -e .[dev]", "python -m pytest tests/ -q"]},
    "gateway": {"extras": "dev,gateway", "commands": ["python -m pip install -e .[dev,gateway]"]},
    "mcp": {"extras": "dev,mcp", "commands": ["python -m pip install -e .[dev,mcp]"]},
    "full": {
        "extras": "dev,gateway,mcp,local,minimind",
        "commands": ["python -m pip install -e .[dev,gateway,mcp,local,minimind]"],
    },
}


def profile_data(profile: str) -> dict[str, Any]:
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile: {profile}")
    data = dict(PROFILES[profile])
    data["profile"] = profile
    data["note"] = "Commands are printed only; this script does not install anything."
    return data


def format_text(data: dict[str, Any]) -> str:
    lines = [f"Profile: {data['profile']}", data["note"], "Commands:"]
    for command in data["commands"]:
        lines.append(f"  {command}")
    return "\n".join(lines)


def format_markdown(data: dict[str, Any]) -> str:
    lines = [f"# Dev Environment: {data['profile']}", "", data["note"], "", "## Commands", ""]
    for command in data["commands"]:
        lines.append(f"- `{command}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Print Ghost Chimera dev environment commands")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="dev")
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    args = parser.parse_args()

    data = profile_data(args.profile)
    if args.format == "json":
        print(json.dumps(data, indent=2))
    elif args.format == "markdown":
        print(format_markdown(data))
    else:
        print(format_text(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
