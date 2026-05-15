"""
Automated Changelog Generator for Ghost Chimera.

Parses git history and generates categorized changelogs in markdown or JSON format.
Part of IBM Bob Phase 1: Developer Tools.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def parse_commit_line(line: str) -> dict[str, str]:
    """
    Parse a git log line into commit hash and subject.
    
    Expected format: "abc1234 commit subject here"
    """
    parts = line.split(" ", 1)
    if len(parts) == 2:
        return {"sha": parts[0], "subject": parts[1]}
    return {"sha": "", "subject": line}


def categorize_commit(subject: str) -> str:
    """
    Categorize a commit based on conventional commit prefixes or keywords.
    
    Categories:
    - Features: feat:, feature:, add, implement, new
    - Fixes: fix:, bugfix:, bug, patch, resolve
    - Tests: test:, tests:, testing
    - Docs: docs:, doc:, documentation, readme
    - Chores: chore:, ci:, build:, deps:, dependency, dependencies
    - Other: everything else
    """
    subject_lower = subject.lower()
    
    # Conventional commit prefixes
    if subject_lower.startswith(("feat:", "feat(", "feature:")):
        return "Features"
    if subject_lower.startswith(("fix:", "fix(", "bugfix:")):
        return "Fixes"
    if subject_lower.startswith(("test:", "test(", "tests:")):
        return "Tests"
    if subject_lower.startswith(("docs:", "docs(", "doc:")):
        return "Docs"
    if subject_lower.startswith(("chore:", "chore(", "ci:", "ci(", "build:", "build(", "refactor:", "refactor(")):
        return "Chores"
    
    # Keyword-based categorization
    if any(word in subject_lower for word in ["add", "implement", "new", "feature"]):
        return "Features"
    if any(word in subject_lower for word in ["fix", "bug", "patch", "resolve"]):
        return "Fixes"
    if any(word in subject_lower for word in ["test", "testing"]):
        return "Tests"
    if any(word in subject_lower for word in ["doc", "documentation", "readme"]):
        return "Docs"
    if any(word in subject_lower for word in ["chore", "deps", "dependency", "dependencies", "ci", "build"]):
        return "Chores"
    
    return "Other"


def _looks_like_date_or_time_window(value: str) -> bool:
    """Return True when a --since value is likely meant for git's date parser."""
    lowered = value.strip().lower()
    if not lowered:
        return False
    if any(word in lowered for word in ("ago", "yesterday", "today", "last ")):
        return True
    if len(lowered) >= 8 and lowered[0].isdigit() and "-" in lowered:
        return True
    return False


def build_git_log_command(since: str | None = None, max_count: int | None = None) -> list[str]:
    """
    Build a git log command for changelog generation.

    ``--since`` accepts either a date/time window understood by git or a ref/range
    such as ``v0.2.0`` or ``HEAD~10``. Ref-like values are converted into a
    ``ref..HEAD`` range so release tags behave as users expect.
    """
    cmd = ["git", "log", "--oneline"]

    if since:
        if ".." in since:
            cmd.append(since)
        elif _looks_like_date_or_time_window(since):
            cmd.append(f"--since={since}")
        else:
            cmd.append(f"{since}..HEAD")

    if max_count:
        cmd.extend(["--max-count", str(max_count)])

    return cmd


def get_git_log(since: str | None = None, max_count: int | None = None) -> list[str]:
    """
    Get git log output using subprocess.
    
    Args:
        since: Git ref to start from (e.g., "v0.2.0", "HEAD~10")
        max_count: Maximum number of commits to retrieve
    
    Returns:
        List of commit lines in format "sha subject"
    """
    cmd = build_git_log_command(since=since, max_count=max_count)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT
        )
        return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
    except subprocess.CalledProcessError as e:
        print(f"Error running git log: {e}", file=sys.stderr)
        print(f"Command: {' '.join(cmd)}", file=sys.stderr)
        return []
    except FileNotFoundError:
        print("Error: git command not found", file=sys.stderr)
        return []


def generate_changelog_data(
    since: str | None = None,
    max_count: int | None = None
) -> dict[str, list[dict[str, str]]]:
    """
    Generate changelog data structure from git history.
    
    Returns:
        Dictionary mapping categories to lists of commits
    """
    commits = get_git_log(since=since, max_count=max_count)
    
    changelog: dict[str, list[dict[str, str]]] = {
        "Features": [],
        "Fixes": [],
        "Tests": [],
        "Docs": [],
        "Chores": [],
        "Other": []
    }
    
    for commit_line in commits:
        commit = parse_commit_line(commit_line)
        if commit["sha"]:
            category = categorize_commit(commit["subject"])
            changelog[category].append(commit)
    
    return changelog


def format_markdown(changelog: dict[str, list[dict[str, str]]]) -> str:
    """Format changelog as markdown."""
    lines = ["# Changelog", ""]
    
    for category in ["Features", "Fixes", "Tests", "Docs", "Chores", "Other"]:
        commits = changelog.get(category, [])
        if commits:
            lines.append(f"## {category}")
            lines.append("")
            for commit in commits:
                lines.append(f"- {commit['subject']} ({commit['sha']})")
            lines.append("")
    
    return "\n".join(lines)


def format_json(changelog: dict[str, list[dict[str, str]]]) -> str:
    """Format changelog as JSON."""
    return json.dumps(changelog, indent=2)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate changelog from git history",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate changelog for last 10 commits
  python scripts/generate_changelog.py --max-count 10
  
  # Generate changelog since a tag
  python scripts/generate_changelog.py --since v0.2.0
  
  # Generate changelog and save to file
  python scripts/generate_changelog.py --max-count 20 --output CHANGELOG_DRAFT.md
  
  # Generate JSON format
  python scripts/generate_changelog.py --max-count 10 --format json
        """
    )
    
    parser.add_argument(
        "--since",
        help="Git ref to start from (e.g., v0.2.0, HEAD~10)"
    )
    parser.add_argument(
        "--max-count",
        type=int,
        help="Maximum number of commits to include"
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout)"
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)"
    )
    
    args = parser.parse_args()
    
    # Generate changelog data
    changelog = generate_changelog_data(since=args.since, max_count=args.max_count)
    
    # Format output
    if args.format == "json":
        output = format_json(changelog)
    else:
        output = format_markdown(changelog)
    
    # Write or print output
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(output, encoding="utf-8")
        print(f"Changelog written to {args.output}")
    else:
        print(output)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob
