"""Tests for the first-class User Model (layers, lifecycle, work graph)."""

from __future__ import annotations

import unittest

from ghostchimera.stealth import new_event
from ghostchimera.stealth.user_model import UserModel


class ExplicitFactTests(unittest.TestCase):
    def test_set_fact_is_full_confidence_and_never_decays(self) -> None:
        model = UserModel()
        trait = model.set_fact("identity", "name", "Alex", source_event_id="evt-1", now=1000.0)

        self.assertEqual(trait.confidence, 1.0)
        self.assertTrue(trait.explicit)
        self.assertEqual(model.decay(now=1000.0 + 365 * 86400.0), 0)
        self.assertEqual(model.get("identity", "name").value, "Alex")

    def test_missing_trait_returns_none(self) -> None:
        self.assertIsNone(UserModel().get("identity", "name"))


class TraitLifecycleTests(unittest.TestCase):
    def test_propose_confirms_toward_threshold(self) -> None:
        model = UserModel()
        first = model.propose_trait("communication", "tone", "concise", confidence=0.4, now=1000.0)

        self.assertEqual(first.confidence, 0.4)
        self.assertFalse(first.confirmed())
        model.propose_trait("communication", "tone", "concise", confidence=0.4, now=1001.0)
        primary = model.propose_trait("communication", "tone", "concise", confidence=0.4, now=1002.0)

        self.assertTrue(primary.confirmed())
        self.assertEqual(primary.confirmations, 2)
        self.assertEqual(model.confirmed_traits("communication")[0].key, "tone")

    def test_proposal_confidence_is_capped(self) -> None:
        model = UserModel()

        trait = model.propose_trait("personality", "planning", "careful", confidence=0.99, now=1000.0)

        self.assertEqual(trait.confidence, 0.4)

    def test_invalid_layer_rejected(self) -> None:
        with self.assertRaises(ValueError):
            UserModel().propose_trait("astrology", "sign", "leo")

    def test_sustained_contradiction_replaces_value(self) -> None:
        model = UserModel()
        model.propose_trait("communication", "verbosity", "terse", confidence=0.4, now=1000.0)
        for step in range(3):
            trait = model.propose_trait("communication", "verbosity", "verbose", confidence=0.4, now=1001.0 + step)

        self.assertEqual(trait.value, "verbose")
        self.assertEqual(trait.contradictions, 0)

    def test_single_contradiction_only_decays(self) -> None:
        model = UserModel()
        model.propose_trait("communication", "verbosity", "terse", confidence=0.4, now=1000.0)

        trait = model.propose_trait("communication", "verbosity", "verbose", confidence=0.4, now=1001.0)

        self.assertEqual(trait.value, "terse")
        self.assertLess(trait.confidence, 0.4)
        self.assertEqual(trait.contradictions, 1)

    def test_decay_prunes_exhausted_traits_but_spares_facts(self) -> None:
        model = UserModel()
        model.propose_trait("personality", "risk", "cautious", confidence=0.4, now=1000.0)
        model.set_fact("identity", "name", "Alex", now=1000.0)

        pruned = model.decay(now=1000.0 + 400 * 86400.0)

        self.assertEqual(pruned, 1)
        self.assertIsNone(model.get("personality", "risk"))
        self.assertIsNotNone(model.get("identity", "name"))


class WorkGraphTests(unittest.TestCase):
    def test_relations_accumulate_and_filter(self) -> None:
        model = UserModel()
        model.note_relation("person:alex", "works_on", "project:moovsoon", weight=2.0)
        model.note_relation("person:alex", "works_on", "project:moovsoon")
        model.note_relation("person:alex", "knows", "person:sam")

        self.assertEqual(
            model.relations("person:alex", "works_on"), {"person:alex\x00works_on": {"project:moovsoon": 3.0}}
        )
        self.assertEqual(len(model.relations("person:alex")), 2)
        self.assertEqual(len(model.relations()), 2)

    def test_observe_event_extracts_facts_and_relations(self) -> None:
        model = UserModel()
        model.observe_event(
            new_event(
                "agent.session_started",
                source="claude",
                actor="alex",
                payload={"project": "moovsoon", "profile": {"role": "engineer"}},
                session_id="s",
            )
        )

        self.assertEqual(model.get("identity", "role").value, "engineer")
        self.assertIn("project:moovsoon", model.relations("person:alex", "works_on")["person:alex\x00works_on"])

    def test_observe_event_ignores_blank_values(self) -> None:
        model = UserModel()
        model.observe_event(new_event("file.modified", source="fs", actor="", payload={}))

        self.assertEqual(model.snapshot()["layers"]["identity"], [])


class PersistenceTests(unittest.TestCase):
    def test_save_and_load_round_trip(self) -> None:
        import tempfile

        model = UserModel()
        model.set_fact("identity", "name", "Alex", now=1000.0)
        model.propose_trait("communication", "tone", "concise", confidence=0.4, now=1000.0)
        model.note_relation("person:alex", "works_on", "project:moovsoon")

        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/user_model.json"
            model.save(path)
            restored = UserModel.load(path)

        self.assertEqual(restored.get("identity", "name").value, "Alex")
        self.assertEqual(restored.get("communication", "tone").value, "concise")
        self.assertEqual(restored.relations(), model.relations())

    def test_load_missing_or_corrupt_returns_empty(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(UserModel.load(f"{tmp}/missing.json").snapshot()["layers"]["identity"], [])
            corrupt = f"{tmp}/corrupt.json"
            with open(corrupt, "w", encoding="utf-8") as handle:
                handle.write("not json{{{")
            self.assertEqual(UserModel.load(corrupt).snapshot()["layers"]["identity"], [])


class StandingBlockTests(unittest.TestCase):
    def test_block_contains_confirmed_traits_and_truncates(self) -> None:
        model = UserModel()
        model.set_fact("identity", "name", "Alex", now=1000.0)
        model.propose_trait("communication", "tone", "concise", confidence=0.4, now=1000.0)
        model.propose_trait("communication", "tone", "concise", confidence=0.4, now=1001.0)
        model.propose_trait("communication", "tone", "concise", confidence=0.4, now=1002.0)
        model.propose_trait("personality", "risk", "cautious", confidence=0.4, now=1000.0)

        block = model.standing_block(host="claude", task="review")

        self.assertIn("identity.name: Alex", block)
        self.assertIn("communication.tone: concise", block)
        self.assertNotIn("risk", block)
        short = model.standing_block(max_chars=20)
        self.assertIn("truncated", short)


class LoopIntegrationTests(unittest.TestCase):
    def test_loop_feeds_user_model_without_changing_decisions(self) -> None:
        from ghostchimera.stealth import StealthLoop
        from ghostchimera.stealth.stealth_policy import Decision

        loop = StealthLoop()
        try:
            loop.emit(
                new_event(
                    "agent.session_started",
                    source="claude",
                    actor="alex",
                    payload={"project": "moovsoon"},
                    session_id="s",
                    confidence=0.9,
                )
            )
            relations = loop.user_model.relations("person:alex", "works_on")
            self.assertTrue(relations)
            loop.emit(new_event("file.modified", source="fs", confidence=0.2))
            self.assertEqual(loop.last_result.decision, Decision.NONE)
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
