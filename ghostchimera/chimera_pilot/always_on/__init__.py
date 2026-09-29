"""Always-on agents: the persistent agent runtime for Ghost Chimera.

Ports the general-purpose concepts of the always-on assistant pattern onto
the ``official`` branch: an explicit agent lifecycle (sleeping / queued /
awake / completed), webhook and schedule wake triggers, stable agent
identities, durable sessions that survive restarts, automatic context
compaction with continuity, bounded subagent delegation, and
policy-controlled approval gates. The browser Ghost Console is the operator
surface.
"""

from .approvals import (
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    TERMINAL_STATUSES,
    ApprovalStore,
    ApprovalTicket,
    QueuedApprovalHandler,
)
from .compaction import DEFAULT_THRESHOLD_PERCENT, AutoCompactor
from .daemon import (
    WAKE_STATUS_COMPLETED,
    WAKE_STATUS_FAILED,
    WAKE_STATUS_QUEUED,
    WAKE_STATUS_RUNNING,
    AlwaysOnDaemon,
    LifecycleState,
    WakeRequest,
)
from .identity import AgentIdentity, IdentityStore
from .sessions import MAX_MESSAGES_PER_SESSION, DurableSession, SessionStore
from .triggers import WebhookDefinition, WebhookHandler, WebhookRegistry, render_objective_template

__all__ = [
    "AlwaysOnDaemon",
    "LifecycleState",
    "WakeRequest",
    "WAKE_STATUS_QUEUED",
    "WAKE_STATUS_RUNNING",
    "WAKE_STATUS_COMPLETED",
    "WAKE_STATUS_FAILED",
    "AgentIdentity",
    "IdentityStore",
    "DurableSession",
    "SessionStore",
    "MAX_MESSAGES_PER_SESSION",
    "AutoCompactor",
    "DEFAULT_THRESHOLD_PERCENT",
    "ApprovalTicket",
    "ApprovalStore",
    "QueuedApprovalHandler",
    "STATUS_PENDING",
    "STATUS_APPROVED",
    "STATUS_DENIED",
    "STATUS_EXPIRED",
    "TERMINAL_STATUSES",
    "WebhookRegistry",
    "WebhookDefinition",
    "WebhookHandler",
    "render_objective_template",
]
