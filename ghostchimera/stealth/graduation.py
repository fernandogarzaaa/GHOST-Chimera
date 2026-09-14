"""Graduated action tiers: SUGGEST / PREVIEW / PRE-FILL / SUBMIT.

Evaluator decisions jump PREPARE -> INJECT -> ACT with no lightweight
middle. Proposals fill that gap as an additive, inert pipeline: a
suggestion is a pointer, a preview renders content without acting, a
pre-fill stages an actionable draft, and a submit hands off to the
existing execution/approval path. Creation never acts; only tier
transitions are autonomy-gated, and submitted proposals execute nothing
themselves.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .events import new_event_id
from .stealth_policy import AutonomyLevel
from .triggers import TriggerHit

MAX_PENDING = 50


class ProposalTier(StrEnum):
    SUGGEST = "suggest"
    PREVIEW = "preview"
    PREFILL = "prefill"
    SUBMIT = "submit"


class ProposalState(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


TIER_ORDER = (ProposalTier.SUGGEST, ProposalTier.PREVIEW, ProposalTier.PREFILL, ProposalTier.SUBMIT)

TIER_TTL_S = {
    ProposalTier.SUGGEST: 3600.0,
    ProposalTier.PREVIEW: 86400.0,
    ProposalTier.PREFILL: 86400.0,
    ProposalTier.SUBMIT: 86400.0,
}

# Autonomy required to *enter* a tier via advance()/submit(). Creation is ungated.
TIER_GATE = {
    ProposalTier.SUGGEST: AutonomyLevel.OBSERVE,
    ProposalTier.PREVIEW: AutonomyLevel.OBSERVE,
    ProposalTier.PREFILL: AutonomyLevel.PREPARE,
    ProposalTier.SUBMIT: AutonomyLevel.ACT,
}

TERMINAL_STATES = frozenset({ProposalState.SUBMITTED, ProposalState.DISMISSED, ProposalState.EXPIRED})


@dataclass
class Proposal:
    """One graduated action proposal with tier, content, and lifecycle."""

    id: str
    tier: ProposalTier = ProposalTier.SUGGEST
    title: str = ""
    body: str = ""
    workflow: str = ""
    source: str = ""
    min_autonomy: AutonomyLevel = AutonomyLevel.OBSERVE
    prefill: dict[str, Any] = field(default_factory=dict)
    state: ProposalState = ProposalState.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0

    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def expired(self, now: float | None = None) -> bool:
        moment = now if now is not None else time.time()
        return not self.terminal() and self.expires_at > 0 and moment >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tier": self.tier.value,
            "title": self.title,
            "body": self.body,
            "workflow": self.workflow,
            "source": self.source,
            "min_autonomy": self.min_autonomy.name.lower(),
            "prefill": dict(self.prefill),
            "state": self.state.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Proposal:
        data = data if isinstance(data, dict) else {}
        try:
            tier = ProposalTier(str(data.get("tier", "suggest")))
        except ValueError:
            tier = ProposalTier.SUGGEST
        try:
            state = ProposalState(str(data.get("state", "pending")))
        except ValueError:
            state = ProposalState.PENDING
        level = str(data.get("min_autonomy", "observe")).upper()
        created = float(data.get("created_at", 0.0) or 0.0)
        return cls(
            id=str(data.get("id", "")) or new_event_id("prop"),
            tier=tier,
            title=str(data.get("title", "")),
            body=str(data.get("body", "")),
            workflow=str(data.get("workflow", "")),
            source=str(data.get("source", "")),
            min_autonomy=AutonomyLevel[level] if level in AutonomyLevel.__members__ else AutonomyLevel.OBSERVE,
            prefill=dict(data.get("prefill", {}) or {}),
            state=state,
            created_at=created,
            expires_at=float(data.get("expires_at", 0.0) or 0.0),
        )


def proposal_from_hit(hit: TriggerHit, *, now: float | None = None) -> Proposal | None:
    """Convert a trigger hit's action descriptor into a proposal.

    Only the four graduated kinds map; anything else (notes, unknown
    kinds) stays a bare hit and returns None.
    """

    action = hit.action or {}
    try:
        tier = ProposalTier(str(action.get("kind", "")).lower())
    except ValueError:
        return None
    moment = now if now is not None else time.time()
    workflow = str(action.get("workflow", ""))
    return Proposal(
        id=new_event_id("prop"),
        tier=tier,
        title=str(action.get("title", "") or f"{tier.value}: {workflow or hit.trigger_name}"),
        body=str(action.get("body", "")),
        workflow=workflow,
        source=hit.trigger_name,
        min_autonomy=TIER_GATE[tier],
        prefill=dict(action.get("prefill", {}) or {}),
        created_at=moment,
        expires_at=moment + TIER_TTL_S[tier],
    )


class ProposalQueue:
    """Bounded store plus gated transitions for proposals."""

    def __init__(self, *, max_pending: int = MAX_PENDING) -> None:
        self.max_pending = max(1, max_pending)
        self._proposals: dict[str, Proposal] = {}

    def _settle_expired(self, now: float) -> None:
        for item in self._proposals.values():
            if item.expired(now):
                item.state = ProposalState.EXPIRED

    def _make_room(self) -> bool:
        if sum(1 for item in self._proposals.values() if not item.terminal()) < self.max_pending:
            return True
        oldest = min(
            (item for item in self._proposals.values() if not item.terminal()),
            key=lambda item: item.created_at,
        )
        if oldest.tier is ProposalTier.SUGGEST:
            oldest.state = ProposalState.DISMISSED
            return True
        return False

    def _live(self, proposal_id: str, now: float) -> Proposal | None:
        proposal = self._proposals.get(proposal_id)
        if proposal is None or proposal.terminal():
            return None
        if proposal.expired(now):
            proposal.state = ProposalState.EXPIRED
            return None
        return proposal

    def propose(
        self,
        tier: ProposalTier | str = ProposalTier.SUGGEST,
        *,
        title: str = "",
        body: str = "",
        workflow: str = "",
        source: str = "",
        prefill: dict[str, Any] | None = None,
        ttl_s: float | None = None,
        now: float | None = None,
    ) -> Proposal | None:
        """Create an inert proposal; None when the pending queue is full."""

        try:
            resolved = tier if isinstance(tier, ProposalTier) else ProposalTier(str(tier).lower())
        except ValueError:
            resolved = ProposalTier.SUGGEST
        moment = now if now is not None else time.time()
        self._settle_expired(moment)
        if not self._make_room():
            return None
        proposal = Proposal(
            id=new_event_id("prop"),
            tier=resolved,
            title=title,
            body=body,
            workflow=workflow,
            source=source,
            min_autonomy=TIER_GATE[resolved],
            prefill=dict(prefill or {}),
            created_at=moment,
            expires_at=moment + (ttl_s if ttl_s is not None else TIER_TTL_S[resolved]),
        )
        self._proposals[proposal.id] = proposal
        return proposal

    def propose_from_hit(self, hit: TriggerHit, *, now: float | None = None) -> Proposal | None:
        proposal = proposal_from_hit(hit, now=now)
        if proposal is None:
            return None
        moment = now if now is not None else time.time()
        self._settle_expired(moment)
        if not self._make_room():
            return None
        self._proposals[proposal.id] = proposal
        return proposal

    def get(self, proposal_id: str) -> Proposal | None:
        return self._proposals.get(proposal_id)

    def pending(self, tier: ProposalTier | None = None, *, now: float | None = None) -> list[Proposal]:
        self._settle_expired(now if now is not None else time.time())
        items = [item for item in self._proposals.values() if item.state == ProposalState.PENDING]
        if tier is not None:
            items = [item for item in items if item.tier is tier]
        return sorted(items, key=lambda item: item.created_at)

    def advance(
        self, proposal_id: str, autonomy: AutonomyLevel = AutonomyLevel.OBSERVE, *, now: float | None = None
    ) -> bool:
        """Move to the next tier; the final step submits. Gated per tier."""

        proposal = self._live(proposal_id, now if now is not None else time.time())
        if proposal is None:
            return False
        index = TIER_ORDER.index(proposal.tier)
        if index >= len(TIER_ORDER) - 1:
            return self.submit(proposal_id, autonomy)
        nxt = TIER_ORDER[index + 1]
        if autonomy < TIER_GATE[nxt] or autonomy < proposal.min_autonomy:
            return False
        proposal.tier = nxt
        proposal.min_autonomy = TIER_GATE[nxt]
        return True

    def submit(
        self, proposal_id: str, autonomy: AutonomyLevel = AutonomyLevel.OBSERVE, *, now: float | None = None
    ) -> bool:
        """Hand off to execution/approval; marks submitted, executes nothing."""

        proposal = self._live(proposal_id, now if now is not None else time.time())
        if proposal is None:
            return False
        if autonomy < AutonomyLevel.ACT or autonomy < proposal.min_autonomy:
            return False
        proposal.tier = ProposalTier.SUBMIT
        proposal.state = ProposalState.SUBMITTED
        return True

    def dismiss(self, proposal_id: str, *, now: float | None = None) -> bool:
        proposal = self._live(proposal_id, now if now is not None else time.time())
        if proposal is None:
            return False
        proposal.state = ProposalState.DISMISSED
        return True

    def sweep(self, now: float | None = None) -> int:
        """Expire overdue proposals; returns the expired count."""

        moment = now if now is not None else time.time()
        count = 0
        for proposal in self._proposals.values():
            if proposal.expired(moment):
                proposal.state = ProposalState.EXPIRED
                count += 1
        return count

    def __len__(self) -> int:
        return len(self._proposals)

    def to_dict(self) -> dict[str, Any]:
        return {"proposals": [item.to_dict() for item in self._proposals.values()]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProposalQueue:
        queue = cls()
        for item in (data or {}).get("proposals", []) or []:
            proposal = Proposal.from_dict(item)
            queue._proposals[proposal.id] = proposal
        return queue


__all__ = [
    "MAX_PENDING",
    "Proposal",
    "ProposalQueue",
    "ProposalState",
    "ProposalTier",
    "TIER_GATE",
    "TIER_ORDER",
    "TIER_TTL_S",
    "proposal_from_hit",
]
