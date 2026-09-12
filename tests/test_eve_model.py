"""Tests for EVE Experience Model (Phase 1)."""

from __future__ import annotations

import asyncio
import unittest

from ghostchimera.stealth import (
    EnvironmentState,
    Evidence,
    ExperienceEvent,
    ExperienceEventType,
    ExperienceState,
    ExperienceStream,
    FrictionState,
    IntentHypothesis,
    InterventionMode,
    OutcomeState,
    PerceptionLevel,
    TrajectoryState,
    WorkflowMaturity,
)
from ghostchimera.stealth import (
    EveIntervention as Intervention,
)
from ghostchimera.stealth import (
    EvePrediction as Prediction,
)
from ghostchimera.stealth.attention import AttentionEngine
from ghostchimera.stealth.events import new_event
from ghostchimera.stealth.experience import ExperienceGraph
from ghostchimera.stealth.intent import FrictionDetector, IntentEngine
from ghostchimera.stealth.perception import PerceptionManager, StructuredPerceptionProvider
from ghostchimera.stealth.workflow_learner import WorkflowLearner


class TestExperienceModel(unittest.TestCase):
    def test_experience_state_creation(self):
        exp = ExperienceState(session_id="test-session")
        self.assertTrue(exp.experience_id.startswith("exp-"))
        self.assertEqual(exp.session_id, "test-session")
        self.assertIsInstance(exp.environment, EnvironmentState)
        self.assertIsInstance(exp.trajectory, TrajectoryState)
        self.assertIsInstance(exp.friction, FrictionState)
        self.assertIsInstance(exp.provenance, Evidence)

    def test_intent_hypothesis_with_alternatives(self):
        primary = IntentHypothesis(goal="Find invoice", confidence=0.9, evidence=["event:search"])
        alt1 = IntentHypothesis(goal="Check payment", confidence=0.06)
        alt2 = IntentHypothesis(goal="Forward invoice", confidence=0.03)
        primary.alternatives = [alt1, alt2]

        self.assertTrue(primary.primary())
        self.assertFalse(alt1.primary())
        self.assertEqual(len(primary.alternatives), 2)

    def test_friction_state_signals(self):
        friction = FrictionState(
            score=0.75, repetition=0.8, retry_rate=0.3, signals=["Repeated actions detected", "High retry rate"]
        )
        self.assertEqual(friction.score, 0.75)
        self.assertIn("Repeated actions detected", friction.signals)

    def test_intervention_modes(self):
        for mode in InterventionMode:
            intervention = Intervention(mode=mode)
            self.assertEqual(intervention.mode, mode)

    def test_workflow_maturity_states(self):
        for maturity in WorkflowMaturity:
            self.assertIsInstance(maturity.value, str)

    def test_perception_levels(self):
        levels = list(PerceptionLevel)
        self.assertEqual(len(levels), 5)
        self.assertIn(PerceptionLevel.EVENT, levels)
        self.assertIn(PerceptionLevel.VISION, levels)

    def test_experience_stream(self):
        stream = ExperienceStream(session_id="sess-1", experience_id="exp-1")
        event = ExperienceEvent(
            event_type=ExperienceEventType.TASK_STARTED,
            session_id="sess-1",
            experience_id="exp-1",
            payload={"task": "Find invoice"},
        )
        stream.append(event)
        self.assertEqual(len(stream.recent()), 1)
        self.assertEqual(stream.by_type(ExperienceEventType.TASK_STARTED)[0].payload["task"], "Find invoice")

    def test_environment_state(self):
        env = EnvironmentState(
            active_application="Chrome",
            active_url="https://github.com",
            visible_elements=[{"tag": "button", "text": "Search"}],
        )
        self.assertEqual(env.active_application, "Chrome")
        self.assertEqual(env.active_url, "https://github.com")
        self.assertEqual(len(env.visible_elements), 1)

    def test_prediction(self):
        pred = Prediction(
            predicted_action="browser.navigation",
            probability=0.85,
            expected_friction=0.2,
            opportunity={"type": "prepare", "context": "invoice search"},
            basis="workflow",
        )
        self.assertEqual(pred.predicted_action, "browser.navigation")
        self.assertEqual(pred.probability, 0.85)

    def test_outcome_state(self):
        outcome = OutcomeState(
            task_completion=True,
            time_to_completion=15.5,
            steps_avoided=3,
            friction_reduction=0.4,
            experience_quality=0.82,
        )
        self.assertTrue(outcome.task_completion)
        self.assertEqual(outcome.steps_avoided, 3)

    def test_evidence_provenance(self):
        evidence = Evidence(source_event_ids=["evt-1", "evt-2"], observation_ids=["obs-1"], confidence=0.85)
        self.assertEqual(len(evidence.source_event_ids), 2)
        self.assertEqual(evidence.confidence, 0.85)

    def test_attention_routes_high_value_and_filters_noise(self):
        attention = AttentionEngine()
        file_event = new_event("file.modified", source="fs", payload={"path": "invoice.txt"})
        signal = attention.evaluate(file_event)
        self.assertTrue(signal.should_attend)
        self.assertEqual(signal.level, PerceptionLevel.STRUCTURED)

        noise = new_event("mouse.move", source="desktop")
        signal = attention.evaluate(noise)
        self.assertFalse(signal.should_attend)

        attention.update_friction(0.8)
        signal = attention.evaluate(noise)
        self.assertTrue(signal.should_attend)
        self.assertEqual(signal.level, PerceptionLevel.EVENT)

    def test_attention_detects_application_and_url_transitions(self):
        attention = AttentionEngine()
        attention.evaluate(new_event("context.changed", source="desktop", payload={"application": "Chrome"}))
        signal = attention.evaluate(new_event("context.changed", source="desktop", payload={"application": "Firefox"}))
        self.assertTrue(signal.should_attend)
        self.assertEqual(signal.level, PerceptionLevel.STRUCTURED)

        attention.evaluate(new_event("context.changed", source="desktop", payload={"url": "https://one.test"}))
        signal = attention.evaluate(new_event("context.changed", source="desktop", payload={"url": "https://two.test"}))
        self.assertTrue(signal.should_attend)

    def test_perception_providers_extract_structured_state(self):
        manager = PerceptionManager()
        event = new_event(
            "browser.navigation",
            source="browser",
            payload={
                "url": "https://example.test",
                "browser_dom": {"tag": "body"},
                "browser_a11y": {"name": "main"},
                "console_logs": ["ready"],
            },
        )
        result = asyncio.run(manager.perceive(event, PerceptionLevel.BROWSER, {}))
        self.assertTrue(result.success)
        self.assertEqual(result.environment.active_url, "https://example.test")
        self.assertIn('"tag": "body"', result.data["dom"])
        self.assertIn("untrusted-web-content", result.data["dom"])
        self.assertIn('"name": "main"', result.data["accessibility_tree"])
        self.assertIn("ready", result.data["console"])

        missing_url = new_event("browser.navigation", source="browser")
        result = asyncio.run(manager.perceive(missing_url, PerceptionLevel.BROWSER, {}))
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No URL in event")

    def test_structured_perception_extracts_available_payloads(self):
        provider = StructuredPerceptionProvider()
        event = new_event(
            "context.changed",
            source="test",
            payload={
                "application": "App",
                "dom": {"id": "main"},
                "accessibility_tree": {"role": "main"},
                "ui_elements": [{"name": "Save"}],
                "mcp_data": {"tool": "search"},
            },
        )
        result = asyncio.run(provider.perceive(event, {}))
        self.assertTrue(result.success)
        self.assertEqual(result.environment.active_application, "App")
        self.assertIn('"id": "main"', result.data["dom"])
        self.assertIn('"role": "main"', result.data["accessibility_tree"])
        self.assertIn('"name": "Save"', result.data["ui_elements"])
        self.assertIn('"tool": "search"', result.data["mcp"])

    def test_intent_engine_builds_event_and_payload_hypotheses(self):
        engine = IntentEngine()
        event = new_event(
            "browser.navigation",
            source="browser",
            payload={"url": "https://example.test/invoices", "invoice": "INV-42"},
        )
        hypotheses = engine.update(event, ExperienceGraph(), WorkflowLearner())
        self.assertTrue(hypotheses)
        self.assertEqual(hypotheses[0].goal, "Browse web")
        self.assertIn("Find invoice", [hypothesis.goal for hypothesis in hypotheses])
        self.assertLessEqual(len(hypotheses), engine.max_alternatives + 1)

    def test_intent_engine_matches_workflow_from_recent_history(self):
        engine = IntentEngine()
        learner = WorkflowLearner()
        learner.register_explicit("invoice-flow", ["file.created", "file.modified"], ["agent.tool_called"])
        engine.update(new_event("file.created", source="fs", payload={}), ExperienceGraph(), learner)
        hypotheses = engine.update(
            new_event("file.modified", source="fs", payload={"summary": "invoice draft"}),
            ExperienceGraph(),
            learner,
        )
        goals = [hypothesis.goal for hypothesis in hypotheses]
        self.assertIn("Continue invoice-flow", goals)
        self.assertEqual(engine.get_primary().goal, "Continue invoice-flow")

    def test_friction_detector_auto_counts_errors_and_deviation(self):
        detector = FrictionDetector()
        detector.observe(new_event("file.modified", source="fs", payload={"status": "error: disk full"}))
        state = detector.get_state()
        self.assertEqual(state.error_frequency, 1.0)
        self.assertIn("Frequent errors", state.signals)

        detector.observe(new_event("file.modified", source="fs"), predicted_actions=["event:file.modified"])
        self.assertEqual(detector.get_state().task_deviation, 0.0)
        detector.observe(new_event("email.received", source="gmail"), predicted_actions=["event:file.modified"])
        deviated = detector.get_state()
        self.assertEqual(deviated.task_deviation, 0.5)
        self.assertIn("Actions deviating from predicted workflow", deviated.signals)

    def test_registered_perception_backends_are_invoked(self):
        manager = PerceptionManager()
        structured = manager.providers[PerceptionLevel.STRUCTURED]
        structured.register_mcp_client("repo", lambda event_view, context: {"files": 3})
        structured.register_mcp_client("broken", self._failing_backend)
        browser = manager.providers[PerceptionLevel.BROWSER]
        browser.register_cdp_session("tab-1", lambda event_view, context: {"url": event_view["url"]})
        vision = manager.providers[PerceptionLevel.VISION]
        vision.register_vision_model("ocr", lambda event_view, context: {"text": "invoice"})

        structured_result = asyncio.run(
            manager.perceive(new_event("file.modified", source="fs", payload={}), PerceptionLevel.STRUCTURED, {})
        )
        self.assertIn('"files": 3', structured_result.data["mcp_clients"])
        self.assertIn("broken", structured_result.data["mcp_errors"])

        browser_result = asyncio.run(
            manager.perceive(
                new_event("browser.navigation", source="browser", payload={"url": "https://example.test"}),
                PerceptionLevel.BROWSER,
                {},
            )
        )
        self.assertIn('"url": "https://example.test"', browser_result.data["cdp"])

        vision_result = asyncio.run(
            manager.perceive(new_event("dialog.appeared", source="os", payload={}), PerceptionLevel.VISION, {})
        )
        self.assertIn('"text": "invoice"', vision_result.data["vision_models"])

    @staticmethod
    def _failing_backend(event_view, context):
        raise RuntimeError("mcp unavailable")


if __name__ == "__main__":
    unittest.main()
