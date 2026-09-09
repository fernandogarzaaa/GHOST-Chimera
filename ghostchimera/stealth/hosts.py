"""Host adapters: Ghost's universal event model <-> host-native lifecycles.

The universal protocol is Ghost-internal (Event / ContextPackage /
Intervention). Host specifics (Claude hooks, OpenClaw context engines,
OpenCode plugins) are implementation details of each adapter. Transport
(API/IPC) stays separate from domain logic — adapters talk to
StealthLoop directly in-process or over localhost HTTP.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .events import Event, new_event
from .intervention import InterventionOutcome
from .loop import StealthLoop
from .stealth_policy import Decision


class HostAdapter:
    """Universal host contract (spec section 15)."""

    id: str = "base"
    name: str = "Base host adapter"

    def __init__(self, loop: StealthLoop) -> None:
        self.loop = loop

    # -- lifecycle ------------------------------------------------------
    def detect(self) -> bool:
        """True when this host's CLI/config is present on this machine."""
        return False

    def install(self) -> dict[str, Any]:
        """Return host-native install artifacts (config snippets, scripts)."""
        return {"host": self.id, "installed": False, "reason": "not implemented"}

    def subscribe(self) -> None:
        """Attach to the host's event stream (webhook, tail, poll...)."""

    # -- observation ------------------------------------------------------
    def observe_session(self, session: dict[str, Any]) -> str:
        """Map a host session lifecycle moment to a Ghost agent.* event.
        Returns the decision name for the emitted event."""
        kind = str(session.get("kind", "prompt"))
        mapping = {
            "started": "agent.session_started",
            "prompt": "agent.prompt_submitted",
            "tool": "agent.tool_called",
            "response": "agent.response_completed",
            "ended": "agent.session_ended",
        }
        event = new_event(
            mapping.get(kind, "agent.prompt_submitted"),
            source=self.id,
            actor=str(session.get("actor", "")),
            payload={k: v for k, v in session.items() if k != "kind"},
            session_id=str(session.get("session_id", "")),
            confidence=0.9,
        )
        self.loop.emit(event)
        result = self.loop.last_result
        return str(result.decision) if result else Decision.NONE.value

    def observe_tool_call(self, session_id: str, tool: str, args: dict[str, Any]) -> str:
        return self.observe_session({"kind": "tool", "session_id": session_id,
                                     "tool": tool, "args": args})

    def observe_outcome(self, intervention_id: str, outcome: str) -> None:
        self.loop.observe_outcome(intervention_id, InterventionOutcome(outcome))

    # -- injection ----------------------------------------------------------
    def inject_context(self, intervention_id: str) -> str:
        """Render prepared context for this host. Returns host-ready text."""
        return self.loop.inject(intervention_id, host=self.id)

    # -- /ghost UX convention (spec section 16) ------------------------------
    def handle_command(self, text: str) -> str:
        parts = text.strip().split()
        if not parts or parts[0] != "/ghost":
            return ""
        verb = parts[1] if len(parts) > 1 else ""
        if verb in ("", "status"):
            stats = self.loop.bus.processed, len(self.loop.interventions)
            return (f"Ghost running — events processed: {stats[0]}, "
                    f"interventions: {stats[1]}, autonomy: {self.loop.policy.autonomy.name}")
        if verb == "pause":
            self.loop.policy.enabled = False
            return "Ghost paused. Background observation stopped; host unaffected."
        if verb == "resume":
            self.loop.policy.enabled = True
            return "Ghost resumed."
        if verb == "workflows":
            hyps = self.loop.learner.hypotheses()[:5]
            if not hyps:
                return "No workflows learned yet. Ghost is still observing."
            return "Learned workflows:\n" + "\n".join(
                f"- {h.name} (support={h.support}, conf={h.confidence:.2f})" for h in hyps)
        if verb == "interventions":
            if not self.loop.interventions:
                return "No interventions yet."
            lines = []
            for i in list(self.loop.interventions.values())[-5:]:
                lines.append(f"- {i.id} [{i.state}] {i.workflow} conf={i.confidence:.2f}")
            return "\n".join(lines)
        if verb == "explain":
            target = parts[2] if len(parts) > 2 else ""
            interventions = self.loop.interventions
            item = interventions.get(target) if target else (list(interventions.values())[-1] if interventions else None)
            if item is None:
                return "Nothing to explain yet."
            exp = item.explain()
            return (f"Intervention {exp['id']}: {exp['why']} | trigger={exp['trigger_event']} "
                    f"workflow={exp['workflow']} conf={exp['confidence']:.2f} "
                    f"state={exp['state']} outcome={exp['outcome']}")
        if verb == "memory":
            snap = self.loop.graph.snapshot()
            return (f"Experience: {snap['nodes']} nodes, {snap['edges']} edges. "
                    f"World facts: {len(self.loop.world.active_facts())}.")
        return "Unknown /ghost command. Try: status, memory, workflows, interventions, explain, pause, resume."


@dataclass
class AdapterRegistry:
    adapters: dict[str, HostAdapter] = field(default_factory=dict)

    def register(self, adapter: HostAdapter) -> None:
        self.adapters[adapter.id] = adapter

    def detect_all(self) -> dict[str, bool]:
        return {aid: adapter.detect() for aid, adapter in self.adapters.items()}


class ClaudeCodeAdapter(HostAdapter):
    """Claude Code via lifecycle hooks (UserPromptSubmit et al).

    Install emits a settings.json snippet wiring `ghost-hook` as a
    UserPromptSubmit/SessionStart/SessionEnd command hook. The hook
    handler (`handle_hook_input`) maps Claude's stdin JSON to Ghost
    agent.* events and returns Claude's expected stdout JSON with
    `additionalContext` when Ghost has something prepared — the user
    never copy-pastes memory.
    """

    id = "claude"
    name = "Claude Code"

    def detect(self) -> bool:
        import shutil

        return shutil.which("claude") is not None

    def install(self) -> dict[str, Any]:
        return {
            "host": self.id,
            "settings_snippet": {
                "hooks": {
                    "UserPromptSubmit": [{"matcher": "", "hooks": [
                        {"type": "command", "command": "ghost-hook prompt"}]}],
                    "SessionStart": [{"matcher": "", "hooks": [
                        {"type": "command", "command": "ghost-hook start"}]}],
                    "SessionEnd": [{"matcher": "", "hooks": [
                        {"type": "command", "command": "ghost-hook end"}]}],
                }
            },
            "note": "Merge into ~/.claude/settings.json; ghost-hook reads hook JSON on stdin.",
        }

    def handle_hook_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Claude hook protocol in -> hook JSON out (pure function, tested)."""
        hook_event = str(payload.get("hook_event_name") or payload.get("hookEventName") or "")
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "")
        prompt = str(payload.get("prompt", ""))
        if prompt.startswith("/ghost"):
            return {"systemMessage": self.handle_command(prompt)}
        kind = {"UserPromptSubmit": "prompt", "SessionStart": "started",
                "SessionEnd": "ended", "PreToolUse": "tool",
                "PostToolUseResponse": "response"}.get(hook_event, "prompt")
        decision = self.observe_session({"kind": kind, "session_id": session_id,
                                         "prompt": prompt[:2000], "relevance": 0.8,
                                         "confidence": 0.85, "benefit": 0.7})
        if decision not in (Decision.PREPARE.value, Decision.INJECT.value):
            return {}
        result = self.loop.last_result
        if result is None or not result.intervention_id:
            return {}
        # Wait briefly for background preparation; fall back to sync prepare.
        intervention = self.loop.interventions[result.intervention_id]
        from .intervention import InterventionState

        for _ in range(40):
            if intervention.state == InterventionState.READY:
                break
            time.sleep(0.05)
        if intervention.state != InterventionState.READY:
            self.loop._prepare(intervention, Event.from_dict(
                {"event_id": result.event_id, "event_type": "agent.prompt_submitted",
                 "timestamp": time.time(), "source": "claude"}))
        markdown = self.inject_context(result.intervention_id)
        return {"hookSpecificOutput": {"hookEventName": hook_event or "UserPromptSubmit",
                                       "additionalContext": markdown}}


class OpenClawAdapter(HostAdapter):
    """OpenClaw via its context-engine lifecycle (ingest/assemble/after-turn)."""

    id = "openclaw"
    name = "OpenClaw"

    def detect(self) -> bool:
        import shutil

        return shutil.which("openclaw") is not None

    def assemble(self, session: dict[str, Any]) -> dict[str, Any]:
        """Context-engine `assemble` hook: observe + return prepared context."""
        self.observe_session({"kind": "prompt", **session})
        result = self.loop.last_result
        if result is None or not result.intervention_id:
            return {"context": "", "intervention_id": ""}
        intervention = self.loop.interventions[result.intervention_id]
        from .intervention import InterventionState

        if intervention.state != InterventionState.READY:
            return {"context": "", "intervention_id": result.intervention_id, "status": "preparing"}
        return {"context": self.inject_context(result.intervention_id),
                "intervention_id": result.intervention_id, "status": "ready"}

    def after_turn(self, session: dict[str, Any], *, useful: bool) -> None:
        intervention_id = str(session.get("intervention_id", ""))
        if intervention_id and intervention_id in self.loop.interventions:
            self.observe_outcome(intervention_id,
                                 InterventionOutcome.USEFUL.value if useful else InterventionOutcome.IGNORED.value)


class OpenCodeAdapter(HostAdapter):
    """OpenCode via plugin/MCP surface (event mapping + command passthrough)."""

    id = "opencode"
    name = "OpenCode"

    def detect(self) -> bool:
        import shutil

        return shutil.which("opencode") is not None


class CodexAdapter(HostAdapter):
    """Codex via plugin/MCP surface + prompt bridging.

    Codex exposes skills, MCP servers, and optional UI through plugins —
    no Claude-style stdin/stdout hook protocol — so this adapter maps
    Ghost interventions to a Codex plugin context block and translates
    Codex session events (prompt/tool/result) into Ghost agent.* events.
    """

    id = "codex"
    name = "Codex"

    def detect(self) -> bool:
        import shutil

        return shutil.which("codex") is not None

    def install(self) -> dict[str, Any]:
        return {
            "host": self.id,
            "plugin": {
                "name": "ghost",
                "skills": ["ghost-context"],
                "mcp": {"ghost": {"command": "ghost-hook", "args": ["mcp"]}},
                "slash": {"/ghost": "Ghost status, memory, and workflow commands"},
            },
            "note": "Register the ghost plugin with Codex; context blocks come from inject_context().",
        }

    def context_block(self, intervention_id: str) -> str:
        """Plugin context block prepended to the Codex session prompt."""
        markdown = self.inject_context(intervention_id)
        return f"<ghost-context>\n{markdown}\n</ghost-context>"


class GeminiAdapter(HostAdapter):
    """Gemini CLI via extensions (MCP servers, commands, hooks, skills).

    install() emits a Gemini extension manifest wiring a PreToolUse-style
    hook to `ghost-hook`; handle_hook_input() speaks the extension hook
    JSON dialect (eventName/sessionId/prompt in, contextOut or {} out).
    """

    id = "gemini"
    name = "Gemini CLI"

    def detect(self) -> bool:
        import shutil

        return shutil.which("gemini") is not None

    def install(self) -> dict[str, Any]:
        return {
            "host": self.id,
            "extension": {
                "name": "ghost",
                "version": "0.1.0",
                "hooks": {
                    "before_prompt": {"command": "ghost-hook gemini-prompt"},
                    "after_tool": {"command": "ghost-hook gemini-tool"},
                },
                "commands": ["/ghost"],
            },
            "note": "Drop into the Gemini extensions dir; hooks POST hook JSON to ghost-hook.",
        }

    def handle_hook_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = str(payload.get("eventName") or payload.get("event_name") or "")
        session_id = str(payload.get("sessionId") or payload.get("session_id") or "")
        prompt = str(payload.get("prompt", ""))
        if prompt.startswith("/ghost"):
            return {"messageOut": self.handle_command(prompt)}
        kind = {"before_prompt": "prompt", "after_tool": "tool",
                "session_start": "started", "session_end": "ended"}.get(event, "prompt")
        decision = self.observe_session({"kind": kind, "session_id": session_id,
                                         "prompt": prompt[:2000], "relevance": 0.8,
                                         "confidence": 0.85, "benefit": 0.7})
        if decision not in (Decision.PREPARE.value, Decision.INJECT.value):
            return {}
        result = self.loop.last_result
        if result is None or not result.intervention_id:
            return {}
        intervention = self.loop.interventions[result.intervention_id]
        from .intervention import InterventionState

        for _ in range(40):
            if intervention.state == InterventionState.READY:
                break
            time.sleep(0.05)
        if intervention.state != InterventionState.READY:
            return {}
        return {"contextOut": self.inject_context(result.intervention_id)}


class HermesAdapter(HostAdapter):
    """Hermes Agent via its memory-provider interface.

    Hermes prefetches relevant memory in the background before turns, so
    this adapter is query-shaped: prefetch() observes the turn event and
    returns prepared context (or "" while preparing), and report() feeds
    the outcome back into Ghost's learning loop.
    """

    id = "hermes"
    name = "Hermes Agent"

    def detect(self) -> bool:
        import shutil

        return shutil.which("hermes") is not None

    def install(self) -> dict[str, Any]:
        return {
            "host": self.id,
            "memory_provider": {
                "name": "ghost",
                "capabilities": ["prefetch", "submit_feedback"],
                "endpoint": "local ghost transport /query_context",
            },
            "note": "Register ghost as an external memory provider; Hermes calls prefetch() per turn.",
        }

    def prefetch(self, session: dict[str, Any]) -> str:
        """Background memory prefetch for an upcoming Hermes turn."""
        self.observe_session({"kind": "prompt", **session})
        result = self.loop.last_result
        if result is None or not result.intervention_id:
            return ""
        intervention = self.loop.interventions[result.intervention_id]
        from .intervention import InterventionState

        if intervention.state != InterventionState.READY:
            return ""
        return self.inject_context(result.intervention_id)

    def report(self, intervention_id: str, *, useful: bool) -> None:
        self.observe_outcome(
            intervention_id,
            InterventionOutcome.USEFUL.value if useful else InterventionOutcome.IGNORED.value,
        )


__all__ = ["AdapterRegistry", "ClaudeCodeAdapter", "CodexAdapter", "GeminiAdapter",
           "HermesAdapter", "HostAdapter", "OpenClawAdapter", "OpenCodeAdapter"]
