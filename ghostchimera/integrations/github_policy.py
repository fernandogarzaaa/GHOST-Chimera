"""Policy simulation for GitHub-connected autonomous actions."""

from __future__ import annotations

from typing import Any


def simulate_github_action_policy(action: dict[str, Any], controls: dict[str, Any]) -> dict[str, Any]:
    """Return required controls before a GitHub action may run."""

    required: list[str] = []
    name = str(action.get("action") or "")
    if name in {"push_branch", "open_pr", "post_review"} and not controls.get("allow_push"):
        required.append("allow_push")
    if name in {"read_private_repo", "scan_org"} and not controls.get("allow_private_repo_read"):
        required.append("allow_private_repo_read")
    if action.get("autonomous") and not controls.get("allow_autonomy"):
        required.append("allow_autonomy")
    if action.get("admin") and not controls.get("admin_controls"):
        required.append("admin_controls")
    return {
        "allowed": not required,
        "required_controls": required,
        "action": name,
    }
