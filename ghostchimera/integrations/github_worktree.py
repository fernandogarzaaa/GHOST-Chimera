"""Git worktree planning for GitHub-connected tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-").lower()


@dataclass(frozen=True)
class GitHubWorktreePlan:
    """A command plan for creating an isolated task worktree."""

    repo_root: Path
    path: Path
    branch: str
    base_branch: str
    commands: list[str]

    @classmethod
    def create(cls, *, repo_root: Path, repo: str, issue_number: int, base_branch: str) -> GitHubWorktreePlan:
        repo_name = _slug(repo.split("/")[-1])
        branch = f"codex/github-{issue_number}"
        path = repo_root.resolve().parent / f"{repo_name}-github-{issue_number}"
        commands = [
            "git fetch origin",
            f"git worktree add {path} -b {branch} origin/{base_branch}",
        ]
        return cls(repo_root=repo_root.resolve(), path=path, branch=branch, base_branch=base_branch, commands=commands)

    def to_dict(self) -> dict[str, str | list[str]]:
        return {
            "repo_root": str(self.repo_root),
            "path": str(self.path),
            "branch": self.branch,
            "base_branch": self.base_branch,
            "commands": self.commands,
        }
