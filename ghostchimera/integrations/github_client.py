"""GitHub API and gh CLI integration for local beta workflows."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"


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


@dataclass(frozen=True)
class GitHubDeviceCode:
    """Device-flow code bundle returned by GitHub without exposing a token."""

    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_code": self.device_code,
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "expires_in": self.expires_in,
            "interval": self.interval,
        }


def github_oauth_client_id() -> str:
    """Return the optional GitHub OAuth client id for console sign-in."""

    return os.environ.get("GHOSTCHIMERA_GITHUB_CLIENT_ID") or os.environ.get("GITHUB_CLIENT_ID") or ""


def _post_form_json(url: str, payload: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "ghostchimera-github-console",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise RuntimeError("GitHub returned a non-object response")
    return data


def start_device_flow(*, client_id: str, scope: str = "read:user repo") -> GitHubDeviceCode:
    """Start GitHub OAuth device flow for the local console."""

    data = _post_form_json(GITHUB_DEVICE_CODE_URL, {"client_id": client_id, "scope": scope})
    if "error" in data:
        raise RuntimeError(str(data.get("error_description") or data.get("error")))
    return GitHubDeviceCode(
        device_code=str(data["device_code"]),
        user_code=str(data["user_code"]),
        verification_uri=str(data.get("verification_uri") or "https://github.com/login/device"),
        expires_in=int(data.get("expires_in") or 900),
        interval=int(data.get("interval") or 5),
    )


def poll_device_flow(*, client_id: str, device_code: str) -> dict[str, Any]:
    """Poll GitHub OAuth device flow and return GitHub's token-state response."""

    return _post_form_json(
        GITHUB_ACCESS_TOKEN_URL,
        {
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
    )


def fetch_authenticated_user(token: str) -> dict[str, Any]:
    """Return the authenticated GitHub user for a token."""

    request = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ghostchimera-github-console",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8") or "{}")
    if not isinstance(data, dict):
        raise RuntimeError("GitHub returned a non-object user response")
    return data


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
