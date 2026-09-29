"""Policy-controlled approval gates for always-on agents.

High-stakes tool calls never execute without an explicit decision. In daemon
mode there is no TTY to ask, so :class:`QueuedApprovalHandler` parks each
``requires_approval`` request as a persistent :class:`ApprovalTicket` and
blocks the requesting thread until the ticket is decided (via the Ghost
Console, the CLI, or the API) or the wait times out — at which point the
ticket expires and the call is denied. There is no auto-approve path here:
every outcome is allow-by-decision or deny.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config import GhostChimeraConfig
from ...logging_config import get_logger
from ...safety_layer.approval import ApprovalHandler, ApprovalPolicy, ApprovalRequest, ApprovalResult

logger = get_logger("always_on.approvals")

APPROVAL_DIRNAME = "approvals"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_EXPIRED = "expired"

TERMINAL_STATUSES = frozenset({STATUS_APPROVED, STATUS_DENIED, STATUS_EXPIRED})


@dataclass(frozen=True)
class ApprovalTicket:
    """A parked approval request awaiting a human decision."""

    ticket_id: str
    tool_name: str
    arguments: dict[str, Any]
    requester: str
    context: dict[str, Any]
    status: str
    created_at: float
    decided_at: float | None = None
    decided_by: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "requester": self.requester,
            "context": dict(self.context),
            "status": self.status,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalTicket:
        return cls(
            ticket_id=str(data["ticket_id"]),
            tool_name=str(data["tool_name"]),
            arguments=dict(data.get("arguments") or {}),
            requester=str(data.get("requester") or ""),
            context=dict(data.get("context") or {}),
            status=str(data.get("status") or STATUS_PENDING),
            created_at=float(data.get("created_at") or 0.0),
            decided_at=data.get("decided_at"),
            decided_by=str(data.get("decided_by") or ""),
            reason=str(data.get("reason") or ""),
        )


class ApprovalStore:
    """Atomic, thread-safe persistence for approval tickets.

    Tickets live under ``<state_dir>/always_on/approvals/<ticket_id>.json``.
    Because the store is file-backed, a ticket decided from another process
    (the Ghost Console server, the CLI) is visible to the daemon immediately.
    """

    def __init__(self, state_dir: str | Path | None = None) -> None:
        base = Path(state_dir or GhostChimeraConfig.from_env().state_dir).expanduser()
        self.state_dir = base
        self._dir = base / "always_on" / APPROVAL_DIRNAME
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        requester: str = "",
        context: dict[str, Any] | None = None,
    ) -> ApprovalTicket:
        ticket = ApprovalTicket(
            ticket_id=f"approval-{uuid.uuid4().hex[:12]}",
            tool_name=tool_name,
            arguments=dict(arguments or {}),
            requester=requester,
            context=dict(context or {}),
            status=STATUS_PENDING,
            created_at=time.time(),
        )
        with self._lock:
            self._write(ticket)
        logger.info("Approval ticket %s opened for tool '%s' (requester=%s)", ticket.ticket_id, tool_name, requester)
        return ticket

    def get(self, ticket_id: str) -> ApprovalTicket | None:
        with self._lock:
            return self._read(ticket_id)

    def list_pending(self) -> list[ApprovalTicket]:
        """Pending tickets, oldest first."""
        with self._lock:
            return [t for t in self._list_all() if t.status == STATUS_PENDING]

    def list_recent(self, limit: int = 50) -> list[ApprovalTicket]:
        """All tickets, newest first, capped at *limit*."""
        with self._lock:
            tickets = sorted(self._list_all(), key=lambda t: t.created_at, reverse=True)
            return tickets[: max(1, limit)]

    def decide(self, ticket_id: str, approved: bool, decided_by: str = "") -> ApprovalTicket:
        """Record a human decision. Only pending tickets can be decided."""
        with self._lock:
            ticket = self._read(ticket_id)
            if ticket is None:
                raise KeyError(f"Unknown approval ticket '{ticket_id}'")
            if ticket.status != STATUS_PENDING:
                raise ValueError(f"Ticket '{ticket_id}' is already {ticket.status}")
            decided = ApprovalTicket(
                ticket_id=ticket.ticket_id,
                tool_name=ticket.tool_name,
                arguments=dict(ticket.arguments),
                requester=ticket.requester,
                context=dict(ticket.context),
                status=STATUS_APPROVED if approved else STATUS_DENIED,
                created_at=ticket.created_at,
                decided_at=time.time(),
                decided_by=decided_by or "console",
                reason="approved by operator" if approved else "denied by operator",
            )
            self._write(decided)
        logger.info("Approval ticket %s %s by %s", ticket_id, decided.status, decided.decided_by)
        return decided

    def expire(self, ticket_id: str, reason: str = "approval wait timed out") -> ApprovalTicket | None:
        """Mark a pending ticket expired (deny-by-timeout)."""
        with self._lock:
            ticket = self._read(ticket_id)
            if ticket is None or ticket.status != STATUS_PENDING:
                return ticket
            expired = ApprovalTicket(
                ticket_id=ticket.ticket_id,
                tool_name=ticket.tool_name,
                arguments=dict(ticket.arguments),
                requester=ticket.requester,
                context=dict(ticket.context),
                status=STATUS_EXPIRED,
                created_at=ticket.created_at,
                decided_at=time.time(),
                decided_by="daemon",
                reason=reason,
            )
            self._write(expired)
            return expired

    def expire_stale(self, older_than_seconds: float) -> int:
        """Expire pending tickets older than the cutoff. Returns count."""
        cutoff = time.time() - older_than_seconds
        expired = 0
        with self._lock:
            for ticket in self._list_all():
                if ticket.status == STATUS_PENDING and ticket.created_at < cutoff:
                    self.expire(ticket.ticket_id, reason="stale ticket reaped")
                    expired += 1
        return expired

    # ------------------------------------------------------------------
    # IO
    # ------------------------------------------------------------------

    def _list_all(self) -> list[ApprovalTicket]:
        tickets: list[ApprovalTicket] = []
        if self._dir.exists():
            for path in sorted(self._dir.glob("approval-*.json")):
                ticket = self._read(path.stem)
                if ticket is not None:
                    tickets.append(ticket)
        return tickets

    def _path(self, ticket_id: str) -> Path:
        return self._dir / f"{ticket_id}.json"

    def _write(self, ticket: ApprovalTicket) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._dir / f".{ticket.ticket_id}.tmp"
        tmp.write_text(json.dumps(ticket.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path(ticket.ticket_id))

    def _read(self, ticket_id: str) -> ApprovalTicket | None:
        path = self._path(ticket_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable approval ticket %s: %s", ticket_id, exc)
            return None
        try:
            return ApprovalTicket.from_dict(data)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Ignoring malformed approval ticket %s: %s", ticket_id, exc)
            return None


class QueuedApprovalHandler(ApprovalHandler):
    """Approval handler that parks requests as tickets and waits.

    Trusted tools are still auto-allowed and blocked tools auto-denied by the
    policy — only the ``requires_approval`` category parks. The requesting
    thread blocks until the ticket is decided or *wait_timeout_seconds*
    elapses; a timeout expires the ticket and denies the call. The wait polls
    the file-backed store, so a decision made from another process (console
    server, CLI) unblocks the daemon without any extra IPC.
    """

    def __init__(
        self,
        store: ApprovalStore | None = None,
        *,
        wait_timeout_seconds: float = 300.0,
        poll_interval_seconds: float = 0.5,
        policy: ApprovalPolicy | None = None,
    ) -> None:
        super().__init__(policy)
        self.store = store or ApprovalStore()
        self.wait_timeout_seconds = max(1.0, float(wait_timeout_seconds))
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))
        self._waiters: dict[str, threading.Event] = {}
        self._waiters_lock = threading.Lock()

    # ------------------------------------------------------------------
    # ApprovalHandler interface
    # ------------------------------------------------------------------

    def _ask_human(self, request: ApprovalRequest) -> ApprovalResult:
        ticket = self.store.create(
            request.tool_name,
            arguments=request.arguments,
            requester=request.requester,
            context=request.context,
        )
        event = threading.Event()
        with self._waiters_lock:
            self._waiters[ticket.ticket_id] = event

        try:
            decided = self._wait_for_decision(ticket.ticket_id)
        finally:
            with self._waiters_lock:
                self._waiters.pop(ticket.ticket_id, None)

        if decided is None:
            self.store.expire(ticket.ticket_id)
            return ApprovalResult.deny(
                reason=f"approval timed out after {self.wait_timeout_seconds:g}s; ticket {ticket.ticket_id} expired",
                approver="queued_handler",
            )
        if decided.status == STATUS_APPROVED:
            return ApprovalResult.allow(
                reason=f"approved by {decided.decided_by} (ticket {ticket.ticket_id})",
                approver=decided.decided_by,
            )
        return ApprovalResult.deny(
            reason=f"{decided.status} by {decided.decided_by}: {decided.reason} (ticket {ticket.ticket_id})",
            approver=decided.decided_by,
        )

    # ------------------------------------------------------------------
    # External decision entry points
    # ------------------------------------------------------------------

    def decide(self, ticket_id: str, approved: bool, decided_by: str = "") -> ApprovalTicket:
        """Decide a pending ticket and wake the blocked requester, if any."""
        ticket = self.store.decide(ticket_id, approved, decided_by=decided_by)
        self._wake_waiter(ticket_id)
        return ticket

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _wake_waiter(self, ticket_id: str) -> None:
        with self._waiters_lock:
            event = self._waiters.get(ticket_id)
        if event is not None:
            event.set()

    def _wait_for_decision(self, ticket_id: str) -> ApprovalTicket | None:
        """Block until the ticket leaves pending state or the timeout hits."""
        deadline = time.monotonic() + self.wait_timeout_seconds
        while True:
            with self._waiters_lock:
                event = self._waiters.get(ticket_id)
            if event is None:  # pragma: no cover - defensive
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            # Short waits keep cross-process decisions responsive.
            event.wait(timeout=min(self.poll_interval_seconds, remaining))
            current = self.store.get(ticket_id)
            if current is None or current.status != STATUS_PENDING:
                return current


__all__ = [
    "ApprovalTicket",
    "ApprovalStore",
    "QueuedApprovalHandler",
    "STATUS_PENDING",
    "STATUS_APPROVED",
    "STATUS_DENIED",
    "STATUS_EXPIRED",
    "TERMINAL_STATUSES",
]
