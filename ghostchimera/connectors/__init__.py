"""Ghost connectors: external world -> Ghost Event Fabric.

Every connector implements connect / authenticate / subscribe / poll /
normalize / disconnect and emits normalized stealth Events. No
connector-specific logic may leak into the StealthLoop.
"""

from __future__ import annotations

from .base import Connector, ConnectorStatus
from .github_events import GitHubEventConnector, normalize_github_webhook
from .nango import NANGO_CATALOG, NangoAction, NangoClient, NangoError
from .nango_events import NangoInboxConnector
from .stealth_service import (
    approve_draft,
    draft_actions,
    extract_draft_text,
    get_service_loop,
    ste_prefill,
)
from .oauth import OAUTH_PRESETS, TokenVault, get_preset, oauth_status

__all__ = [
    "Connector",
    "ConnectorStatus",
    "GitHubEventConnector",
    "NANGO_CATALOG",
    "NangoAction",
    "NangoClient",
    "NangoError",
    "NangoInboxConnector",
    "approve_draft",
    "OAUTH_PRESETS",
    "TokenVault",
    "approve_draft",
    "draft_actions",
    "get_preset",
    "get_service_loop",
    "normalize_github_webhook",
    "extract_draft_text",
    "oauth_status",
    "ste_prefill",
]
