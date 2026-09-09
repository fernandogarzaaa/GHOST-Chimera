"""Ghost connectors: external world -> Ghost Event Fabric.

Every connector implements connect / authenticate / subscribe / poll /
normalize / disconnect and emits normalized stealth Events. Account
connections are owned by the Custom Auth Engine (auth_engine.py) —
self-hosted OAuth2, encrypted vault, proactive refresh, direct proxy.
No third-party auth cloud involved.
"""

from __future__ import annotations

from .auth_engine import (
    PROVIDERS as AUTH_PROVIDERS,
)
from .auth_engine import (
    AuthEngineError,
    CustomAuthEngine,
    EngineAction,
    NeedsReauth,
    UnknownProvider,
)
from .base import Connector, ConnectorStatus
from .github_events import GitHubEventConnector, normalize_github_webhook
from .oauth import OAUTH_PRESETS, TokenVault, get_preset, oauth_status
from .stealth_service import (
    approve_draft,
    draft_actions,
    extract_draft_text,
    get_service_loop,
    ste_prefill,
)
from .webhooks import NORMALIZERS, normalize_webhook

__all__ = [
    "AUTH_PROVIDERS",
    "AuthEngineError",
    "Connector",
    "ConnectorStatus",
    "CustomAuthEngine",
    "EngineAction",
    "GitHubEventConnector",
    "NeedsReauth",
    "NORMALIZERS",
    "OAUTH_PRESETS",
    "TokenVault",
    "UnknownProvider",
    "approve_draft",
    "draft_actions",
    "extract_draft_text",
    "get_preset",
    "get_service_loop",
    "normalize_github_webhook",
    "normalize_webhook",
    "oauth_status",
    "ste_prefill",
]
