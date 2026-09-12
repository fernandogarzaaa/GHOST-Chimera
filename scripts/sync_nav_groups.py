"""Single source of truth for console navigation groups.

``ghostchimera/control_plane/static/nav_groups.json`` defines the Setup /
Connect / Operate / Advanced groups. This script regenerates the
``var TAB_GROUPS`` literal in ``app.js`` from that manifest so the UI and
the contract tests can never drift apart again:

    python scripts/sync_nav_groups.py          # rewrite app.js in place
    python scripts/sync_nav_groups.py --check  # fail if app.js is stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "ghostchimera" / "control_plane" / "static" / "nav_groups.json"
APP_JS = REPO_ROOT / "ghostchimera" / "control_plane" / "static" / "app.js"
LINE_LIMIT = 100


def load_manifest() -> list[dict]:
    """Load and validate the navigation manifest."""

    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read navigation manifest: {exc}") from None
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        raise SystemExit("Navigation manifest must define a non-empty 'groups' list")
    seen_ids: set[str] = set()
    seen_tabs: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise SystemExit(f"Invalid group entry: {group!r}")
        group_id, label, tabs = group.get("id"), group.get("label"), group.get("tabs")
        if not group_id or not label or not isinstance(tabs, list) or not tabs:
            raise SystemExit(f"Group needs id/label/non-empty tabs: {group!r}")
        if group_id in seen_ids:
            raise SystemExit(f"Duplicate group id: {group_id}")
        seen_ids.add(group_id)
        for tab in tabs:
            if not tab or tab in seen_tabs:
                raise SystemExit(f"Duplicate or empty tab: {tab!r}")
            seen_tabs.add(tab)
    return groups


def render_literal(groups: list[dict]) -> str:
    """Render the ``var TAB_GROUPS`` block deterministically."""

    lines = ["  var TAB_GROUPS = ["]
    for group in groups:
        quoted = [f'"{tab}"' for tab in group["tabs"]]
        head = f'["{group["id"]}", "{group["label"]}", ['
        body_lines: list[str] = []
        current = "    " + head
        for tab in quoted:
            joiner = "" if current.rstrip().endswith("[") else ", "
            if len(current + joiner + tab + "]],") <= LINE_LIMIT:
                current += joiner + tab
            else:
                body_lines.append(current + ",")
                current = "      " + tab
        body_lines.append(current + "]],")
        lines.extend(body_lines)
    lines.append("  ];")
    return "\n".join(lines)


def sync(*, check: bool) -> int:
    """Rewrite (or verify) the TAB_GROUPS literal in app.js."""

    groups = load_manifest()
    rendered = render_literal(groups)
    javascript = APP_JS.read_text(encoding="utf-8")
    pattern = re.compile(r"  var TAB_GROUPS = \[.*?\n  \];", re.DOTALL)
    match = pattern.search(javascript)
    if match is None:
        raise SystemExit("TAB_GROUPS declaration not found in app.js")
    if match.group(0) == rendered:
        print("app.js navigation groups are in sync.")
        return 0
    if check:
        print("app.js navigation groups are stale; run python scripts/sync_nav_groups.py")
        return 1
    APP_JS.write_text(javascript[: match.start()] + rendered + javascript[match.end() :], encoding="utf-8")
    print("app.js navigation groups synchronized.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the navigation sync script."""

    parser = argparse.ArgumentParser(description="Sync app.js navigation groups from nav_groups.json")
    parser.add_argument("--check", action="store_true", help="Fail if app.js is stale instead of rewriting it")
    args = parser.parse_args(argv)
    return sync(check=args.check)


if __name__ == "__main__":
    sys.exit(main())
