"""Phase 5b tests: Codex, Gemini, Hermes adapters."""

from __future__ import annotations

from ghostchimera.stealth import (
    AutonomyLevel,
    CodexAdapter,
    GeminiAdapter,
    GhostPolicy,
    HermesAdapter,
    StealthLoop,
)
from ghostchimera.stealth.context import ContextFabric, ContextItem, InMemoryRetriever
from ghostchimera.stealth.intervention import InterventionState


def _loop() -> StealthLoop:
    policy = GhostPolicy(autonomy=AutonomyLevel.INJECT)
    fabric = ContextFabric(retrievers=[InMemoryRetriever([
        ContextItem(source="memory:episodic", kind="memory",
                    text="Moovsoon proposal context for Alex", score=0.9,
                    confidence=0.9, provenance={"origin": "test"}),
    ])])
    return StealthLoop(policy=policy, fabric=fabric)


def _train(adapter, n: int = 4) -> None:
    for _ in range(n):
        adapter.observe_session({"kind": "prompt", "session_id": "s",
                                 "relevance": 0.95, "confidence": 0.93, "benefit": 0.9})


def test_codex_plugin_and_context_block() -> None:
    loop = _loop()
    try:
        adapter = CodexAdapter(loop)
        manifest = adapter.install()
        assert manifest["plugin"]["skills"] == ["ghost-context"]
        assert "/ghost" in manifest["plugin"]["slash"]
        _train(adapter)
        decision = adapter.observe_session({"kind": "prompt", "session_id": "s",
                                            "relevance": 0.95, "confidence": 0.93,
                                            "benefit": 0.9})
        assert decision in ("prepare", "inject")
        result = loop.last_result
        assert result is not None and result.intervention_id
        block = adapter.context_block(result.intervention_id)
        assert block.startswith("<ghost-context>") and "Moovsoon" in block
    finally:
        loop.close()


def test_gemini_extension_hook() -> None:
    loop = _loop()
    try:
        adapter = GeminiAdapter(loop)
        assert "ghost" in adapter.install()["extension"]["name"]
        _train(adapter)
        out = adapter.handle_hook_input({"eventName": "before_prompt", "sessionId": "s",
                                         "prompt": "work on Moovsoon"})
        assert "contextOut" in out and "Moovsoon" in out["contextOut"]
        out2 = adapter.handle_hook_input({"eventName": "before_prompt", "sessionId": "s",
                                          "prompt": "/ghost status"})
        assert "Ghost running" in out2.get("messageOut", "")
        assert isinstance(adapter.detect(), bool)
    finally:
        loop.close()


def test_hermes_prefetch_and_report() -> None:
    loop = _loop()
    try:
        adapter = HermesAdapter(loop)
        assert adapter.install()["memory_provider"]["name"] == "ghost"
        _train(adapter)
        context = adapter.prefetch({"session_id": "s", "relevance": 0.95,
                                    "confidence": 0.93, "benefit": 0.9})
        assert "Moovsoon" in context
        result = loop.last_result
        assert result is not None and result.intervention_id
        # Prefetch consumes the preparation into the host turn.
        assert loop.interventions[result.intervention_id].state == InterventionState.INJECTED
        adapter.report(result.intervention_id, useful=True)
        assert loop.graph.workflow_score(
            loop.interventions[result.intervention_id].workflow) > 0.5
        # Cold prefetch with no history stays silent.
        loop2 = StealthLoop()
        try:
            assert HermesAdapter(loop2).prefetch({"session_id": "z"}) == ""
        finally:
            loop2.close()
    finally:
        loop.close()
