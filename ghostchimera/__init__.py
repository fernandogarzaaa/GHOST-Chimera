"""
Ghost Chimera
============

Ghost Chimera is a local-first agent orchestration project. It provides a
modular architecture for planning, skills, tools, model providers, safety
checks, and Chimera Pilot resource orchestration.

The package is a beta release. It is a functional foundation for
experimentation and extension; it does not claim to be AGI or a secure sandbox
for untrusted code.

v0.3.0-beta closes all remaining OpenClaw parity gaps:
  - Media provider interfaces (image, TTS, web search, web fetch, vision,
    document extraction)
  - Approval flow runtime (ApprovalHandler/Policy + BEFORE_TOOL_CALL /
    AFTER_TOOL_CALL / LLM_INPUT / LLM_OUTPUT hook names)
  - Tool result middleware pipeline (ToolResultMiddleware / ToolMiddlewareChain)
  - Skill metadata enrichment (requires_env, requires_bins, check_requirements)
  - BackgroundService ABC + ServiceRegistry
  - HTTP route registry in GatewayServer
  - Plugin manifest format (PluginManifest / PluginLoader)
  - ExternalAuthProvider ABC wired into CredentialPool
  - SSRF / network policy dispatcher (SSRFPolicy / NetworkDispatcher)
  - PROVIDERS split by type (TEXT_PROVIDERS / MEDIA_PROVIDERS)
"""

from __future__ import annotations

__version__ = "0.3.0-beta"
__release_phase__ = "beta"

__all__ = ["__version__", "__release_phase__"]
