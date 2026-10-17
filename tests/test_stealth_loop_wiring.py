"""Wiring tests for the Stealth Loop event pipeline (testteeth gapfill).

Drives StealthLoop with fake cloud collaborators in sync mode and asserts
the observable wiring the mutation run proved unnoticed: session-history
bounds, minimal/full update paths, Nemotron UNDERSTAND/PREDICT gating,
web-grounding gating, cloud result attachment, restore_from_store,
last_result, close, and the small unit helpers.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from ghostchimera.stealth import new_event
from ghostchimera.stealth.attention import AttentionSignal
from ghostchimera.stealth.eve_model import PerceptionLevel
from ghostchimera.stealth.loop import (
    NEMOTRON_PREDICT_CONFIDENCE_THRESHOLD,
    NEMOTRON_PREDICT_MIN_INTERVAL_S,
    LoopResult,
    StealthLoop,
    _cloud_key,
    _CloudSlot,
    _env_float,
    _payload_unit,
)
from ghostchimera.stealth.stealth_policy import Decision
from ghostchimera.stealth.workflow_learner import WorkflowHypothesis


class FakeReasoner:
    available = True

    def __init__(self) -> None:
        self.understand_calls: list = []
        self.predict_calls: list = []

    def understand(self, event: Any, hypothesis: Any = None, predictions: Any = None) -> dict:
        self.understand_calls.append(event)
        return {"intent": "test-intent"}

    def predict_next(self, history_text: str, hypothesis: str = "") -> list:
        self.predict_calls.append(history_text)
        return [{"action": "act-x", "probability": 0.4}]

    def last_call(self) -> dict:
        return {"usage": {"total_tokens": 12}}


class FakeGrounding:
    available = True

    def __init__(self, result: Any = None) -> None:
        self.calls: list = []
        self._result = {"grounded": True} if result is None else result

    def ground_event(self, event: Any) -> Any:
        self.calls.append(event)
        return self._result


class FakeStore:
    def __init__(self) -> None:
        self.events: list = []
        self.interventions: list = []

    def record_event(self, event: Any) -> None:
        self.events.append(event)

    def record_intervention(self, intervention: Any) -> None:
        self.interventions.append(intervention)

    def load_interventions(self, states: Any) -> list:
        return []

    def load_workflows(self) -> list:
        return []

    def count_events(self) -> int:
        return 0


def _loop(**kw: Any) -> StealthLoop:
    kw.setdefault("cloud_mode", "sync")
    loop = StealthLoop(**kw)
    return loop


def _weak_signal() -> AttentionSignal:
    return AttentionSignal(should_attend=False, level=PerceptionLevel.EVENT, reason="weak", confidence=0.1, urgency=0.1)


def _strong_signal() -> AttentionSignal:
    return AttentionSignal(
        should_attend=True, level=PerceptionLevel.EVENT, reason="strong", confidence=0.9, urgency=0.8
    )


def _spy(loop: StealthLoop, *names: str) -> dict[str, mock.Mock]:
    spies = {}
    for dotted in names:
        obj, attr = dotted.rsplit(".", 1)
        target = loop
        for part in obj.split("."):
            target = getattr(target, part)
        original = getattr(target, attr)
        spy = mock.Mock(wraps=original)
        setattr(target, attr, spy)
        spies[dotted] = spy
    return spies


@pytest.fixture()
def closed_loop():
    loops: list[StealthLoop] = []
    yield loops.append
    for loop in loops:
        loop.close()


# ---------------------------------------------------------------------------
# Module constants and small helpers
# ---------------------------------------------------------------------------


def test_predict_gating_constants() -> None:
    assert NEMOTRON_PREDICT_CONFIDENCE_THRESHOLD == 0.6
    assert NEMOTRON_PREDICT_MIN_INTERVAL_S == 30.0


def test_env_float_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GC_T_LOOP_FLOAT", raising=False)
    assert _env_float("GC_T_LOOP_FLOAT", 9.0) == 9.0
    monkeypatch.setenv("GC_T_LOOP_FLOAT", "abc")
    assert _env_float("GC_T_LOOP_FLOAT", 9.0) == 9.0
    monkeypatch.setenv("GC_T_LOOP_FLOAT", "-5")
    assert _env_float("GC_T_LOOP_FLOAT", 9.0) == 0.0
    monkeypatch.setenv("GC_T_LOOP_FLOAT", "2.5")
    assert _env_float("GC_T_LOOP_FLOAT", 9.0) == 2.5


def test_payload_unit_shapes() -> None:
    assert _payload_unit(None, "confidence", 0.25) == 0.25
    assert _payload_unit({"other": 1}, "confidence", 0.25) == 0.25
    assert _payload_unit({"confidence": None}, "confidence", 0.25) == 0.25
    assert _payload_unit({"confidence": "high"}, "confidence", 0.0) == 0.8
    assert _payload_unit({"confidence": "junk"}, "confidence", "junk-default") == 0.0
    # garbage outer default still falls back to 0.0, never 1.0
    assert _payload_unit("junk-default", "confidence", "junk-default") == 0.0


def test_cloud_key_deterministic() -> None:
    a = _cloud_key("understand", "email.received")
    assert _cloud_key("understand", "email.received") == a
    assert len(a) == 64
    assert _cloud_key("predict", "email.received") != a


# ---------------------------------------------------------------------------
# Constructor wiring
# ---------------------------------------------------------------------------


def test_init_registers_three_computer_providers(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    modalities = set(loop.computer._providers.keys())
    assert len(modalities) == 3


def test_init_own_runtime_defaults_true(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    assert loop._own_runtime is True


def test_init_explicit_runtime_not_owned(closed_loop) -> None:
    from ghostchimera.stealth.runtime import BackgroundRuntime

    runtime = BackgroundRuntime()
    loop = _loop(runtime=runtime, own_runtime=True)
    closed_loop(loop)
    assert loop._own_runtime is False
    assert loop.runtime is runtime
    runtime.stop()


def test_init_results_max_default(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    assert loop._results_max == 256


def test_init_computer_capability_passthrough(closed_loop) -> None:
    from ghostchimera.stealth.computer import ComputerCapability

    cap = ComputerCapability()
    loop = _loop(computer_capability=cap)
    closed_loop(loop)
    assert loop.computer_capability is cap


def test_init_cloud_mode_sync_and_default(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GHOSTCHIMERA_NEMOTRON_MODE", raising=False)
    loop = _loop(cloud_mode="sync")
    closed_loop(loop)
    assert loop.cloud.mode == "sync"
    loop2 = StealthLoop()
    closed_loop(loop2)
    assert loop2.cloud.mode == "async"


def test_init_token_budget_gating(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.stealth.budgets import COST_BUDGET

    monkeypatch.delenv("GHOSTCHIMERA_NEMOTRON_TOKENS_PER_HOUR", raising=False)
    loop = _loop()
    closed_loop(loop)
    # env unset -> the tracker's default budget stands (limit 100000), not a 0.0 override
    assert loop.budgets.get(COST_BUDGET).limit == 100000.0
    monkeypatch.setenv("GHOSTCHIMERA_NEMOTRON_TOKENS_PER_HOUR", "100")
    loop2 = _loop()
    closed_loop(loop2)
    assert loop2.budgets.get(COST_BUDGET).limit == 100


def test_init_max_sessions_env(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GHOSTCHIMERA_STEALTH_MAX_SESSIONS", raising=False)
    loop = _loop()
    closed_loop(loop)
    assert loop.max_sessions == 1000
    monkeypatch.setenv("GHOSTCHIMERA_STEALTH_MAX_SESSIONS", "3")
    loop2 = _loop()
    closed_loop(loop2)
    assert loop2.max_sessions == 3


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_close_stops_cloud_and_owned_runtime(closed_loop) -> None:
    loop = _loop()
    cloud, runtime = mock.Mock(), mock.Mock()
    loop._cloud, loop.runtime = cloud, runtime
    loop._own_runtime = True
    loop.close()
    cloud.close.assert_called_once_with()
    runtime.stop.assert_called_once_with()


def test_close_skips_runtime_when_not_owned(closed_loop) -> None:
    loop = _loop()
    cloud, runtime = mock.Mock(), mock.Mock()
    loop._cloud, loop.runtime = cloud, runtime
    loop._own_runtime = False
    loop.close()
    cloud.close.assert_called_once_with()
    runtime.stop.assert_not_called()


def test_wait_for_cloud_passes_default_timeout(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    seen: list = []
    loop._cloud.wait_idle = lambda timeout=None: seen.append(timeout) or True  # type: ignore[method-assign]
    assert loop.wait_for_cloud() is True
    assert seen == [30.0]


def test_cloud_property(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    assert loop.cloud is loop._cloud


# ---------------------------------------------------------------------------
# Session history / results bookkeeping
# ---------------------------------------------------------------------------


def test_session_history_bounds_and_lru(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    hist = loop._session_history("s")
    for i in range(25):
        hist.append(f"e{i}")
    assert len(hist) == 20  # deque(maxlen=20), not 21
    loop._session_history("a")
    loop._session_history("b")
    loop._session_history("a")
    assert list(loop._recent.keys())[-1] == "a"  # move_to_end on access


def test_session_history_evicts_beyond_max_sessions(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    loop.max_sessions = 1
    loop._session_history("a")
    loop._session_history("b")
    assert "a" not in loop._recent
    assert "b" in loop._recent


def test_set_last_result_evicts_oldest(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    loop._results_max = 1
    r1 = LoopResult(event_id="e1", decision=Decision.NONE)
    r2 = LoopResult(event_id="e2", decision=Decision.NONE)
    loop._set_last_result("e1", r1)
    loop._set_last_result("e2", r2)
    assert loop.result_for("e1") is None
    assert loop.result_for("e2") is r2
    assert loop.last_result is r2


def test_events_processed_counts_emits(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    before = loop.events_processed
    loop.emit(new_event("email.received", source="gmail", confidence=0.1))
    loop.emit(new_event("email.received", source="gmail", confidence=0.1))
    assert loop.events_processed == before + 2


# ---------------------------------------------------------------------------
# Minimal-update path (weak signal)
# ---------------------------------------------------------------------------


def test_minimal_update_wiring(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    loop = _loop(store=store)
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _weak_signal())
    spies = _spy(
        loop,
        "world.observe_event",
        "graph.record_event",
        "learner.observe",
        "predictions.observe",
        "user_model.observe_event",
        "temporal.observe_event",
        "attention.update_friction",
    )
    record_spy = mock.Mock(wraps=loop._record_experience_event)
    monkeypatch.setattr(loop, "_record_experience_event", record_spy)

    event = new_event("email.received", source="gmail", confidence=0.1)
    result = loop.emit_and_get(event)

    assert result is not None and result.decision == Decision.NONE
    for name, spy in spies.items():
        assert spy.call_count >= 1, name
    assert store.events, "store.record_event must be called when a store is attached"
    record_spy.assert_called_once()
    args = record_spy.call_args[0]
    assert args[1] == Decision.NONE  # decision
    hist = loop._session_history("global")
    assert "email.received" in hist
    assert loop.last_result is result


def test_minimal_update_without_store(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop(store=None)
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _weak_signal())
    event = new_event("email.received", source="gmail", confidence=0.1)
    result = loop.emit_and_get(event)
    assert result is not None and result.decision == Decision.NONE


# ---------------------------------------------------------------------------
# Full-update path (strong signal)
# ---------------------------------------------------------------------------


def test_full_update_wiring(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    consult_r = mock.Mock(wraps=loop._consult_nemotron_reasoner)
    consult_p = mock.Mock(wraps=loop._consult_nemotron_predict)
    consult_w = mock.Mock(wraps=loop._consult_web_grounding)
    update_e = mock.Mock(wraps=loop._update_experience)
    maturity = mock.Mock(wraps=loop.maturity.observe)
    record = mock.Mock(wraps=loop._record_experience_event)
    monkeypatch.setattr(loop, "_consult_nemotron_reasoner", consult_r)
    monkeypatch.setattr(loop, "_consult_nemotron_predict", consult_p)
    monkeypatch.setattr(loop, "_consult_web_grounding", consult_w)
    monkeypatch.setattr(loop, "_update_experience", update_e)
    monkeypatch.setattr(loop.maturity, "observe", maturity)
    monkeypatch.setattr(loop, "_record_experience_event", record)
    # cap predictions so the [:3] slice is exercised deterministically
    fake_preds = [SimpleNamespace(action=f"a{i}", probability=0.1) for i in range(5)]
    monkeypatch.setattr(loop.predictions, "predict", lambda history, hypothesis: fake_preds)

    event = new_event(
        "email.received",
        source="gmail",
        payload={"relevance": 0.9, "confidence": 0.9, "benefit": 0.9},
        confidence=0.9,
    )
    result = loop.emit_and_get(event)

    assert result is not None
    consult_r.assert_called_once()
    consult_p.assert_called_once()
    consult_w.assert_called_once()
    update_e.assert_called_once()
    record.assert_called_once()
    assert len(result.predictions) == 3  # preds[:3], not [:4]
    assert result.trace.get("governance")
    assert result.attention["should_attend"] is True


def test_process_event_prunes_stale_intervention_window(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    import time as time_module

    loop = _loop()
    closed_loop(loop)
    # pruning lives on the full path, so drive a strong signal
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    T = 1792249872.0
    monkeypatch.setattr(time_module, "time", lambda: T)
    loop._interventions_1h.append(T - 3600.5)  # older: pruned
    loop._interventions_1h.append(T - 3600)  # exactly at the boundary: kept
    loop.emit(new_event("email.received", source="gmail", confidence=0.1))
    assert list(loop._interventions_1h) == [T - 3600]


def test_evaluation_signals_carry_payload_units(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    monkeypatch.setattr(loop.learner, "match", lambda history: None)  # no hypothesis
    captured: list = []
    original = loop.evaluator.evaluate
    monkeypatch.setattr(loop.evaluator, "evaluate", lambda signals: captured.append(signals) or original(signals))
    loop.emit(new_event("email.received", source="gmail", payload={"confidence": 0.9}, confidence=0.9))
    assert captured
    signals = captured[0]
    assert signals.relevance == 0.2  # no hypothesis -> 0.2, not 0.5/1.2/1.5
    assert signals.user_benefit == 0.5
    assert signals.cost == 0.2
    assert signals.external_side_effect is False


def test_confidence_boost_math(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    monkeypatch.setattr(loop.intent_engine, "get_primary", lambda: SimpleNamespace(confidence=0.9))
    captured: list = []
    original = loop.evaluator.evaluate
    monkeypatch.setattr(loop.evaluator, "evaluate", lambda signals: captured.append(signals) or original(signals))
    # payload confidence 0.5, primary intent 0.9 -> max(0.5, 0.9*0.9=0.81)
    loop.emit(new_event("email.received", source="gmail", payload={"confidence": 0.5}, confidence=0.5))
    assert captured
    assert captured[0].confidence == pytest.approx(0.81)


def test_confidence_boost_boundary(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    monkeypatch.setattr(loop.intent_engine, "get_primary", lambda: SimpleNamespace(confidence=0.7))
    captured: list = []
    original = loop.evaluator.evaluate
    monkeypatch.setattr(loop.evaluator, "evaluate", lambda signals: captured.append(signals) or original(signals))
    # base exactly 0.31 enters the boost (>= 0.31); primary exactly 0.7 does not (> 0.7)
    loop.emit(new_event("email.received", source="gmail", payload={"confidence": 0.31}, confidence=0.31))
    assert captured
    assert captured[0].confidence == pytest.approx(0.31)


def test_computer_action_ignored_unless_act(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    event = new_event(
        "email.received",
        source="gmail",
        payload={"computer_action": {"kind": "click", "target": "x"}, "confidence": 0.1},
        confidence=0.1,
    )
    result = loop.emit_and_get(event)
    assert result is not None
    assert result.decision != Decision.ACT
    assert "computer_use" not in result.trace


def test_prepare_path_calls_prepare_not_submit(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop(own_runtime=False)
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    monkeypatch.setattr(loop.evaluator, "evaluate", lambda signals: (Decision.PREPARE, {"t": 1}))
    prepare = mock.Mock()
    submit = mock.Mock()
    monkeypatch.setattr(loop, "_prepare", prepare)
    monkeypatch.setattr(loop.runtime, "submit", submit)
    event = new_event("email.received", source="gmail", payload={"confidence": 0.9}, confidence=0.9)
    result = loop.emit_and_get(event)
    assert result is not None and result.decision == Decision.PREPARE
    prepare.assert_called_once()
    submit.assert_not_called()


# ---------------------------------------------------------------------------
# Nemotron UNDERSTAND consultation
# ---------------------------------------------------------------------------


def test_consult_reasoner_gating(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    assert loop._consult_nemotron_reasoner(event, None, []) is None  # no reasoner attached
    loop._reasoner = SimpleNamespace(available=False)
    assert loop._consult_nemotron_reasoner(event, None, []) is None
    loop._reasoner = SimpleNamespace()  # no `available` attribute at all
    assert loop._consult_nemotron_reasoner(event, None, []) is None


def test_consult_reasoner_secret_event_skipped(closed_loop) -> None:
    loop = _loop(reasoner=FakeReasoner())
    closed_loop(loop)
    event = new_event("email.received", source="gmail", privacy_classification="secret")
    assert loop._consult_nemotron_reasoner(event, None, []) is None


def test_consult_reasoner_sync_returns_insight_and_attaches(closed_loop) -> None:
    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    slot = _CloudSlot()
    out = loop._consult_nemotron_reasoner(event, None, [], slot=slot)
    assert out == {"intent": "test-intent"}
    assert slot.values["nemotron"] == {"intent": "test-intent"}
    assert reasoner.understand_calls == [event]


def test_consult_reasoner_meters_tokens(closed_loop) -> None:
    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    loop._consult_nemotron_reasoner(event, None, [])
    assert loop._cloud_tokens == 12


# ---------------------------------------------------------------------------
# Nemotron PREDICT consultation
# ---------------------------------------------------------------------------


def test_consult_predict_gating(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    assert loop._consult_nemotron_predict(event, "s", [], None, []) is None
    loop._reasoner = SimpleNamespace(available=False)
    assert loop._consult_nemotron_predict(event, "s", [], None, []) is None
    loop._reasoner = FakeReasoner()
    secret = new_event("email.received", source="gmail", privacy_classification="secret")
    assert loop._consult_nemotron_predict(secret, "s", [], None, []) is None


def test_consult_predict_skips_when_locally_confident(closed_loop) -> None:
    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    confident = [SimpleNamespace(probability=0.9, basis="workflow")]
    assert loop._consult_nemotron_predict(event, "s", ["email.received"], None, confident) is None
    assert reasoner.predict_calls == []


def test_consult_predict_throttles_per_stream(closed_loop) -> None:
    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    first = loop._consult_nemotron_predict(event, "s", ["email.received"], None, [])
    assert first == [{"action": "act-x", "probability": 0.4}]
    # second call within the interval is skipped
    assert loop._consult_nemotron_predict(event, "s", ["email.received"], None, []) is None
    assert len(reasoner.predict_calls) == 1


def test_consult_predict_attaches_to_slot(closed_loop) -> None:
    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    slot = _CloudSlot()
    out = loop._consult_nemotron_predict(event, "s", [], None, [], slot=slot)
    assert out == [{"action": "act-x", "probability": 0.4}]
    assert slot.values["nemotron_predictions"] == out


# ---------------------------------------------------------------------------
# Web grounding consultation
# ---------------------------------------------------------------------------


def test_consult_web_grounding_gating(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    assert loop._consult_web_grounding(event) is None  # no grounding attached
    loop._grounding = SimpleNamespace(available=False)
    assert loop._consult_web_grounding(event) is None
    loop._grounding = SimpleNamespace()  # missing `available`
    assert loop._consult_web_grounding(event) is None


def test_consult_web_grounding_secret_and_reasoner_skip(closed_loop) -> None:
    loop = _loop(grounding=FakeGrounding(), reasoner=FakeReasoner())
    closed_loop(loop)
    secret = new_event("email.received", source="gmail", privacy_classification="secret")
    assert loop._consult_web_grounding(secret) is None
    # reasoner available -> grounding skipped (reasoner grounds internally)
    event = new_event("email.received", source="gmail")
    assert loop._consult_web_grounding(event) is None


def test_consult_web_grounding_returns_grounded(closed_loop) -> None:
    grounding = FakeGrounding()
    loop = _loop(grounding=grounding)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    assert loop._consult_web_grounding(event) == {"grounded": True}
    assert grounding.calls == [event]


def test_consult_web_grounding_exception_is_none(closed_loop) -> None:
    class Boom:
        available = True

        def ground_event(self, event: Any) -> Any:
            raise RuntimeError("tavily down")

    loop = _loop(grounding=Boom())
    closed_loop(loop)
    assert loop._consult_web_grounding(new_event("email.received", source="gmail")) is None


# ---------------------------------------------------------------------------
# Cloud attach / budget / status
# ---------------------------------------------------------------------------


def test_attach_cloud_paths(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    slot = _CloudSlot()
    loop._attach_cloud(slot, "k", None)  # falsy value: no-op
    assert slot.values == {}
    loop._attach_cloud(slot, "k", {"v": 1})  # trace not set yet: values only
    assert slot.values == {"k": {"v": 1}}
    trace: dict = {}
    slot.trace = trace
    loop._attach_cloud(slot, "k2", {"v": 2})
    assert trace["k2"] == {"v": 2}


def test_cloud_budget_ok_without_budget(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    assert loop._cloud_budget_ok() is True


def test_meter_cloud_call_records_tokens(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.stealth.budgets import COST_BUDGET

    monkeypatch.setenv("GHOSTCHIMERA_NEMOTRON_TOKENS_PER_HOUR", "100")
    loop = _loop()
    closed_loop(loop)
    reasoner = FakeReasoner()
    loop._meter_cloud_call(reasoner)
    assert loop._cloud_tokens == 12
    assert loop.budgets.get(COST_BUDGET).spent() == 12

    class NoUsage:
        def last_call(self) -> dict:
            return {"usage": {"total_tokens": 0}}

    loop._meter_cloud_call(NoUsage())
    assert loop._cloud_tokens == 12  # zero tokens: no-op


def test_cloud_status(closed_loop) -> None:
    loop = _loop(reasoner=FakeReasoner())
    closed_loop(loop)
    status = loop.cloud_status()
    assert status["enabled"] is True
    assert status["tokens_metered"] == 0
    assert "worker" in status
    loop2 = _loop()
    closed_loop(loop2)
    assert loop2.cloud_status()["enabled"] is False


# ---------------------------------------------------------------------------
# restore_from_store
# ---------------------------------------------------------------------------


def test_restore_from_store_without_store(closed_loop) -> None:
    loop = _loop(store=None)
    closed_loop(loop)
    assert loop.restore_from_store() == {"interventions": 0, "workflows": 0, "events": 0}


def test_restore_from_store_rehydrates(closed_loop) -> None:
    from ghostchimera.stealth.intervention import InterventionState

    store = FakeStore()
    store.load_interventions = lambda states: [  # type: ignore[method-assign]
        {"id": "i1", "state": "queued", "trigger_event_id": "e1", "workflow": "w", "confidence": 0.5}
    ]
    store.load_workflows = lambda: [{"name": "w", "pattern": ["a", "b"], "support": 3, "explicit": True}]  # type: ignore[method-assign]
    store.count_events = lambda: 7  # type: ignore[method-assign]
    loop = _loop(store=store)
    closed_loop(loop)
    out = loop.restore_from_store()
    assert out == {"interventions": 1, "workflows": 1, "events": 7}
    assert loop.interventions["i1"].state == InterventionState.QUEUED
    assert loop.events_processed >= 7
    # second restore skips already-known interventions
    out2 = loop.restore_from_store()
    assert out2["interventions"] == 0


def test_restore_from_store_skips_bad_rows(closed_loop) -> None:
    store = FakeStore()
    store.load_interventions = lambda states: [{"no-id": True}]  # type: ignore[method-assign]
    loop = _loop(store=store)
    closed_loop(loop)
    assert loop.restore_from_store()["interventions"] == 0


# ---------------------------------------------------------------------------
# last_result
# ---------------------------------------------------------------------------


def test_last_result_fresh_is_none(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    assert loop.last_result is None


def test_last_result_after_emit(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    event = new_event("email.received", source="gmail", confidence=0.1)
    result = loop.emit_and_get(event)
    assert loop.last_result is result
    assert loop.result_for(event.event_id) is result
    assert loop.result_for("missing") is None


# ---------------------------------------------------------------------------
# Round 2: remaining testteeth survivors
# ---------------------------------------------------------------------------


def test_full_update_wiring_with_reasoner(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    """Full path with a reasoner: cloud values land in the trace."""
    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    spies = _spy(
        loop,
        "world.observe_event",
        "graph.record_event",
        "learner.observe",
        "predictions.observe",
        "user_model.observe_event",
        "temporal.observe_event",
        "attention.update_perception",
        "attention.update_friction",
    )
    event = new_event(
        "email.received",
        source="gmail",
        payload={"relevance": 0.9, "confidence": 0.9, "benefit": 0.9},
        session_id="s1",
        confidence=0.9,
    )
    result = loop.emit_and_get(event)
    assert result is not None
    for name, spy in spies.items():
        assert spy.call_count >= 1, name
    assert "s1" in loop._recent  # stream keyed by session_id, not ""
    assert result.trace.get("nemotron") == {"intent": "test-intent"}
    assert loop.last_result is result


def test_full_update_records_trigger_hits_and_proposals(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.stealth.triggers import TriggerHit

    loop = _loop()
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    hit = TriggerHit(trigger_name="t", event_id="e", action={"kind": "note"})
    monkeypatch.setattr(loop.triggers, "evaluate", lambda event, autonomy: [hit])
    propose = mock.Mock(wraps=loop.proposals.propose_from_hit)
    monkeypatch.setattr(loop.proposals, "propose_from_hit", propose)
    spend = mock.Mock(wraps=loop.budgets.spend)
    monkeypatch.setattr(loop.budgets, "spend", spend)
    loop.emit(new_event("email.received", source="gmail", confidence=0.9))
    assert hit in loop.trigger_hits
    propose.assert_called_once()
    assert spend.call_args[0][1] == 1.0  # PROPOSAL_BUDGET spend amount, not 2.0


def test_minimal_update_records_trigger_hits(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.stealth.triggers import TriggerHit

    loop = _loop()
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _weak_signal())
    hit = TriggerHit(trigger_name="t", event_id="e", action={"kind": "note"})
    monkeypatch.setattr(loop.triggers, "evaluate", lambda event, autonomy: [hit])
    propose = mock.Mock(wraps=loop.proposals.propose_from_hit)
    monkeypatch.setattr(loop.proposals, "propose_from_hit", propose)
    loop.emit(new_event("email.received", source="gmail", confidence=0.1))
    assert hit in loop.trigger_hits
    propose.assert_called_once()


def test_confidence_boost_exact_boundary(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    monkeypatch.setattr(loop.intent_engine, "get_primary", lambda: SimpleNamespace(confidence=0.9))
    captured: list = []
    original = loop.evaluator.evaluate
    monkeypatch.setattr(loop.evaluator, "evaluate", lambda signals: captured.append(signals) or original(signals))
    # base exactly 0.31 enters the boost (>= 0.31); primary 0.9 boosts it
    loop.emit(new_event("email.received", source="gmail", payload={"confidence": 0.31}, confidence=0.31))
    assert captured
    assert captured[0].confidence == pytest.approx(max(0.31, 0.9 * 0.9))


def test_relevance_default_with_hypothesis(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    hypothesis = WorkflowHypothesis(name="w", pattern=("a", "b"), support=2, confidence=0.5)
    monkeypatch.setattr(loop.learner, "match", lambda history: hypothesis)
    maturity = mock.Mock(wraps=loop.maturity.observe)
    monkeypatch.setattr(loop.maturity, "observe", maturity)
    captured: list = []
    original = loop.evaluator.evaluate
    monkeypatch.setattr(loop.evaluator, "evaluate", lambda signals: captured.append(signals) or original(signals))
    loop.emit(new_event("email.received", source="gmail", payload={"confidence": 0.9}, confidence=0.9))
    assert captured
    assert captured[0].relevance == 0.5  # hypothesis present -> 0.5, not 1.5
    maturity.assert_called_once()  # hypothesis observed


def test_prepare_path_with_owned_runtime_submits(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()  # own_runtime=True by default
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    monkeypatch.setattr(loop.evaluator, "evaluate", lambda signals: (Decision.PREPARE, {"t": 1}))
    prepare = mock.Mock()
    submit = mock.Mock()
    monkeypatch.setattr(loop, "_prepare", prepare)
    monkeypatch.setattr(loop.runtime, "submit", submit)
    event = new_event("email.received", source="gmail", payload={"confidence": 0.9}, confidence=0.9)
    result = loop.emit_and_get(event)
    assert result is not None and result.decision == Decision.PREPARE
    submit.assert_called_once()
    prepare.assert_not_called()


def test_computer_action_dry_run_when_act(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()
    closed_loop(loop)
    monkeypatch.setattr(loop.attention, "evaluate", lambda event: _strong_signal())
    monkeypatch.setattr(loop.evaluator, "evaluate", lambda signals: (Decision.ACT, {}))

    class PassThrough:
        def __init__(self, decision: Any) -> None:
            self.decision = decision

        def to_dict(self) -> dict:
            return {}

    # governor would otherwise downgrade ACT for the unknown workflow
    monkeypatch.setattr(loop.governor, "govern", lambda decision, workflow: PassThrough(decision))
    plan = mock.Mock(return_value={"plan": {"dry": True}})
    monkeypatch.setattr(loop, "request_computer_use", plan)
    event = new_event(
        "email.received",
        source="gmail",
        payload={"computer_action": {"kind": "click", "target": "x"}, "confidence": 0.9},
        confidence=0.9,
    )
    result = loop.emit_and_get(event)
    assert result is not None and result.decision == Decision.ACT
    plan.assert_called_once()
    assert plan.call_args[1].get("dry_run") is True
    assert "computer_use" in result.trace


def test_attach_cloud_intervention_recorded(closed_loop) -> None:
    from ghostchimera.stealth.intervention import Intervention, InterventionState

    store = FakeStore()
    loop = _loop(store=store)
    closed_loop(loop)
    intervention = Intervention(
        id="i9",
        trigger_event_id="e",
        workflow="w",
        confidence=0.5,
        state=InterventionState.QUEUED,
        reason="r",
    )
    loop.interventions["i9"] = intervention
    slot = _CloudSlot(intervention_id="i9")
    slot.trace = {}
    loop._attach_cloud(slot, "nemotron", {"intent": "x"})
    assert slot.trace["nemotron"] == {"intent": "x"}
    assert store.interventions == [intervention]


def test_attach_cloud_no_record_when_no_intervention(closed_loop) -> None:
    store = FakeStore()
    loop = _loop(store=store)
    closed_loop(loop)
    record = mock.Mock(wraps=store.record_intervention)
    store.record_intervention = record
    slot = _CloudSlot()  # no intervention_id
    slot.trace = {}
    loop._attach_cloud(slot, "nemotron", {"intent": "x"})
    record.assert_not_called()


def test_cloud_budget_ok_near_exhaustion(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.stealth.budgets import COST_BUDGET

    monkeypatch.setenv("GHOSTCHIMERA_NEMOTRON_TOKENS_PER_HOUR", "100")
    loop = _loop()
    closed_loop(loop)
    loop.budgets.record(COST_BUDGET, 98.5)
    assert loop._cloud_budget_ok() is True  # 98.5 + 1.0 <= 100, not + 2.0
    loop.budgets.record(COST_BUDGET, 2.0)
    assert loop._cloud_budget_ok() is False


def test_meter_cloud_call_fractional_tokens(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.stealth.budgets import COST_BUDGET

    monkeypatch.setenv("GHOSTCHIMERA_NEMOTRON_TOKENS_PER_HOUR", "100")
    loop = _loop()
    closed_loop(loop)

    class HalfToken:
        def last_call(self) -> dict:
            return {"usage": {"total_tokens": 0.5}}

    loop._meter_cloud_call(HalfToken())
    assert loop.budgets.get(COST_BUDGET).spent() == 0.5  # 0.5 > 0 is metered, not skipped


def test_cloud_status_with_budget_and_unavailable_reasoner(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_NEMOTRON_TOKENS_PER_HOUR", "100")
    reasoner = FakeReasoner()
    reasoner.available = False
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    loop._cloud_tokens = 12
    from ghostchimera.stealth.budgets import COST_BUDGET

    loop.budgets.record(COST_BUDGET, 12.34)
    status = loop.cloud_status()
    assert status["enabled"] is False
    assert status["cost_budget"]["spent"] == 12.3  # rounded to 1dp, not 2dp
    assert status["cost_budget"]["remaining"] == 87.7
    assert status["cost_budget"]["limit"] == 100


def test_consult_reasoner_unavailable_with_methods_returns_none(closed_loop) -> None:
    reasoner = FakeReasoner()
    reasoner.available = False
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    assert loop._consult_nemotron_reasoner(event, None, []) is None
    assert reasoner.understand_calls == []


def test_consult_reasoner_no_available_attr_with_methods(closed_loop) -> None:
    class NoAvailable:
        def understand(self, event: Any, hypothesis: Any = None, predictions: Any = None) -> dict:
            raise AssertionError("must not be called")

    loop = _loop(reasoner=NoAvailable())
    closed_loop(loop)
    assert loop._consult_nemotron_reasoner(new_event("email.received", source="gmail"), None, []) is None


def test_consult_predict_unavailable_with_methods_returns_none(closed_loop) -> None:
    reasoner = FakeReasoner()
    reasoner.available = False
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    assert loop._consult_nemotron_predict(new_event("email.received", source="gmail"), "s", [], None, []) is None
    assert reasoner.predict_calls == []


def test_consult_predict_no_available_attr_with_methods(closed_loop) -> None:
    class NoAvailable:
        def predict_next(self, history_text: str, hypothesis: str = "") -> list:
            raise AssertionError("must not be called")

    loop = _loop(reasoner=NoAvailable())
    closed_loop(loop)
    assert loop._consult_nemotron_predict(new_event("email.received", source="gmail"), "s", [], None, []) is None


def test_consult_predict_exact_threshold_skips(closed_loop) -> None:
    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    at_threshold = [SimpleNamespace(probability=0.6, basis="workflow")]
    assert loop._consult_nemotron_predict(event, "s", ["x"], None, at_threshold) is None
    assert reasoner.predict_calls == []


def test_consult_predict_missing_probability_counts_as_zero(closed_loop) -> None:
    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    # no probability attribute -> 0.0, below threshold -> consults
    out = loop._consult_nemotron_predict(event, "s", ["x"], None, [SimpleNamespace(basis="workflow")])
    assert out == [{"action": "act-x", "probability": 0.4}]
    assert len(reasoner.predict_calls) == 1


def test_consult_predict_honours_zero_timestamp(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    import time as time_module

    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    T = 1792249872.0
    monkeypatch.setattr(time_module, "time", lambda: T)
    loop._nemotron_predict_last["s"] = T - 1000.0  # long ago: consult again
    event = new_event("email.received", source="gmail", timestamp=0)  # falsy -> time.time(), not 0.0
    out = loop._consult_nemotron_predict(event, "s", ["x"], None, [])
    assert out == [{"action": "act-x", "probability": 0.4}]


def test_consult_predict_interval_boundary(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    import time as time_module

    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    T = 1792249872.0
    monkeypatch.setattr(time_module, "time", lambda: T)
    loop._nemotron_predict_last["s"] = T - 30.0  # exactly interval: not < interval
    event = new_event("email.received", source="gmail", timestamp=T)
    out = loop._consult_nemotron_predict(event, "s", ["x"], None, [])
    assert out == [{"action": "act-x", "probability": 0.4}]


def test_consult_predict_lru_order_and_eviction(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    import time as time_module

    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    T = 1792249872.0
    monkeypatch.setattr(time_module, "time", lambda: T)
    loop.max_sessions = 1
    e1 = new_event("email.received", source="gmail", timestamp=T)
    e2 = new_event("email.received", source="gmail", timestamp=T)
    assert loop._consult_nemotron_predict(e1, "s1", ["x"], None, []) is not None
    assert loop._consult_nemotron_predict(e2, "s2", ["x"], None, []) is not None
    assert list(loop._nemotron_predict_last.keys()) == ["s2"]  # s1 evicted
    # re-consult s2 after the interval moves it to the end
    loop._nemotron_predict_last["s2"] = T - 1000.0
    loop._consult_nemotron_predict(e2, "s2", ["x"], None, [])
    assert list(loop._nemotron_predict_last.keys()) == ["s2"]


def test_consult_predict_history_capped_at_20(closed_loop) -> None:
    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    history = [f"e{i}" for i in range(25)]
    loop._consult_nemotron_predict(event, "s", history, None, [])
    assert reasoner.predict_calls[0].splitlines() == [f"e{i}" for i in range(5, 25)]


def test_consult_predict_passes_workflow_name(closed_loop) -> None:
    reasoner = FakeReasoner()
    seen: list = []

    def predict_next(history_text: str, hypothesis: str = "") -> list:
        seen.append(hypothesis)
        return [{"action": "a", "probability": 0.4}]

    reasoner.predict_next = predict_next  # type: ignore[method-assign]
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    hypothesis = SimpleNamespace(name="morning-prep")
    loop._consult_nemotron_predict(event, "s", ["x"], hypothesis, [])
    assert seen == ["morning-prep"]


def test_consult_predict_meters_tokens(closed_loop) -> None:
    reasoner = FakeReasoner()
    loop = _loop(reasoner=reasoner)
    closed_loop(loop)
    event = new_event("email.received", source="gmail")
    loop._consult_nemotron_predict(event, "s", ["x"], None, [])
    assert loop._cloud_tokens == 12


def test_consult_web_grounding_unavailable_with_method(closed_loop) -> None:
    grounding = FakeGrounding()
    grounding.available = False
    loop = _loop(grounding=grounding)
    closed_loop(loop)
    assert loop._consult_web_grounding(new_event("email.received", source="gmail")) is None
    assert grounding.calls == []


def test_consult_web_grounding_no_available_attr_with_method(closed_loop) -> None:
    class NoAvailable:
        def ground_event(self, event: Any) -> Any:
            raise AssertionError("must not be called")

    loop = _loop(grounding=NoAvailable())
    closed_loop(loop)
    assert loop._consult_web_grounding(new_event("email.received", source="gmail")) is None


def test_consult_web_grounding_when_reasoner_unavailable(closed_loop) -> None:
    reasoner = FakeReasoner()
    reasoner.available = False
    grounding = FakeGrounding()
    loop = _loop(grounding=grounding, reasoner=reasoner)
    closed_loop(loop)
    assert loop._consult_web_grounding(new_event("email.received", source="gmail")) == {"grounded": True}


def test_restore_learner_state_and_pattern_support(closed_loop) -> None:
    store = FakeStore()
    store.load_workflows = lambda: [  # type: ignore[method-assign]
        {"name": "w", "pattern": ["a", "b"], "support": 3},  # learned: support journaled
        {"name": "w2", "pattern": ["x", "y"]},  # no support key -> support 0
    ]
    loop = _loop(store=store)
    closed_loop(loop)
    loop.learner.min_support = 1  # make the support-0 vs support-1 distinction observable
    out = loop.restore_from_store()
    assert out["workflows"] == 2
    names = [h.name for h in loop.learner.hypotheses()]
    assert "learned:a→b" in names  # learned hypotheses are named by pattern
    w = next(h for h in loop.learner.hypotheses() if h.name == "learned:a→b")
    assert list(w.pattern) == ["a", "b"] and w.support == 3
    assert "learned:x→y" not in names  # support 0 < min_support; the `or 1` mutant restores it


def test_restore_from_store_tolerates_journal_errors(closed_loop) -> None:
    class BadStore(FakeStore):
        def load_interventions(self, states: Any) -> list:
            raise RuntimeError("journal locked")

        def load_workflows(self) -> list:
            raise RuntimeError("journal locked")

        def count_events(self) -> int:
            raise RuntimeError("journal locked")

    loop = _loop(store=BadStore())
    closed_loop(loop)
    assert loop.restore_from_store() == {"interventions": 0, "workflows": 0, "events": 0}


def test_events_processed_fresh_is_zero(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    assert loop.events_processed == 0


def test_cloud_key_sort_keys_and_fallback() -> None:
    assert _cloud_key({"z": 1, "a": 2}) == _cloud_key({"a": 2, "z": 1})
    # unorderable key types -> json.dumps raises -> repr fallback, still a key
    key = _cloud_key({1: "a", "b": 2})
    assert len(key) == 64


def test_session_history_eviction_cleans_predict_cache(closed_loop) -> None:
    loop = _loop()
    closed_loop(loop)
    loop.max_sessions = 1
    loop._nemotron_predict_last["a"] = 1.0
    loop._session_history("a")
    loop._session_history("b")
    assert "a" not in loop._nemotron_predict_last


def test_init_token_budget_small_cap(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.stealth.budgets import COST_BUDGET

    monkeypatch.setenv("GHOSTCHIMERA_NEMOTRON_TOKENS_PER_HOUR", "0.5")
    loop = _loop()
    closed_loop(loop)
    assert loop.budgets.get(COST_BUDGET).limit == 0.5


def test_init_budget_window(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.stealth.budgets import COST_BUDGET

    monkeypatch.setenv("GHOSTCHIMERA_NEMOTRON_TOKENS_PER_HOUR", "100")
    loop = _loop()
    closed_loop(loop)
    assert loop.budgets.get(COST_BUDGET).window_s == 3600.0


def test_init_max_sessions_one(closed_loop, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_STEALTH_MAX_SESSIONS", "1")
    loop = _loop()
    closed_loop(loop)
    assert loop.max_sessions == 1
