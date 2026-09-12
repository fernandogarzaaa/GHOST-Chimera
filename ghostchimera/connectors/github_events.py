"""GitHub event connector: repo activity -> github.* Ghost events.

Two ingestion paths, one normalizer family:
- poll: incremental REST polling (issues / pulls / commits) with an
  injectable fetcher so tests never touch the network. Production use
  reuses integrations.GitHubClient (token / gh CLI auth discovery).
- webhook: normalize_github_webhook() maps push / issues / pull_request
  deliveries (verified upstream) to the same event shapes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..stealth.events import Event, new_event
from .base import Connector, ConnectorStatus

Fetcher = Callable[[str], Any]


def _github_client_fetcher(client: Any) -> Fetcher:
    def fetch(path: str) -> Any:
        return client.get_json(path)

    return fetch


class GitHubEventConnector(Connector):
    id = "github"

    def __init__(self, repo: str, *, fetcher: Fetcher | None = None, state: dict[str, Any] | None = None) -> None:
        super().__init__(id="github")
        self.repo = repo
        self._fetcher = fetcher
        self._state = state if state is not None else {"since": None, "known": set()}

    def authenticate(self) -> dict[str, Any]:
        if self._fetcher is not None:
            return {"connector": "github", "authenticated": True, "mode": "injected"}
        try:
            from ..integrations.github_client import GitHubAuth

            auth = GitHubAuth.discover()
            return {"connector": "github", "authenticated": bool(auth.token), "mode": getattr(auth, "mode", "unknown")}
        except Exception as exc:
            return {"connector": "github", "authenticated": False, "error": str(exc)[:120]}

    def connect(self) -> bool:
        if self._fetcher is None:
            try:
                from ..integrations.github_client import GitHubAuth, GitHubClient

                self._fetcher = _github_client_fetcher(GitHubClient(auth=GitHubAuth.discover()))
            except Exception as exc:
                self.status = ConnectorStatus.ERROR
                self.last_error = str(exc)[:200]
                return False
        self.status = ConnectorStatus.CONNECTED
        return True

    def normalize(self, raw: dict[str, Any]) -> Event | None:
        kind = str(raw.get("_ghost_kind", ""))
        if kind == "issue":
            action = str(raw.get("action", "opened"))
            return new_event(
                "github.issue_created" if action in ("opened", "created") else "github.issue_updated",
                source="github",
                actor=str((raw.get("user") or {}).get("login", "")),
                payload={
                    "repo": self.repo,
                    "number": raw.get("number"),
                    "title": raw.get("title", ""),
                    "action": action,
                },
                event_id=f"gh-{self.repo}-issue-{raw.get('number')}-{action}-{raw.get('updated_at', '')}",
                confidence=0.95,
            )
        if kind == "pull":
            action = str(raw.get("action", "opened"))
            event_type = (
                "github.pull_request_merged"
                if action == "closed" and raw.get("merged")
                else "github.pull_request_opened"
                if action == "opened"
                else "github.issue_updated"
            )
            return new_event(
                event_type,
                source="github",
                actor=str((raw.get("user") or {}).get("login", "")),
                payload={
                    "repo": self.repo,
                    "number": raw.get("number"),
                    "title": raw.get("title", ""),
                    "action": action,
                },
                event_id=f"gh-{self.repo}-pr-{raw.get('number')}-{action}",
                confidence=0.95,
            )
        if kind == "commit":
            sha = str(raw.get("sha", ""))[:12]
            return new_event(
                "github.commit",
                source="github",
                actor=str(((raw.get("commit") or {}).get("author") or {}).get("name", "")),
                payload={
                    "repo": self.repo,
                    "sha": sha,
                    "message": str((raw.get("commit") or {}).get("message", ""))[:500],
                },
                event_id=f"gh-{self.repo}-commit-{sha}",
                confidence=0.9,
            )
        return None

    def poll_once(self) -> list[Event]:
        assert self._fetcher is not None, "connect() first"
        events: list[Event] = []
        known: set[str] = self._state.setdefault("known", set())
        for path, kind in (
            (f"/repos/{self.repo}/issues?state=all&sort=updated&direction=desc&per_page=20", "issue"),
            (f"/repos/{self.repo}/pulls?state=all&sort=updated&direction=desc&per_page=20", "pull"),
            (f"/repos/{self.repo}/commits?per_page=20", "commit"),
        ):
            try:
                items = self._fetcher(path) or []
            except Exception:
                continue  # one failing endpoint must not sink the poll
            if isinstance(items, dict):
                items = [items]
            for raw in items[:20]:
                if not isinstance(raw, dict):
                    continue
                raw = dict(raw)
                raw["_ghost_kind"] = kind
                event = self.normalize(raw)
                if event is None or event.event_id in known:
                    continue
                known.add(event.event_id)
                events.append(event)
        if len(known) > 2000:
            self._state["known"] = set(list(known)[-1000:])
        return events


def normalize_github_webhook(event_name: str, delivery_id: str, payload: dict[str, Any]) -> Event | None:
    """Map a verified GitHub webhook delivery to a Ghost event.

    Verification (HMAC signature) happens upstream in the HTTP layer —
    this function is pure mapping. Idempotency key = delivery id.
    """
    repo = str((payload.get("repository") or {}).get("full_name", ""))
    sender = str((payload.get("sender") or {}).get("login", ""))
    base = {"repo": repo, "delivery_id": delivery_id}
    if event_name == "push":
        commits = payload.get("commits") or []
        head = str(payload.get("after", ""))[:12]
        messages = "; ".join(str(c.get("message", ""))[:200] for c in commits[:5])
        return new_event(
            "github.commit",
            source="github-webhook",
            actor=sender,
            payload={**base, "sha": head, "message": messages, "ref": str(payload.get("ref", ""))},
            event_id=f"gh-webhook-{delivery_id}",
            confidence=0.98,
        )
    if event_name == "issues":
        issue = payload.get("issue") or {}
        action = str(payload.get("action", "opened"))
        return new_event(
            "github.issue_created" if action == "opened" else "github.issue_updated",
            source="github-webhook",
            actor=sender,
            payload={**base, "number": issue.get("number"), "title": str(issue.get("title", "")), "action": action},
            event_id=f"gh-webhook-{delivery_id}",
            confidence=0.98,
        )
    if event_name == "pull_request":
        pr = payload.get("pull_request") or {}
        action = str(payload.get("action", "opened"))
        merged = action == "closed" and bool(pr.get("merged"))
        return new_event(
            "github.pull_request_merged"
            if merged
            else "github.pull_request_opened"
            if action == "opened"
            else "github.issue_updated",
            source="github-webhook",
            actor=sender,
            payload={**base, "number": pr.get("number"), "title": str(pr.get("title", "")), "action": action},
            event_id=f"gh-webhook-{delivery_id}",
            confidence=0.98,
        )
    return None


__all__ = ["GitHubEventConnector", "normalize_github_webhook"]
