"""GitHub issue and repository task conversion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GitHubIssue:
    """Issue metadata used to create a Ghost objective."""

    repo: str
    number: int
    title: str
    body: str = ""
    labels: list[str] = field(default_factory=list)
    url: str = ""

    @classmethod
    def from_api(cls, repo: str, payload: dict[str, Any]) -> GitHubIssue:
        return cls(
            repo=repo,
            number=int(payload["number"]),
            title=str(payload.get("title") or ""),
            body=str(payload.get("body") or ""),
            labels=[str(item.get("name") or "") for item in payload.get("labels") or [] if item.get("name")],
            url=str(payload.get("html_url") or ""),
        )


@dataclass(frozen=True)
class GitHubRepoScan:
    """Repository scan result for onboarding and release-gate planning."""

    repo: str
    default_branch: str
    languages: list[str]
    release_commands: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "default_branch": self.default_branch,
            "languages": self.languages,
            "release_commands": self.release_commands,
        }


def issue_to_objective(issue: GitHubIssue) -> str:
    """Convert an issue into an actionable Ghost objective."""

    labels = ", ".join(issue.labels) if issue.labels else "none"
    return "\n".join(
        [
            f"Implement GitHub issue {issue.repo}#{issue.number}: {issue.title}",
            f"Source: {issue.url or issue.repo}",
            f"Labels: {labels}",
            "",
            issue.body.strip(),
            "",
            "Deliver a tested change, run the repository release gates, review the diff, and prepare a pull request.",
        ]
    ).strip()
