"""Bluesky access via app-password sessions (officially sanctioned for bots/CLI).

AT Protocol OAuth (DPoP + PAR + client metadata) is deferred; password
sessions produce the same authenticated session and are what Bluesky
documents for single-purpose apps. Handle + app password live in the
auth-engine custom-key vault (kind ``byok`` recommended); sessions are
in-memory only (session-only posture: re-login each process).
Public reads (timeline profiles, public posts) need no auth at all and go
through the public AppView. Stdlib-only (urllib).
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_PDS = "https://bsky.social"
PUBLIC_APPVIEW = "https://public.api.bsky.app"


class BlueskyError(RuntimeError):
    pass


def _request(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    token: str = "",
    proxy_did: str = "",
    timeout: float = 30.0,
) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if proxy_did:
        headers["atproto-proxy"] = proxy_did
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise BlueskyError(f"bluesky HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise BlueskyError(f"bluesky unreachable: {type(exc).__name__}") from exc


def create_session(handle: str, app_password: str, *, pds: str = DEFAULT_PDS, request_fn: Any = None) -> dict[str, Any]:
    """Log in with handle + app password. Returns session (tokens in-memory)."""
    if not handle or not app_password:
        raise BlueskyError("handle and app password are required (never the main password)")
    post = request_fn or _request
    host = (pds or DEFAULT_PDS).rstrip("/")
    data = post(
        "POST", f"{host}/xrpc/com.atproto.server.createSession", body={"identifier": handle, "password": app_password}
    )
    if not isinstance(data, dict) or not data.get("accessJwt"):
        raise BlueskyError("login failed: no session returned")
    return {
        "did": str(data.get("did", "")),
        "handle": str(data.get("handle", handle)),
        "access_jwt": str(data["accessJwt"]),
        "refresh_jwt": str(data.get("refreshJwt", "")),
        "pds": host,
        "created_at": time.time(),
    }


def send_post(session: dict[str, Any], text: str, *, request_fn: Any = None) -> dict[str, Any]:
    """Publish a text post (approval-gated by callers). Max 300 chars."""
    text = (text or "").strip()
    if not text:
        raise BlueskyError("post text is required")
    if len(text) > 300:
        raise BlueskyError("posts are limited to 300 chars")
    post = request_fn or _request
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    return post(
        "POST",
        f"{session['pds']}/xrpc/com.atproto.repo.createRecord",
        body={
            "repo": session["did"],
            "collection": "app.bsky.feed.post",
            "record": {"text": text, "createdAt": now},
        },
        token=session["access_jwt"],
    )


def get_timeline(session: dict[str, Any], *, limit: int = 10, request_fn: Any = None) -> dict[str, Any]:
    """Read the authenticated home timeline (headers + text only)."""
    get = request_fn or _request
    limit = max(1, min(50, limit))
    query = urllib.parse.urlencode({"limit": limit})
    return get("GET", f"{session['pds']}/xrpc/app.bsky.feed.getTimeline?{query}", token=session["access_jwt"])


def public_profile(handle: str, *, request_fn: Any = None) -> dict[str, Any]:
    """Resolve a public profile. No auth required."""
    get = request_fn or _request
    query = urllib.parse.urlencode({"actor": handle})
    return get("GET", f"{PUBLIC_APPVIEW}/xrpc/app.bsky.actor.getProfile?{query}")


__all__ = ["BlueskyError", "create_session", "get_timeline", "public_profile", "send_post"]
