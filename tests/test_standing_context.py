"""Tests for Standing Context (versioned user-model projection)."""

from __future__ import annotations

import unittest

from ghostchimera.stealth.standing_context import StandingContext
from ghostchimera.stealth.user_model import UserModel


def _populated_model() -> UserModel:
    model = UserModel()
    model.set_fact("identity", "name", "Alex", now=1000.0)
    model.set_fact("identity", "role", "engineer", now=1000.0)
    for step in range(3):
        model.propose_trait("communication", "tone", "concise", confidence=0.4, now=1000.0 + step)
    model.note_relation("person:alex", "works_on", "project:moovsoon", weight=2.0)
    model.note_relation("person:alex", "works_on", "project:sidequest")
    model.note_relation("person:alex", "knows", "person:sam")
    return model


class RevisionTests(unittest.TestCase):
    def test_first_refresh_bumps_revision_once(self) -> None:
        context = StandingContext()

        self.assertTrue(context.refresh(_populated_model()))
        self.assertEqual(context.revision, 1)
        self.assertFalse(context.refresh(_populated_model()))
        self.assertEqual(context.revision, 1)

    def test_new_evidence_bumps_revision(self) -> None:
        context = StandingContext()
        model = _populated_model()
        context.refresh(model)
        model.set_fact("identity", "email", "alex@example.test", now=2000.0)

        self.assertTrue(context.refresh(model))
        self.assertEqual(context.revision, 2)

    def test_empty_model_renders_placeholder(self) -> None:
        context = StandingContext()
        context.refresh(UserModel())

        self.assertIn("no confirmed traits", context.render().lower())


class RenderTests(unittest.TestCase):
    def test_sections_ordered_and_attributed(self) -> None:
        context = StandingContext()
        context.refresh(_populated_model())
        block = context.render(host="claude", task="moovsoon review")

        self.assertIn("host=claude task=moovsoon review", block)
        self.assertIn("name: Alex", block)
        self.assertIn("tone: concise", block)
        self.assertIn("project: moovsoon", block)
        self.assertLess(block.index("## identity"), block.index("## work"))

    def test_task_filters_work_section(self) -> None:
        context = StandingContext()
        context.refresh(_populated_model())

        self.assertIn("moovsoon", context.render(task="moovsoon invoice"))
        self.assertNotIn("sidequest", context.render(task="moovsoon invoice"))
        self.assertIn("sidequest", context.render())

    def test_budget_truncates_with_marker(self) -> None:
        context = StandingContext()
        context.refresh(_populated_model())

        short = context.render(max_chars=40)

        self.assertIn("truncated", short)
        self.assertLessEqual(len(short), 40 + len("\n[...truncated...]") + 1)

    def test_to_dict_snapshot(self) -> None:
        context = StandingContext()
        context.refresh(_populated_model())
        snapshot = context.to_dict()

        self.assertEqual(snapshot["revision"], 1)
        self.assertEqual([section["name"] for section in snapshot["sections"]], ["identity", "communication", "work"])


class StandingFileTests(unittest.TestCase):
    def test_write_if_changed_writes_once(self) -> None:
        import tempfile

        context = StandingContext()
        context.refresh(_populated_model())
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/nested/CLAUDE.md"
            self.assertTrue(context.write_if_changed(path, host="claude"))
            self.assertFalse(context.write_if_changed(path, host="claude"))
            with open(path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("name: Alex", content)


class LoopAccessorTests(unittest.TestCase):
    def test_get_standing_context_reflects_observed_events(self) -> None:
        from ghostchimera.stealth import StealthLoop, new_event

        loop = StealthLoop()
        try:
            self.assertIn("no confirmed traits", loop.get_standing_context().lower())
            loop.emit(
                new_event(
                    "agent.session_started",
                    source="claude",
                    actor="alex",
                    payload={"project": "moovsoon", "profile": {"role": "engineer"}},
                    session_id="s",
                    confidence=0.9,
                )
            )
            block = loop.get_standing_context(host="claude")
            self.assertIn("role: engineer", block)
            self.assertIn("project: moovsoon", block)
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
