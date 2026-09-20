"""Tests for the TypeSafe judgment provider (HTTP mocked, no network)."""

from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from ghostchimera.model_layer.typesafe_provider import TypeSafeJudge
from ghostchimera.stealth.system_one import ChoiceQuestion, NoulQuestion, ScoreQuestion


def _response(payload: dict) -> mock.Mock:
    body = io.BytesIO(json.dumps(payload).encode("utf-8"))
    resp = mock.Mock()
    resp.read.return_value = body.read()
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


class JudgeConfigTests(unittest.TestCase):
    def test_unavailable_without_key(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False):
            judge = TypeSafeJudge(api_key="")
            self.assertFalse(judge.available)
            self.assertIn("TYPESAFE_API_KEY", judge.validate_config()[0])

    def test_available_with_key(self) -> None:
        judge = TypeSafeJudge(api_key="ts-test", model="jev-latest")
        self.assertTrue(judge.available)
        self.assertEqual(judge.validate_config(), [])
        self.assertEqual(judge.to_dict()["model"], "jev-latest")

    def test_judge_refuses_when_unavailable(self) -> None:
        judge = TypeSafeJudge(api_key="")
        with self.assertRaises(RuntimeError):
            judge.judge({}, {})

    def test_empty_questions_short_circuits(self) -> None:
        judge = TypeSafeJudge(api_key="ts-test")
        self.assertEqual(judge.judge({}, {}), {})


class JudgeMappingTests(unittest.TestCase):
    def _judge(self, answers: dict) -> tuple[TypeSafeJudge, mock.Mock]:
        run_mock = mock.Mock(return_value=_response({"model": "jev-latest", "answers": answers}))
        patcher = mock.patch("ghostchimera.model_layer.typesafe_provider.urllib_request.urlopen", run_mock)
        patcher.start()
        self.addCleanup(patcher.stop)
        return TypeSafeJudge(api_key="ts-test"), run_mock

    def test_choice_answer_mapped(self) -> None:
        judge, run_mock = self._judge(
            {
                "dept": {
                    "type": "choice",
                    "choice": "billing",
                    "confidence": 0.9,
                    "probabilities": {"billing": 0.9, "other": 0.1},
                }
            }
        )
        question = ChoiceQuestion(instructions="Which?", criteria={"billing": "money", "other": "rest"})
        answers = judge.judge({"msg": "charge twice"}, {"dept": question})
        self.assertEqual(answers["dept"].option, "billing")
        self.assertAlmostEqual(answers["dept"].confidence, 0.8)
        sent = json.loads(run_mock.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(sent["questions"]["dept"]["type"], "choice")
        self.assertEqual(sent["model"], "jev-latest")

    def test_score_answer_mapped(self) -> None:
        judge, _ = self._judge(
            {
                "sev": {
                    "type": "score",
                    "score": 1.3,
                    "confidence": 0.54,
                    "probabilities": {"0": 0.0, "1": 0.7, "2": 0.3},
                }
            }
        )
        question = ScoreQuestion(instructions="How bad?", levels=("low", "mid", "high"))
        answers = judge.judge({"msg": "x"}, {"sev": question})
        self.assertAlmostEqual(answers["sev"].score, 1.3)
        self.assertEqual(answers["sev"].legend, {"0": "low", "1": "mid", "2": "high"})

    def test_noul_answer_mapped(self) -> None:
        judge, _ = self._judge({"refund": {"type": "noul", "noul": 0.95}})
        question = NoulQuestion(instructions="Refund?", true_meaning="asks money back", false_meaning="no ask")
        answers = judge.judge({"msg": "refund please"}, {"refund": question})
        self.assertAlmostEqual(answers["refund"].probability, 0.95)

    def test_missing_answer_raises(self) -> None:
        judge, _ = self._judge({})
        with self.assertRaises(RuntimeError):
            judge.judge({"msg": "x"}, {"dept": ChoiceQuestion(instructions="?", criteria={"a": "a"})})

    def test_unknown_question_rejected(self) -> None:
        judge = TypeSafeJudge(api_key="ts-test")
        with self.assertRaises(ValueError):
            judge.judge({"msg": "x"}, {"bad": object()})


if __name__ == "__main__":
    unittest.main()
