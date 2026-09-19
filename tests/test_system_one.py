"""Tests for System-One typed judgments (TypeSafe-inspired, dependency-free)."""

from __future__ import annotations

import unittest

from ghostchimera.stealth.system_one import (
    ACT,
    CONFIRM,
    ESCALATE,
    ChoiceQuestion,
    NoulQuestion,
    ScoreQuestion,
    advise_event,
    answer_choice,
    answer_noul,
    answer_score,
    combine_weighted,
    confidence_from_distribution,
    evaluate_batch,
    normalize_score,
    route_on_confidence,
)


class ConfidenceMathTests(unittest.TestCase):
    def test_empty_and_single_option(self) -> None:
        self.assertEqual(confidence_from_distribution({}), 0.0)
        self.assertEqual(confidence_from_distribution({"only": 0.2}), 1.0)

    def test_flat_distribution_is_zero(self) -> None:
        self.assertEqual(confidence_from_distribution({"a": 0.5, "b": 0.5}), 0.0)

    def test_peaked_distribution_is_one(self) -> None:
        self.assertEqual(confidence_from_distribution({"a": 1.0, "b": 0.0}), 1.0)

    def test_matches_typesafe_department_example(self) -> None:
        # Published: returns/0.6, billing/0.38, shipping/0.02 -> 0.39.
        confidence = confidence_from_distribution({"returns": 0.6, "billing": 0.38, "shipping": 0.02})
        self.assertAlmostEqual(confidence, 0.39, delta=0.02)

    def test_matches_typesafe_shipping_example(self) -> None:
        # Published split across 5 levels peaking at 0.63 -> 0.53.
        confidence = confidence_from_distribution({"delayed": 0.63, "other": 0.37, "a": 0.0, "b": 0.0, "c": 0.0})
        self.assertAlmostEqual(confidence, 0.53, delta=0.02)

    def test_matches_typesafe_tone_example(self) -> None:
        # Published: frustrated/0.92, angry/0.08, calm/0 -> 0.88.
        confidence = confidence_from_distribution({"frustrated": 0.92, "angry": 0.08, "calm": 0.0})
        self.assertAlmostEqual(confidence, 0.88, delta=0.01)


class ChoiceTests(unittest.TestCase):
    def test_selects_peak_and_reports_distribution(self) -> None:
        question = ChoiceQuestion(instructions="Which?", criteria={"a": "first", "b": "second"})
        answer = answer_choice(question, {"a": 0.7, "b": 0.3})
        self.assertEqual(answer.option, "a")
        self.assertAlmostEqual(sum(answer.probabilities.values()), 1.0)
        self.assertAlmostEqual(answer.confidence, 0.4)

    def test_missing_options_score_zero(self) -> None:
        question = ChoiceQuestion(instructions="Which?", criteria={"a": "first", "b": "second", "c": "third"})
        answer = answer_choice(question, {"b": 1.0})
        self.assertEqual(answer.option, "b")
        self.assertEqual(answer.probabilities["a"], 0.0)

    def test_empty_criteria_rejected(self) -> None:
        with self.assertRaises(ValueError):
            answer_choice(ChoiceQuestion(instructions="Which?", criteria={}), {})


class ScoreTests(unittest.TestCase):
    def test_weighted_mean_matches_typesafe_example(self) -> None:
        # Published bug_severity: 0.7 on L1, 0.3 on L2 -> score 1.3.
        question = ScoreQuestion(instructions="How severe?", levels=("low", "mid", "high"))
        answer = answer_score(question, {"0": 0.0, "1": 0.7, "2": 0.3})
        self.assertAlmostEqual(answer.score, 1.3)
        self.assertEqual(answer.legend, {"0": "low", "1": "mid", "2": "high"})

    def test_single_level_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ScoreQuestion(instructions="How?", levels=("only",))

    def test_normalize_score(self) -> None:
        self.assertAlmostEqual(normalize_score(1.3, 3), 0.65)
        self.assertAlmostEqual(normalize_score(3.0, 4), 1.0)
        with self.assertRaises(ValueError):
            normalize_score(1.0, 1)


class NoulTests(unittest.TestCase):
    def test_probability_clamped(self) -> None:
        question = NoulQuestion(instructions="Yes?")
        self.assertEqual(answer_noul(question, 1.4).probability, 1.0)
        self.assertEqual(answer_noul(question, -0.2).probability, 0.0)

    def test_certainty_is_distance_from_half(self) -> None:
        question = NoulQuestion(instructions="Yes?")
        self.assertAlmostEqual(answer_noul(question, 0.99).certainty, 0.98)
        self.assertAlmostEqual(answer_noul(question, 0.5).certainty, 0.0)


class BatchTests(unittest.TestCase):
    def test_parallel_atomic_evaluation(self) -> None:
        questions = {
            "ready": NoulQuestion(instructions="Ready?"),
            "pick": ChoiceQuestion(instructions="Pick?", criteria={"x": "ex", "y": "why"}),
            "level": ScoreQuestion(instructions="Level?", levels=("lo", "hi")),
        }
        answers = evaluate_batch(
            questions,
            {"anything": True},
            {
                "ready": lambda state: 0.8,
                "pick": lambda state: {"x": 0.2, "y": 0.8},
                "level": lambda state: {"0": 0.1, "1": 0.9},
            },
        )
        self.assertAlmostEqual(answers["ready"].probability, 0.8)
        self.assertEqual(answers["pick"].option, "y")
        self.assertAlmostEqual(answers["level"].score, 0.9)

    def test_missing_scorer_is_explicit_uncertainty(self) -> None:
        answers = evaluate_batch({"ready": NoulQuestion(instructions="Ready?")}, {}, {})
        self.assertEqual(answers["ready"].probability, 0.5)
        self.assertEqual(answers["ready"].certainty, 0.0)

    def test_unknown_question_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_batch({"bad": object()}, {}, {})


class RoutingTests(unittest.TestCase):
    def _answer(self, confidence: float):
        question = ChoiceQuestion(instructions="Which?", criteria={"a": "x", "b": "y"})
        return answer_choice(question, {"a": 0.5 + confidence / 2, "b": 0.5 - confidence / 2})

    def test_three_paths(self) -> None:
        self.assertEqual(route_on_confidence(self._answer(0.95), act_above=0.8, confirm_above=0.5), ACT)
        self.assertEqual(route_on_confidence(self._answer(0.6), act_above=0.8, confirm_above=0.5), CONFIRM)
        self.assertEqual(route_on_confidence(self._answer(0.2), act_above=0.8, confirm_above=0.5), ESCALATE)

    def test_risk_scaled_thresholds(self) -> None:
        cautious = route_on_confidence(self._answer(0.85), act_above=0.9, confirm_above=0.5)
        bold = route_on_confidence(self._answer(0.85), act_above=0.8, confirm_above=0.5)
        self.assertEqual(cautious, CONFIRM)
        self.assertEqual(bold, ACT)

    def test_invalid_thresholds_rejected(self) -> None:
        with self.assertRaises(ValueError):
            route_on_confidence(self._answer(0.9), act_above=0.5, confirm_above=0.8)

    def test_combine_weighted(self) -> None:
        combined = combine_weighted({"a": 0.62, "b": 0.725, "c": 1.0}, {"a": 0.6, "b": 0.3, "c": 0.1})
        self.assertAlmostEqual(combined, 0.6895, places=3)
        with self.assertRaises(ValueError):
            combine_weighted({"a": 1.0}, {"a": 0.0})


class AdvisoryTests(unittest.TestCase):
    def test_noise_event_stays_witness(self) -> None:
        answers = advise_event(
            event_type="mouse.move",
            high_value_type=False,
            trigger_hit=False,
            attention_confidence=0.3,
            friction_score=0.0,
        )
        self.assertLess(answers["should_attend"].probability, 0.5)
        self.assertEqual(answers["mode"].option, "witness")

    def test_trigger_hit_advises_prepare(self) -> None:
        answers = advise_event(
            event_type="email.received",
            high_value_type=True,
            trigger_hit=True,
            attention_confidence=0.9,
            friction_score=0.4,
        )
        self.assertGreater(answers["should_attend"].probability, 0.5)
        self.assertEqual(answers["mode"].option, "prepare")

    def test_high_friction_advises_copilot(self) -> None:
        answers = advise_event(
            event_type="user.correction",
            high_value_type=True,
            trigger_hit=True,
            attention_confidence=0.8,
            friction_score=0.9,
        )
        self.assertEqual(answers["mode"].option, "copilot")
        self.assertGreater(answers["friction"].score, 1.0)

    def test_advisory_never_decides(self) -> None:
        # The advisory layer returns answers, not Decisions: loop authority untouched.
        answers = advise_event(
            event_type="agent.tool_called",
            high_value_type=True,
            trigger_hit=True,
            attention_confidence=1.0,
            friction_score=1.0,
        )
        self.assertTrue(all(hasattr(a, "to_dict") for a in answers.values()))
        self.assertNotIn("decision", {k.lower() for k in answers})


if __name__ == "__main__":
    unittest.main()
