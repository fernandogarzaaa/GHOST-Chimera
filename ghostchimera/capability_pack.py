"""Built-in Chimera Capability Pack.

The pack exposes deterministic Ghost-native tools that do not require external
MCP servers.  It gives operators the practical benefits of the adjacent
Chimera projects while keeping Ghost Chimera self-contained.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from .chimera_pilot.context_compressor import compress_text_query_aware
from .cognition_layer.trust import GhostBelief, guard_belief, pack_handoff, summarize_operational_trace, verify_handoff
from .mcp.normalization import normalize_mcp_server_entry
from .model_layer.local_model_inventory import discover_local_model_inventory, resolve_model_source


@dataclass(frozen=True)
class CapabilityPackTool:
    id: str
    name: str
    description: str
    category: str
    external_dependency_required: bool = False
    consent_required: bool = False
    side_effects: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_capability_tools() -> list[CapabilityPackTool]:
    return [
        CapabilityPackTool("ghost.guard", "Confidence Guard", "Checks confidence and variance before promotion.", "cognition"),
        CapabilityPackTool("ghost.compress", "Query-Aware Compression", "Compresses context with code-block preservation.", "latency"),
        CapabilityPackTool("ghost.handoff_pack", "Pack Handoff", "Creates a tamper-evident subsystem handoff.", "provenance"),
        CapabilityPackTool("ghost.handoff_verify", "Verify Handoff", "Verifies a Ghost handoff hash and payload.", "provenance"),
        CapabilityPackTool(
            "ghost.local_model_inventory",
            "Local Model Inventory",
            "Previews local GGUF/SafeTensors model files.",
            "models",
            consent_required=True,
        ),
        CapabilityPackTool("ghost.local_model_resolve", "Resolve Model Source", "Classifies HF/local model sources.", "models"),
        CapabilityPackTool("ghost.normalize_mcp", "Normalize MCP Entry", "Sanitizes MCP server capability metadata.", "mcp"),
        CapabilityPackTool("ghost.operational_trace", "Operational Trace", "Shows safe execution stages without chain-of-thought.", "cognition"),
    ]


def call_capability_tool(tool_id: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = dict(arguments or {})
    handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "ghost.guard": _tool_guard,
        "ghost.compress": _tool_compress,
        "ghost.handoff_pack": _tool_handoff_pack,
        "ghost.handoff_verify": _tool_handoff_verify,
        "ghost.local_model_inventory": _tool_local_model_inventory,
        "ghost.local_model_resolve": _tool_local_model_resolve,
        "ghost.normalize_mcp": _tool_normalize_mcp,
        "ghost.operational_trace": _tool_operational_trace,
    }
    handler = handlers.get(str(tool_id))
    if not handler:
        return {"ok": False, "error": f"Unknown capability tool: {tool_id}"}
    try:
        return {"ok": True, "tool_id": tool_id, "result": _redact(handler(args))}
    except Exception as exc:
        return {"ok": False, "tool_id": tool_id, "error": str(exc)}


def _tool_guard(args: dict[str, Any]) -> dict[str, Any]:
    belief = GhostBelief.from_confidence(
        str(args.get("value") or "candidate"),
        float(args.get("confidence", 0.0)),
        variance=float(args.get("variance", 0.0)),
        source=str(args.get("source") or "capability_pack"),
    )
    return guard_belief(
        belief,
        max_risk=float(args.get("max_risk", 0.2)),
        max_variance=float(args.get("max_variance", 0.05)),
    ).to_dict()


def _tool_compress(args: dict[str, Any]) -> dict[str, Any]:
    return compress_text_query_aware(
        str(args.get("text") or ""),
        focus=str(args.get("focus") or ""),
        budget_tokens=int(args.get("budget_tokens") or 800),
    ).to_dict()


def _tool_handoff_pack(args: dict[str, Any]) -> dict[str, Any]:
    handoff = pack_handoff(
        sender=str(args.get("sender") or "ghost"),
        receiver=str(args.get("receiver") or "operator"),
        tool=str(args.get("tool") or "ghost.guard"),
        args=args.get("args") if isinstance(args.get("args"), dict) else {},
        payload=args.get("payload") if isinstance(args.get("payload"), dict) else {},
        summary_text=str(args.get("summary_text") or "Ghost handoff"),
        metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else {},
    )
    return handoff.to_dict()


def _tool_handoff_verify(args: dict[str, Any]) -> dict[str, Any]:
    from .cognition_layer.trust import GhostHandoff

    raw = args.get("handoff")
    handoff = GhostHandoff.from_json(raw) if isinstance(raw, str) else GhostHandoff(**raw)
    return verify_handoff(handoff).to_dict()


def _tool_local_model_inventory(args: dict[str, Any]) -> dict[str, Any]:
    roots = args.get("roots") if isinstance(args.get("roots"), list) else None
    return discover_local_model_inventory(roots)


def _tool_local_model_resolve(args: dict[str, Any]) -> dict[str, Any]:
    return resolve_model_source(str(args.get("source") or ""), license_id=str(args.get("license_id") or "")).to_dict()


def _tool_normalize_mcp(args: dict[str, Any]) -> dict[str, Any]:
    return normalize_mcp_server_entry(
        str(args.get("server_id") or "mcp-server"),
        args.get("details") if isinstance(args.get("details"), dict) else {},
        source_path=args.get("source_path") or None,
    )


def _tool_operational_trace(args: dict[str, Any]) -> dict[str, Any]:
    return summarize_operational_trace(
        goal=str(args.get("goal") or "operator request"),
        sources=[str(item) for item in args.get("sources", [])] if isinstance(args.get("sources"), list) else [],
        policy_decision=str(args.get("policy_decision") or "approval_required"),
        tool_candidates=[str(item) for item in args.get("tool_candidates", [])]
        if isinstance(args.get("tool_candidates"), list)
        else [],
    )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("token", "secret", "api_key", "password", "authorization")):
                result[str(key)] = "[redacted]" if item else ""
            else:
                result[str(key)] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


__all__ = ["CapabilityPackTool", "call_capability_tool", "list_capability_tools"]
