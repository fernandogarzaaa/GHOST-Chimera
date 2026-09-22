"""Structured approval requests: the submit handoff with an expiry.

ASK decisions currently flag ``needs_approval`` on an intervention and
dead-end; submitted proposals hand off to nothing. ApprovalRequests close
that gap: a bounded queue of explicit, expiring asks recording what was
requested, why, by whom, and who decided. Approvals authorize — they never
execute; execution stays with the existing ACT path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .events import new_event_id
from .graduation import Proposal, ProposalState, ProposalTier
from .intervention import Intervention

DEFAULT_APPROVAL_TTL_S = 86400.0
MAX_PENDING_APPROVALS = 50


class ApprovalState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


TERMINAL_APPROVAL_STATES = frozenset({ApprovalState.APPROVED, ApprovalState.DENIED, ApprovalState.EXPIRED})


@dataclass
class ApprovalRequest:
    """One structured, expiring ask awaiting a human decision."""

    id: str
    subject: str = ""
    body: str = ""
    workflow: str = ""
    source_kind: str = "manual"  # "proposal" | "intervention" | "manual"
    source_id: str = ""
    risk: float = 0.5
    details: dict[str, Any] = field(default_factory=dict)
    state: ApprovalState = ApprovalState.PENDING
    requested_by: str = ""
    decided_by: str = ""
    decision_note: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0

    def terminal(self) -> bool:
        return self.state in TERMINAL_APPROVAL_STATES

    def expired(self, now: float | None = None) -> bool:
        moment = now if now is not None else time.time()
        return not self.terminal() and self.expires_at > 0 and moment >= self.expires_at

    def _settle(self, state: ApprovalState, actor: str, note: str, now: float | None) -> bool:
        moment = now if now is not None else time.time()
        if self.terminal():
            return False
        if self.expired(moment):
            self.state = ApprovalState.EXPIRED
            return False
        self.state = state
        self.decided_by = actor
        self.decision_note = note
        return True

    def approve(self, actor: str, note: str = "", *, now: float | None = None) -> bool:
        """Grant the request; overdue requests expire instead."""

        return self._settle(ApprovalState.APPROVED, actor, note, now)

    def deny(self, actor: str, note: str = "", *, now: float | None = None) -> bool:
        """Refuse the request; overdue requests expire instead."""

        return self._settle(ApprovalState.DENIED, actor, note, now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "body": self.body,
            "workflow": self.workflow,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "risk": self.risk,
            "details": dict(self.details),
            "state": self.state.value,
            "requested_by": self.requested_by,
            "decided_by": self.decided_by,
            "decision_note": self.decision_note,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRequest:
        data = data if isinstance(data, dict) else {}
        try:
            state = ApprovalState(str(data.get("state", "pending")))
        except ValueError:
            state = ApprovalState.PENDING
        return cls(
            id=str(data.get("id", "")) or new_event_id("apr"),
            subject=str(data.get("subject", "")),
            body=str(data.get("body", "")),
            workflow=str(data.get("workflow", "")),
            source_kind=str(data.get("source_kind", "manual")),
            source_id=str(data.get("source_id", "")),
            risk=max(0.0, min(1.0, float(data.get("risk", 0.5) or 0.0))),
            details=dict(data.get("details", {}) or {}),
            state=state,
            requested_by=str(data.get("requested_by", "")),
            decided_by=str(data.get("decided_by", "")),
            decision_note=str(data.get("decision_note", "")),
            created_at=float(data.get("created_at", 0.0) or 0.0),
            expires_at=float(data.get("expires_at", 0.0) or 0.0),
        )


class ApprovalQueue:
    """Bounded store for approval requests; refuses (never recycles) when full.

    Optionally attached to a durable authority
    (connectors ActionApprovalStore): every request is mirrored there under
    provider "stealth" so asks survive restarts and appear in the canonical
    Trust surface; decisions in either place are reflected in the other via
    sync(). Without an attached authority the queue behaves exactly as
    before (in-memory only).
    """

    def __init__(self, *, max_pending: int = MAX_PENDING_APPROVALS) -> None:
        self.max_pending = max(1, max_pending)
        self._requests: dict[str, ApprovalRequest] = {}
        self._authority: Any = None
        self._authority_entity = "stealth"

    def attach_authority(self, store: Any, *, entity_id: str = "stealth") -> None:
        """Write-through durable backend (ActionApprovalStore).

        Pre-existing pending items are mirrored immediately, and durable
        pending stealth records unknown here (e.g. from before a restart)
        are imported — so no ask is lost in either direction.
        """
        self._authority = store
        self._authority_entity = entity_id
        for item in self._requests.values():
            if item.state == ApprovalState.PENDING and not item.details.get("authority_id"):
                self._mirror_request(item)
        self._import_durable_pending()
        self.sync()

    def _import_durable_pending(self) -> int:
        """Reconstruct queue items from durable stealth records (restart recovery)."""
        if self._authority is None:
            return 0
        try:
            records = self._authority.pending(self._authority_entity)
        except Exception:
            return 0
        known = {item.details.get("authority_id") for item in self._requests.values()}
        imported = 0
        for record in records:
            if record.get("provider") != "stealth" or record.get("id") in known:
                continue
            url = str(record.get("url") or "")
            source_kind, _, source_id = url.removeprefix("stealth://").partition("/")
            try:
                expires_in = max(1.0, float(record.get("expires_at", 0) or 0) - time.time())
            except (TypeError, ValueError):
                continue
            if expires_in <= 0:
                continue
            item = ApprovalRequest(
                id=new_event_id("apr"),
                subject=str(record.get("summary") or "stealth approval"),
                body="",
                workflow=str(record.get("scope") or ""),
                source_kind=source_kind or "unknown",
                source_id=source_id,
                requested_by=str(record.get("requested_by") or ""),
                created_at=float(record.get("created_at", 0) or time.time()),
                expires_at=time.time() + expires_in,
                details={"authority_id": record["id"], "imported": True},
            )
            self._requests[item.id] = item
            imported += 1
        return imported

    def _mirror_request(self, item: ApprovalRequest) -> None:
        if self._authority is None:
            return
        try:
            remaining = max(1.0, float(item.expires_at - item.created_at))
            created = self._authority.request(
                self._authority_entity,
                "stealth",
                "APPROVE",
                f"stealth://{item.source_kind}/{item.source_id or item.id}",
                {"subject": item.subject, "body": item.body, "risk": item.risk, "details": item.details},
                scope=item.workflow,
                summary=item.subject[:300],
                requested_by=item.requested_by,
                ttl_s=remaining,
            )
            item.details = {**item.details, "authority_id": created["id"]}
        except Exception:
            pass

    def _decide_durable_first(self, item: ApprovalRequest, *, approved: bool, actor: str) -> bool:
        """Decide the durable record before touching local state.

        Returns True only when the authority confirms the requested
        outcome. An EXPIRED (or otherwise non-matching) authority marks
        the local item expired and reports failure — local state is never
        finalized ahead of the canonical record.
        """
        if self._authority is None:
            return True
        authority_id = item.details.get("authority_id", "")
        if not authority_id:
            return True
        try:
            result = self._authority.decide(authority_id, approved=approved, actor=actor or "stealth-loop")
        except Exception:
            return False
        want = "APPROVED" if approved else "DENIED"
        if isinstance(result, dict) and result.get("state") == want:
            return True
        if isinstance(result, dict) and result.get("state") == "EXPIRED":
            item.state = ApprovalState.EXPIRED
        return False

    def sync(self, now: float | None = None) -> int:
        """Pull external decisions from the authority into memory.

        Returns the number of items updated. Items decided in the Trust UI
        (or expired there) are reflected here; unknown here but pending
        there are NOT imported (stealth asks originate in the loop).
        """
        if self._authority is None:
            return 0
        moment = now if now is not None else time.time()
        updated = 0
        try:
            states = {item.details.get("authority_id"): item for item in self._requests.values()}
            states.pop("", None)
            if not states:
                return 0
            # The authority store is the source of truth for mirrored state.
            # It expires lazily, so apply the TTL here as well as the state.
            for authority_id, item in states.items():
                try:
                    record = self._authority.describe(authority_id)
                except Exception:
                    continue
                if record is None:
                    continue
                state = str(record.get("state", ""))
                overdue = moment >= float(record.get("expires_at", 0) or 0)
                if state == "APPROVED" and item.state == ApprovalState.PENDING:
                    item.state = ApprovalState.APPROVED
                    item.decided_by = str(record.get("decided_by", "") or "trust-ui")
                    updated += 1
                elif state == "DENIED" and item.state == ApprovalState.PENDING:
                    item.state = ApprovalState.DENIED
                    item.decided_by = str(record.get("decided_by", "") or "trust-ui")
                    updated += 1
                elif state == "EXPIRED" or (overdue and item.state == ApprovalState.PENDING):
                    item.state = ApprovalState.EXPIRED
                    updated += 1
            updated += self.sweep(moment)
        except Exception:
            pass
        return updated

    def _has_room(self) -> bool:
        return sum(1 for item in self._requests.values() if not item.terminal()) < self.max_pending

    def request(
        self,
        subject: str,
        *,
        body: str = "",
        workflow: str = "",
        source_kind: str = "manual",
        source_id: str = "",
        risk: float = 0.5,
        details: dict[str, Any] | None = None,
        requested_by: str = "",
        ttl_s: float | None = None,
        now: float | None = None,
    ) -> ApprovalRequest | None:
        """File a new ask; None when the pending queue is full."""

        if not self._has_room():
            return None
        moment = now if now is not None else time.time()
        item = ApprovalRequest(
            id=new_event_id("apr"),
            subject=subject,
            body=body,
            workflow=workflow,
            source_kind=source_kind,
            source_id=source_id,
            risk=max(0.0, min(1.0, risk)),
            details=dict(details or {}),
            requested_by=requested_by,
            created_at=moment,
            expires_at=moment + (ttl_s if ttl_s is not None else DEFAULT_APPROVAL_TTL_S),
        )
        self._requests[item.id] = item
        self._mirror_request(item)
        return item

    def request_for_proposal(
        self, proposal: Proposal, *, requested_by: str = "", ttl_s: float | None = None, now: float | None = None
    ) -> ApprovalRequest | None:
        """Submit-handoff: only SUBMIT-tier proposals may ask."""

        if proposal.tier is not ProposalTier.SUBMIT or proposal.state not in (
            ProposalState.PENDING,
            ProposalState.SUBMITTED,
        ):
            return None
        return self.request(
            proposal.title or f"submit: {proposal.workflow or proposal.id}",
            body=proposal.body,
            workflow=proposal.workflow,
            source_kind="proposal",
            source_id=proposal.id,
            details={"prefill": dict(proposal.prefill), "proposal_state": proposal.state.value},
            requested_by=requested_by,
            ttl_s=ttl_s,
            now=now,
        )

    def request_for_intervention(
        self,
        intervention: Intervention,
        *,
        requested_by: str = "",
        ttl_s: float | None = None,
        now: float | None = None,
    ) -> ApprovalRequest | None:
        """ASK-handoff: turn a needs-approval intervention into an ask."""

        return self.request(
            f"approval: {intervention.workflow or intervention.id}",
            body=intervention.reason,
            workflow=intervention.workflow,
            source_kind="intervention",
            source_id=intervention.id,
            details={"confidence": intervention.confidence},
            requested_by=requested_by,
            ttl_s=ttl_s,
            now=now,
        )

    def get(self, request_id: str) -> ApprovalRequest | None:
        return self._requests.get(request_id)

    def approve(self, request_id: str, actor: str, note: str = "", *, now: float | None = None) -> bool:
        item = self._requests.get(request_id)
        if item is None:
            return False
        if not self._decide_durable_first(item, approved=True, actor=actor):
            return False
        return item.approve(actor, note, now=now)

    def deny(self, request_id: str, actor: str, note: str = "", *, now: float | None = None) -> bool:
        item = self._requests.get(request_id)
        if item is None:
            return False
        if not self._decide_durable_first(item, approved=False, actor=actor):
            return False
        return item.deny(actor, note, now=now)

    def pending(self) -> list[ApprovalRequest]:
        return sorted(
            (item for item in self._requests.values() if item.state == ApprovalState.PENDING),
            key=lambda item: item.created_at,
        )

    def sweep(self, now: float | None = None) -> int:
        """Expire overdue asks; returns the expired count."""

        moment = now if now is not None else time.time()
        count = 0
        for item in self._requests.values():
            if item.expired(moment):
                item.state = ApprovalState.EXPIRED
                count += 1
        return count

    def __len__(self) -> int:
        return len(self._requests)

    def to_dict(self) -> dict[str, Any]:
        return {"requests": [item.to_dict() for item in self._requests.values()]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalQueue:
        queue = cls()
        for raw in (data or {}).get("requests", []) or []:
            item = ApprovalRequest.from_dict(raw)
            queue._requests[item.id] = item
        return queue


__all__ = [
    "DEFAULT_APPROVAL_TTL_S",
    "MAX_PENDING_APPROVALS",
    "ApprovalQueue",
    "ApprovalRequest",
    "ApprovalState",
]
