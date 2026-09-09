"""Phase 5 tests: HostAdapter contract, Claude hooks, /ghost, transport."""

from __future__ import annotations

import json
import urllib.request

import pytest

from ghostchimera.stealth import (
    AutonomyLevel,
    GhostPolicy,
    StealthLoop,
    new_event,
)
from ghostchimera.stealth.context import ContextFabric, ContextItem, InMemoryRetriever
from ghostchimera.stealth.hosts import (
    AdapterRegistry,
    ClaudeCodeAdapter,
    HostAdapter,
    OpenClawAdapter,
    OpenCodeAdapter,
)
from ghostchimera.stealth.transport import GhostTransport


def _loop() -> StealthLoop:
    policy = GhostPolicy.conservative_default()
    policy.autonomy = AutonomyLevel.INJECT
    fabric = ContextFabric(retrievers=[InMemoryRetriever([
        ContextItem(source="memory:episodic", kind="memory",
                    text="Moovsoon proposal context for Alex", score=0.9,
                    confidence=0.9, provenance={"origin": "test"}),
    ])])
    return StealthLoop(policy=policy, fabric=fabric)


def test_base_adapter_session_mapping_and_commands() -> None:
    loop = _loop()
    try:
        adapter = HostAdapter(loop)
        for kind in ("started", "prompt", "tool", "response", "ended"):
            decision = adapter.observe_session({"kind": kind, "session_id": "s1"})
            assert isinstance(decision, str)
        assert loop.bus.processed == 5
        assert "Ghost running" in adapter.handle_command("/ghost status")
        assert "paused" in adapter.handle_command("/ghost pause").lower()
        assert loop.policy.enabled is False
        # Paused loop stays silent.
        adapter.observe_session({"kind": "prompt", "session_id": "s1"})
        assert "resumed" in adapter.handle_command("/ghost resume").lower()
        assert "Unknown" in adapter.handle_command("/ghost frobnicate")
        assert adapter.handle_command("hello") == ""
    finally:
        loop.close()


def test_claude_hook_injects_prepared_context() -> None:
    loop = _loop()
    try:
        adapter = ClaudeCodeAdapter(loop)
        snippet = adapter.install()["settings_snippet"]
        assert "UserPromptSubmit" in snippet["hooks"]
        # Train a workflow so the hook has something to prepare.
        for _ in range(4):
            adapter.observe_session({"kind": "prompt", "session_id": "s",
                                     "relevance": 0.95, "confidence": 0.93, "benefit": 0.9})
        out = adapter.handle_hook_input({"hook_event_name": "UserPromptSubmit",
                                         "session_id": "s", "prompt": "Let's work on Moovsoon"})
        assert "hookSpecificOutput" in out
        assert "Moovsoon" in out["hookSpecificOutput"]["additionalContext"]
        # /ghost passthrough inside the hook.
        out2 = adapter.handle_hook_input({"hook_event_name": "UserPromptSubmit",
                                          "session_id": "s", "prompt": "/ghost status"})
        assert "Ghost running" in out2.get("systemMessage", "")
        # Fresh loop, weak history: hook still responds structurally (the
        # hardcoded per-prompt signals are evaluator-gated, cap-bound).
        loop2 = StealthLoop()
        try:
            out3 = ClaudeCodeAdapter(loop2).handle_hook_input(
                {"hook_event_name": "UserPromptSubmit", "session_id": "z", "prompt": "hi"})
            assert isinstance(out3, dict)
            assert out3 == {} or "hookSpecificOutput" in out3
        finally:
            loop2.close()
    finally:
        loop.close()


def test_openclaw_assemble_and_feedback() -> None:
    loop = _loop()
    try:
        adapter = OpenClawAdapter(loop)
        for _ in range(4):
            adapter.observe_session({"kind": "prompt", "session_id": "s",
                                     "relevance": 0.95, "confidence": 0.93, "benefit": 0.9})
        res = adapter.assemble({"session_id": "s", "goal": "work on Moovsoon",
                                  "relevance": 0.9, "confidence": 0.9, "benefit": 0.85})
        assert res["intervention_id"]
        # PREPARE is asynchronous: poll for readiness, then inject.
        import time

        from ghostchimera.stealth.intervention import InterventionState

        iid = res["intervention_id"]
        for _ in range(100):
            if loop.interventions[iid].state == InterventionState.READY:
                break
            time.sleep(0.05)
        assert loop.interventions[iid].state == InterventionState.READY
        context = adapter.inject_context(iid)
        assert "Moovsoon" in context
        adapter.after_turn({"intervention_id": iid}, useful=True)
        assert loop.graph.workflow_score(
            loop.interventions[iid].workflow) > 0.5
    finally:
        loop.close()


def test_registry_detect_all() -> None:
    loop = _loop()
    try:
        registry = AdapterRegistry()
        registry.register(ClaudeCodeAdapter(loop))
        registry.register(OpenCodeAdapter(loop))
        detected = registry.detect_all()
        assert set(detected) == {"claude", "opencode"}
        assert all(isinstance(v, bool) for v in detected.values())
    finally:
        loop.close()


def _post(url: str, payload: dict, token: str = "") -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("X-Ghost-Token", token)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def _get(url: str, token: str = "") -> dict:
    req = urllib.request.Request(url)
    if token:
        req.add_header("X-Ghost-Token", token)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def test_transport_round_trip() -> None:
    loop = _loop()
    transport = GhostTransport(loop)
    url = transport.start()
    try:
        event = new_event("email.received", source="gmail", actor="alex",
                          payload={"relevance": 0.95, "confidence": 0.93, "benefit": 0.9},
                          confidence=0.93)
        r1 = _post(url + "/emit", {"event": event.to_dict()})
        assert r1["ok"] and r1["decision"] in ("prepare", "inject")
        r2 = _post(url + "/query_context", {"event": event.to_dict(), "host": "claude"})
        assert "Moovsoon" in r2["markdown"]
        status = _get(url + "/status")
        assert status["events_processed"] >= 1
        if r1["intervention_id"]:
            exp = _get(url + f"/explain?id={r1['intervention_id']}")
            assert exp["ok"] and "why" in exp["explanation"]
            # Outcome via transport; wait for background prep first.
            import time

            for _ in range(100):
                if loop.interventions[r1["intervention_id"]].state.name == "READY":
                    break
                time.sleep(0.05)
            # INJECT-ready interventions record outcomes after inject.
            loop.inject(r1["intervention_id"], host="claude")
            r3 = _post(url + f"/outcome/{r1['intervention_id']}", {"outcome": "useful"})
            assert r3["recorded"] is True
    finally:
        transport.stop()
        loop.close()


def test_transport_auth_and_unknown_routes() -> None:
    import urllib.error

    loop = _loop()
    transport = GhostTransport(loop, token="s3cret")
    url = transport.start()
    try:
        with pytest.raises(urllib.error.URLError):
            _post(url + "/emit", {"event": new_event("x.y", source="t").to_dict()})
        r = _post(url + "/emit", {"event": new_event("x.y", source="t").to_dict()}, token="s3cret")
        assert r["ok"]
        with pytest.raises(urllib.error.URLError):
            _get(url + "/nope", token="s3cret")
    finally:
        transport.stop()
        loop.close()
