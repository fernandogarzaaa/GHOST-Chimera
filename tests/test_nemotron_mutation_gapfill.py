"""Gapfill tests from testteeth survivors in ghostchimera/stealth/nemotron_reasoning.py.

Each test pins an exact boundary or constant the mutation run proved the
suite did not notice: confidence-word table values, the empty-reply error
message, event-summary scrub/truncate/filter behaviour, and grounding-block
truncation budgets.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ghostchimera.stealth.nemotron_reasoning import (
    NemotronReasoner,
    coerce_unit,
    extract_json,
)


class FakeProvider:
    available = True
    api_key = "<redacted>"

    def __init__(self, model: str = "nano") -> None:
        self.model = model
        self.calls: list[tuple] = []

    def chat(self, system: str, user: str, **options: Any) -> str:
        self.calls.append((system, user, options))
        return "[]"


def _reasoner(**kw: Any) -> NemotronReasoner:
    primary = FakeProvider()
    return NemotronReasoner(provider=primary, reasoning_provider=primary, **kw)


def _event(**kw: Any) -> SimpleNamespace:
    base = {"event_type": "click", "source": "web", "payload": {"action": "clicked"}}
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# coerce_unit: confidence words and default
# ---------------------------------------------------------------------------


def test_coerce_unit_confidence_words_exact() -> None:
    assert coerce_unit("very high") == 0.9
    assert coerce_unit("high") == 0.8
    assert coerce_unit("medium") == 0.5
    assert coerce_unit("moderate") == 0.5
    assert coerce_unit("low") == 0.2
    assert coerce_unit("very low") == 0.1
    assert coerce_unit("none") == 0.0


def test_coerce_unit_garbage_falls_back_to_default() -> None:
    assert coerce_unit("garbage") == 0.0
    assert coerce_unit("garbage", default=0.25) == 0.25
    assert coerce_unit(None) == 0.0


# ---------------------------------------------------------------------------
# extract_json: the empty-reply error is distinct
# ---------------------------------------------------------------------------


def test_extract_json_empty_reply_message() -> None:
    with pytest.raises(ValueError, match="empty reply"):
        extract_json("")
    with pytest.raises(ValueError, match="empty reply"):
        extract_json("   ")


# ---------------------------------------------------------------------------
# _event_summary: payload, hypothesis, prediction filtering, truncation
# ---------------------------------------------------------------------------


def test_event_summary_includes_payload_and_hypothesis() -> None:
    summary = _reasoner()._event_summary(_event(), "weekly report", [])
    assert "clicked" in summary
    assert "local_hypothesis: weekly report" in summary
    assert "event_type: click" in summary


def test_event_summary_omits_hypothesis_line_when_none() -> None:
    summary = _reasoner()._event_summary(_event(), None, [])
    assert "local_hypothesis" not in summary


def test_event_summary_truncates_payload_to_1500_chars() -> None:
    summary = _reasoner()._event_summary(_event(payload={"blob": "x" * 2000}), None, [])
    line = next(ln for ln in summary.splitlines() if ln.startswith("payload: "))
    assert len(line) - len("payload: ") == 1500


def test_event_summary_keeps_first_three_predictions_only() -> None:
    preds = [SimpleNamespace(action=f"a{i}") for i in range(1, 5)]
    summary = _reasoner()._event_summary(_event(), None, preds)
    assert "local_predictions" in summary
    assert "'a4'" not in summary and "a4" not in summary.split("local_predictions")[1]
    for i in (1, 2, 3):
        assert f"a{i}" in summary


def test_event_summary_filters_none_actions_and_keeps_real_ones() -> None:
    summary = _reasoner()._event_summary(
        _event(), None, [SimpleNamespace(action="none"), SimpleNamespace(action="do-x")]
    )
    tail = summary.split("local_predictions")[1]
    assert "do-x" in tail
    assert "none" not in tail.replace("do-x", "")


def test_event_summary_omits_predictions_line_when_all_filtered() -> None:
    summary = _reasoner()._event_summary(_event(), None, [SimpleNamespace(action="none")])
    assert "local_predictions" not in summary


# ---------------------------------------------------------------------------
# _grounding_block: truncation budgets
# ---------------------------------------------------------------------------


class FakeGrounding:
    available = True

    def __init__(self, results: list[dict]) -> None:
        self._results = results

    def ground_event(self, event: Any) -> dict:
        return {"results": self._results, "transport": "direct"}


def _grounded_reasoner(results: list[dict]) -> NemotronReasoner:
    reasoner = _reasoner()
    reasoner._grounding = FakeGrounding(results)
    return reasoner


def _hit(title: str = "t", url: str = "u", snippet: str = "s") -> dict:
    return {"title": title, "url": url, "snippet": snippet}


def test_grounding_block_caps_results_at_three() -> None:
    block = _grounded_reasoner([_hit(title=f"t{i}") for i in range(4)])._grounding_block(_event())
    assert block.count("\n- ") == 3
    assert "t3" not in block


def test_grounding_block_truncates_snippet_to_300_chars() -> None:
    block = _grounded_reasoner([_hit(snippet="s" * 301)])._grounding_block(_event())
    assert "s" * 300 in block
    assert "s" * 301 not in block


def test_grounding_block_fences_content_at_2000_chars() -> None:
    block = _grounded_reasoner([_hit(title="t" * 2001)])._grounding_block(_event())
    assert "[...truncated...]" in block


def test_grounding_block_empty_when_unavailable() -> None:
    reasoner = _reasoner()
    reasoner._grounding = None
    assert reasoner._grounding_block(_event()) == ""
    fake = FakeGrounding([_hit()])
    fake.available = False
    reasoner._grounding = fake
    assert reasoner._grounding_block(_event()) == ""
