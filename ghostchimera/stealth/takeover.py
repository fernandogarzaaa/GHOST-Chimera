"""Takeover-mode login: the user drives, the agent looks away.

When a site needs a real password (or any manual step), Ghost hands the
interactive surface to the operator:
  1. start(): pause the stealth loop policy, block all live-executor
     actions, open/navigate to the login page — then stop capturing.
  2. The operator logs in manually in their own browser/desktop. Ghost
     issues no CDP/desktop commands and captures nothing: keystrokes and
     session cookies never pass through Ghost code.
  3. release(): resume the loop (restoring its prior enabled state).

Session-only posture: nothing credential-shaped is persisted — only audit
events (start/release/timeout + purpose). A TTL auto-releases a forgotten
takeover so the agent cannot be parked forever.
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Any

DEFAULT_TAKEOVER_TTL_S = 600.0


class TakeoverError(RuntimeError):
    pass


class TakeoverActive(TakeoverError):
    """Raised by live executors while the operator is in control."""


class TakeoverManager:
    """Process-global user-control state + loop pause hooks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, Any] | None = None
        self._pause_hook: Any = None
        self._resume_hook: Any = None
        self._was_enabled = True

    def set_loop_hooks(self, *, pause: Any, resume: Any) -> None:
        with self._lock:
            self._pause_hook = pause
            self._resume_hook = resume

    def start(
        self,
        *,
        session_id: str = "console-browser",
        purpose: str = "",
        url: str = "",
        ttl_s: float = DEFAULT_TAKEOVER_TTL_S,
        actor: str = "console-user",
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            if self._active is not None and now < float(self._active["expires_at"]):
                raise TakeoverError("takeover already active; release it first")
            self._was_enabled = True
            if self._pause_hook is not None:
                with contextlib.suppress(Exception):
                    self._was_enabled = bool(self._pause_hook())
            self._active = {
                "session_id": session_id,
                "purpose": str(purpose or "")[:200],
                "url": str(url or "")[:500],
                "actor": actor,
                "started_at": now,
                "expires_at": now + max(60.0, float(ttl_s)),
            }
            return dict(self._active)

    def release(self, *, actor: str = "console-user") -> dict[str, Any]:
        with self._lock:
            if self._active is None:
                return {"released": False, "reason": "no active takeover"}
            active = dict(self._active)
            self._active = None
            if self._resume_hook is not None and self._was_enabled:
                with contextlib.suppress(Exception):
                    self._resume_hook()
            active["released"] = True
            active["released_by"] = actor
            active["released_at"] = time.time()
            return active

    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._active is None:
                return {"active": False}
            if time.time() >= float(self._active["expires_at"]):
                expired = dict(self._active)
                self._active = None
                if self._resume_hook is not None and self._was_enabled:
                    with contextlib.suppress(Exception):
                        self._resume_hook()
                expired["active"] = False
                expired["expired"] = True
                return expired
            return {"active": True, **dict(self._active)}

    def check(self) -> None:
        """Executor guard: raise while the operator is in control."""
        state = self.status()
        if state.get("active"):
            raise TakeoverActive(
                f"operator takeover active ({state.get('purpose') or 'manual login'}); "
                "agent actions blocked until release"
            )


_MANAGER = TakeoverManager()


def takeover_manager() -> TakeoverManager:
    return _MANAGER


def takeover_active() -> bool:
    return bool(_MANAGER.status().get("active"))


__all__ = ["TakeoverActive", "TakeoverError", "TakeoverManager", "takeover_active", "takeover_manager"]
