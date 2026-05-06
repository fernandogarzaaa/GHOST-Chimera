"""Approval flow runtime for Ghost Chimera.

Mirrors OpenClaw's ACP (Agent Conversation Protocol) approval surface.
Tool calls that require human review are routed through an
:class:`ApprovalHandler` before execution.  The default handler auto-approves
calls that match the policy's trusted set and blocks everything else.

Usage::

    from ghostchimera.safety_layer.approval import (
        ApprovalPolicy,
        ApprovalRequest,
        ApprovalResult,
        ConsoleApprovalHandler,
        get_default_policy,
    )

    policy = get_default_policy()
    policy.add_trusted("read_file")

    handler = ConsoleApprovalHandler(policy)
    result = handler.handle(ApprovalRequest(tool_name="shell",
                                            arguments={"command": "ls"},
                                            requester="agent-1"))
    if result.approved:
        ...  # execute
"""

from __future__ import annotations

import fnmatch
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..logging_config import get_logger

logger = get_logger("approval")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalRequest:
    """A pending tool-call that needs approval before execution.

    Parameters
    ----------
    tool_name:
        The name of the tool to be called.
    arguments:
        The arguments the agent wants to pass to the tool.
    requester:
        Identifier of the requesting agent or session.
    context:
        Optional extra context (task ID, session ID, etc.).
    """

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    requester: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "requester": self.requester,
            "context": self.context,
        }


@dataclass(frozen=True)
class ApprovalResult:
    """The outcome of an approval request.

    Parameters
    ----------
    approved:
        Whether the tool call is permitted.
    reason:
        Human-readable explanation.
    approver:
        Who (or what) made the decision.
    """

    approved: bool
    reason: str = ""
    approver: str = "policy"

    @classmethod
    def allow(cls, reason: str = "approved", approver: str = "policy") -> ApprovalResult:
        return cls(approved=True, reason=reason, approver=approver)

    @classmethod
    def deny(cls, reason: str = "denied", approver: str = "policy") -> ApprovalResult:
        return cls(approved=False, reason=reason, approver=approver)

    def to_dict(self) -> dict[str, Any]:
        return {"approved": self.approved, "reason": self.reason, "approver": self.approver}


# ---------------------------------------------------------------------------
# Approval policy
# ---------------------------------------------------------------------------


class ApprovalPolicy:
    """Decides whether a tool call requires human approval.

    Three outcome categories:

    * **trusted** — always approved without asking a human.
    * **blocked** — always denied.
    * **requires_approval** — routes to the :class:`ApprovalHandler`.

    Glob patterns are supported in all three sets (e.g. ``"read_*"``).
    """

    def __init__(self) -> None:
        self._trusted: list[str] = list(self._default_trusted())
        self._blocked: list[str] = list(self._default_blocked())
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    @staticmethod
    def _default_trusted() -> list[str]:
        return ["read_file", "code_search", "rag_query", "safety_check",
                "hallucination_detect", "memory_search"]

    @staticmethod
    def _default_blocked() -> list[str]:
        return ["delete_*", "rm_*", "drop_*"]

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_trusted(self, pattern: str) -> None:
        """Add a glob *pattern* to the always-approved set."""
        with self._lock:
            if pattern not in self._trusted:
                self._trusted.append(pattern)

    def add_blocked(self, pattern: str) -> None:
        """Add a glob *pattern* to the always-denied set."""
        with self._lock:
            if pattern not in self._blocked:
                self._blocked.append(pattern)

    def remove_trusted(self, pattern: str) -> None:
        with self._lock:
            self._trusted = [p for p in self._trusted if p != pattern]

    def remove_blocked(self, pattern: str) -> None:
        with self._lock:
            self._blocked = [p for p in self._blocked if p != pattern]

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(self, tool_name: str) -> str:
        """Return ``"trusted"``, ``"blocked"``, or ``"requires_approval"``."""
        with self._lock:
            for pattern in self._blocked:
                if fnmatch.fnmatch(tool_name, pattern):
                    return "blocked"
            for pattern in self._trusted:
                if fnmatch.fnmatch(tool_name, pattern):
                    return "trusted"
        return "requires_approval"

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {"trusted": list(self._trusted), "blocked": list(self._blocked)}


# ---------------------------------------------------------------------------
# Approval handler ABC + built-in implementations
# ---------------------------------------------------------------------------


class ApprovalHandler(ABC):
    """Abstract base for approval handlers.

    Implementations decide what happens for ``"requires_approval"`` requests.
    """

    def __init__(self, policy: ApprovalPolicy | None = None) -> None:
        self.policy = policy or ApprovalPolicy()

    def handle(self, request: ApprovalRequest) -> ApprovalResult:
        """Classify the request and apply the appropriate gate.

        Short-circuits for trusted/blocked tools; delegates to
        :meth:`_ask_human` only for the ``"requires_approval"`` category.
        """
        verdict = self.policy.classify(request.tool_name)
        if verdict == "trusted":
            return ApprovalResult.allow(
                reason=f"tool '{request.tool_name}' is in the trusted set",
                approver="policy",
            )
        if verdict == "blocked":
            return ApprovalResult.deny(
                reason=f"tool '{request.tool_name}' is blocked by policy",
                approver="policy",
            )
        # requires_approval
        return self._ask_human(request)

    @abstractmethod
    def _ask_human(self, request: ApprovalRequest) -> ApprovalResult:
        """Route the request to a human (or automated) reviewer."""


class AutoApproveHandler(ApprovalHandler):
    """Automatically approves all ``"requires_approval"`` requests.

    Useful for non-interactive test/CI environments.
    """

    def _ask_human(self, request: ApprovalRequest) -> ApprovalResult:
        logger.debug("AutoApproveHandler: approving tool call '%s'", request.tool_name)
        return ApprovalResult.allow(
            reason="auto-approved (non-interactive mode)",
            approver="auto_approve_handler",
        )


class AutoDenyHandler(ApprovalHandler):
    """Automatically denies all ``"requires_approval"`` requests.

    Useful for strict sandbox / read-only environments.
    """

    def _ask_human(self, request: ApprovalRequest) -> ApprovalResult:
        logger.debug("AutoDenyHandler: denying tool call '%s'", request.tool_name)
        return ApprovalResult.deny(
            reason="denied (non-interactive sandbox)",
            approver="auto_deny_handler",
        )


class ConsoleApprovalHandler(ApprovalHandler):
    """Interactive handler that prompts the user on stdout/stdin.

    Falls back to :class:`AutoDenyHandler` when stdin is not a TTY.
    """

    def _ask_human(self, request: ApprovalRequest) -> ApprovalResult:
        import sys

        if not sys.stdin.isatty():
            return ApprovalResult.deny(
                reason="stdin is not a TTY; falling back to deny",
                approver="console_handler",
            )

        print(f"\n[APPROVAL REQUIRED] Tool: {request.tool_name}")
        if request.arguments:
            print(f"  Arguments: {request.arguments}")
        if request.requester:
            print(f"  Requester: {request.requester}")
        try:
            answer = input("  Allow? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        approved = answer in {"y", "yes"}
        return ApprovalResult(
            approved=approved,
            reason="user approved" if approved else "user denied",
            approver="console",
        )


class CallbackApprovalHandler(ApprovalHandler):
    """Approval handler backed by a user-supplied callback.

    The callback receives an :class:`ApprovalRequest` and returns a bool.
    """

    def __init__(
        self,
        callback: Any,
        policy: ApprovalPolicy | None = None,
    ) -> None:
        super().__init__(policy)
        self._callback = callback

    def _ask_human(self, request: ApprovalRequest) -> ApprovalResult:
        try:
            approved = bool(self._callback(request))
            return ApprovalResult(
                approved=approved,
                reason="callback returned True" if approved else "callback returned False",
                approver="callback",
            )
        except Exception as exc:
            logger.warning("CallbackApprovalHandler callback raised: %s", exc)
            return ApprovalResult.deny(reason=f"callback error: {exc}", approver="callback")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_policy: ApprovalPolicy | None = None
_default_handler: ApprovalHandler | None = None
_singleton_lock = threading.Lock()


def get_default_policy() -> ApprovalPolicy:
    """Return the process-wide default :class:`ApprovalPolicy`."""
    global _default_policy
    if _default_policy is None:
        with _singleton_lock:
            if _default_policy is None:
                _default_policy = ApprovalPolicy()
    return _default_policy


def get_default_handler() -> ApprovalHandler:
    """Return the process-wide default :class:`ApprovalHandler`.

    In non-interactive mode (no TTY) returns :class:`AutoDenyHandler`.
    In interactive mode returns :class:`ConsoleApprovalHandler`.
    """
    global _default_handler
    if _default_handler is None:
        with _singleton_lock:
            if _default_handler is None:
                import sys
                policy = get_default_policy()
                if sys.stdin.isatty() and not _truthy(os.environ.get("GHOSTCHIMERA_AUTO_APPROVE")):
                    _default_handler = ConsoleApprovalHandler(policy)
                elif _truthy(os.environ.get("GHOSTCHIMERA_AUTO_APPROVE")):
                    _default_handler = AutoApproveHandler(policy)
                else:
                    _default_handler = AutoDenyHandler(policy)
    return _default_handler


def set_default_handler(handler: ApprovalHandler) -> None:
    """Override the process-wide approval handler."""
    global _default_handler
    with _singleton_lock:
        _default_handler = handler


def approve(tool_name: str, arguments: dict[str, Any] | None = None,
            requester: str = "") -> ApprovalResult:
    """Convenience wrapper: run the default handler for a single tool call."""
    handler = get_default_handler()
    req = ApprovalRequest(tool_name=tool_name,
                          arguments=arguments or {},
                          requester=requester)
    return handler.handle(req)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "ApprovalPolicy",
    "ApprovalRequest",
    "ApprovalResult",
    "ApprovalHandler",
    "AutoApproveHandler",
    "AutoDenyHandler",
    "ConsoleApprovalHandler",
    "CallbackApprovalHandler",
    "get_default_policy",
    "get_default_handler",
    "set_default_handler",
    "approve",
]
