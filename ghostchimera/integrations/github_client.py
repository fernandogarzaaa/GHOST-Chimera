"""GitHub API and gh CLI integration for local beta workflows."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GitHubAuth:
    """Resolved GitHub auth mode for the local runner."""

    mode: str
    token: str = ""

    @classmethod
    def discover(cls) -> GitHubAuth:
        token = os.environ.get("GHOSTCHIMERA_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        if token:
            return cls(mode="token", token=token)
        return cls(mode="gh-cli")


class GitHubClient:
    """Small stdlib GitHub client with gh CLI fallback."""

    def __init__(self, *, auth: GitHubAuth | None = None, api_base: str = "https://api.github.com") -> None:
        self.auth = auth or GitHubAuth.discover()
        self.api_base = api_base.rstrip("/")

    def __repr__(self) -> str:
        return f"GitHubClient(mode={self.auth.mode!r}, api_base={self.api_base!r})"

    def headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ghostchimera-github-connected-beta",
        }
        if self.auth.token:
            headers["Authorization"] = f"Bearer {self.auth.token}"
        return headers

    def get_json(self, path: str) -> dict[str, Any] | list[Any]:
        if self.auth.mode == "gh-cli" and not self.auth.token:
            return self._gh_api(path)
        request = urllib.request.Request(f"{self.api_base}/{path.lstrip('/')}", headers=self.headers(), method="GET")
        return self._open_json(request)

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | list[Any]:
        if self.auth.mode == "gh-cli" and not self.auth.token:
            args = ["gh", "api", path, "-X", "POST"]
            for key, value in payload.items():
                args.extend(["-f", f"{key}={value}"])
            return self._run_gh(args)
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_base}/{path.lstrip('/')}",
            data=body,
            headers={**self.headers(), "Content-Type": "application/json"},
            method="POST",
        )
        return self._open_json(request)

    def post_issue_comment(self, repo: str, number: int, body: str) -> dict[str, Any] | list[Any]:
        return self.post_json(f"repos/{repo}/issues/{number}/comments", {"body": body})

    def _open_json(self, request: urllib.request.Request) -> dict[str, Any] | list[Any]:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API failed with HTTP {exc.code}: {body}") from exc
        return json.loads(raw or "{}")

    def _gh_api(self, path: str) -> dict[str, Any] | list[Any]:
        return self._run_gh(["gh", "api", path])

    @staticmethod
    def _run_gh(args: list[str]) -> dict[str, Any] | list[Any]:
        completed = subprocess.run(args, text=True, capture_output=True, check=False, timeout=30)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "gh api failed").strip())
        return json.loads(completed.stdout or "{}")
