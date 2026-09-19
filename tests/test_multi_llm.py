"""Tests for the MultiLLM parallel facade (fake providers, no network)."""

from __future__ import annotations

import unittest
from unittest import mock

from ghostchimera.model_layer.cost_monitor import CostLedger
from ghostchimera.model_layer.multi_llm import MultiLLM


class FakeProvider:
    def __init__(self, answer: str = "", error: str = "", model: str = "fake-1") -> None:
        self._answer = answer
        self._error = error
        self.model = model
        self.available = not error.startswith("UNAVAILABLE:")
        self.calls = 0

    def chat(self, system_message: str, user_message: str) -> str:  # noqa: ARG002
        self.calls += 1
        if self._error:
            raise RuntimeError(self._error)
        return self._answer


def _fabric(names: list[str], providers: dict[str, FakeProvider]) -> MultiLLM:
    with mock.patch("ghostchimera.model_layer.multi_llm.get_provider", side_effect=lambda n: providers.get(n)):
        fabric = MultiLLM(names, ledger=CostLedger())
    return fabric


class MultiLLMTests(unittest.TestCase):
    def test_ask_all_collects_answers_and_errors(self) -> None:
        providers = {"a": FakeProvider(answer="hello"), "b": FakeProvider(error="boom")}
        fabric = _fabric(["a", "b"], providers)
        outcomes = fabric.ask_all("sys", "hi")
        self.assertTrue(outcomes["a"]["ok"])
        self.assertEqual(outcomes["a"]["answer"], "hello")
        self.assertFalse(outcomes["b"]["ok"])
        self.assertIn("boom", outcomes["b"]["error"])

    def test_ask_first_returns_first_success_in_order(self) -> None:
        providers = {"a": FakeProvider(error="down"), "b": FakeProvider(answer="second wins")}
        fabric = _fabric(["a", "b"], providers)
        outcome = fabric.ask_first("sys", "hi")
        self.assertEqual(outcome["answer"], "second wins")
        self.assertEqual(outcome["strategy"], "parallel-first-success")

    def test_ask_first_raises_when_all_fail(self) -> None:
        providers = {"a": FakeProvider(error="down")}
        fabric = _fabric(["a"], providers)
        with self.assertRaises(RuntimeError):
            fabric.ask_first("sys", "hi")

    def test_unknown_and_unavailable_providers_reported(self) -> None:
        providers = {"gone": FakeProvider(error="UNAVAILABLE:x")}
        fabric = _fabric(["missing", "gone"], providers)
        outcomes = fabric.ask_all("sys", "hi")
        self.assertIn("unknown provider", outcomes["missing"]["error"])
        self.assertIn("not available", outcomes["gone"]["error"])

    def test_empty_fabric_returns_empty(self) -> None:
        fabric = MultiLLM([], ledger=CostLedger())
        self.assertEqual(fabric.ask_all("sys", "hi"), {})

    def test_success_records_cost(self) -> None:
        providers = {"a": FakeProvider(answer="hello world")}
        fabric = _fabric(["a"], providers)
        fabric.ask_first("sys", "hi")
        self.assertEqual(fabric.ledger.calls("a"), 1)

    def test_status_snapshot(self) -> None:
        providers = {"a": FakeProvider(answer="x"), "b": FakeProvider(error="UNAVAILABLE:x")}
        fabric = _fabric(["a", "b"], providers)
        status = {item["name"]: item for item in fabric.status()}
        self.assertTrue(status["a"]["available"])
        self.assertFalse(status["b"]["available"])


if __name__ == "__main__":
    unittest.main()
