"""Analyze plain-text logs for warnings, errors, and repeated messages."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

LEVEL_RE = re.compile(r"\b(CRITICAL|ERROR|WARNING|WARN|INFO|DEBUG)\b", re.IGNORECASE)
LOGGER_RE = re.compile(r"\b(?:logger|name)=([A-Za-z0-9_.-]+)|\b([A-Za-z_][A-Za-z0-9_.-]+):\s")


def analyze_lines(lines: list[str]) -> dict[str, Any]:
    levels: Counter[str] = Counter()
    loggers: Counter[str] = Counter()
    messages: Counter[str] = Counter()
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        level_match = LEVEL_RE.search(line)
        level = level_match.group(1).upper() if level_match else "UNKNOWN"
        if level == "WARN":
            level = "WARNING"
        levels[level] += 1
        logger_match = LOGGER_RE.search(line)
        if logger_match:
            loggers[logger_match.group(1) or logger_match.group(2)] += 1
        cleaned = LEVEL_RE.sub("", line).strip(" -:")
        messages[cleaned] += 1
    repeated = [{"message": msg, "count": count} for msg, count in messages.most_common() if count > 1]
    return {
        "line_count": len([line for line in lines if line.strip()]),
        "levels": dict(levels),
        "top_loggers": [{"logger": name, "count": count} for name, count in loggers.most_common(10)],
        "repeated_messages": repeated[:10],
        "suggestions": suggestions(levels, repeated),
    }


def suggestions(levels: Counter[str], repeated: list[dict[str, Any]]) -> list[str]:
    result = []
    if levels.get("CRITICAL") or levels.get("ERROR"):
        result.append("Investigate ERROR and CRITICAL lines first.")
    if levels.get("WARNING"):
        result.append("Review WARNING lines for degraded behavior.")
    if repeated:
        result.append("Repeated messages may indicate noisy retries or loops.")
    if not result:
        result.append("No obvious log issues detected.")
    return result


def format_text(data: dict[str, Any]) -> str:
    lines = ["Log Analysis", "=" * 40, f"Lines: {data['line_count']}", "Levels:"]
    for level, count in sorted(data["levels"].items()):
        lines.append(f"  {level}: {count}")
    lines.append("Suggestions:")
    for item in data["suggestions"]:
        lines.append(f"  - {item}")
    return "\n".join(lines)


def format_markdown(data: dict[str, Any]) -> str:
    lines = ["# Log Analysis", "", f"- **Lines:** {data['line_count']}", "", "## Levels", ""]
    for level, count in sorted(data["levels"].items()):
        lines.append(f"- **{level}:** {count}")
    lines.extend(["", "## Suggestions", ""])
    for item in data["suggestions"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze plain-text logs")
    parser.add_argument("--input", required=True, help="Log file path")
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    args = parser.parse_args()

    try:
        data = analyze_lines(Path(args.input).read_text(encoding="utf-8").splitlines())
        if args.format == "json":
            print(json.dumps(data, indent=2))
        elif args.format == "markdown":
            print(format_markdown(data))
        else:
            print(format_text(data))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
