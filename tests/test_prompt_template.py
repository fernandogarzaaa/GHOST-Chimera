"""Tests for chat prompt templates (LangChain-inspired, dependency-free)."""

from __future__ import annotations

import unittest

from ghostchimera.stealth.prompt_template import (
    ChatMessage,
    ChatPromptTemplate,
    FewShotExamples,
)


class TemplateRenderTests(unittest.TestCase):
    def test_roles_and_substitution(self) -> None:
        template = ChatPromptTemplate.from_messages(
            [
                ("system", "You are {{ROLE}}."),
                ("human", "{{QUESTION}}"),
            ]
        )
        messages = template.format(ROLE="a helper", QUESTION="go?")
        self.assertEqual(
            [m.to_dict() for m in messages],
            [
                {"role": "system", "content": "You are a helper."},
                {"role": "human", "content": "go?"},
            ],
        )

    def test_unknown_variables_left_in_place(self) -> None:
        template = ChatPromptTemplate.from_messages([("human", "Hi {{NAME}}, {{MISSING}}")])
        messages = template.format(NAME="Sam")
        self.assertEqual(messages[0].content, "Hi Sam, {{MISSING}}")

    def test_history_placeholder_passes_through(self) -> None:
        template = ChatPromptTemplate.from_messages(
            [
                ("system", "ctx"),
                ("placeholder", "history"),
                ("human", "{{QUESTION}}"),
            ]
        )
        history = [
            {"role": "human", "content": "first"},
            ("assistant", "second"),
            ChatMessage(role="human", content="third"),
        ]
        messages = template.format(history=history, QUESTION="next?")
        self.assertEqual([m.role for m in messages], ["system", "human", "assistant", "human", "human"])
        self.assertEqual([m.content for m in messages], ["ctx", "first", "second", "third", "next?"])

    def test_missing_history_renders_empty(self) -> None:
        template = ChatPromptTemplate.from_messages([("system", "ctx"), ("placeholder", "history"), ("human", "hi")])
        messages = template.format()
        self.assertEqual([(m.role, m.content) for m in messages], [("system", "ctx"), ("human", "hi")])

    def test_invalid_spec_rejected(self) -> None:
        template = ChatPromptTemplate.from_messages(["nope"])
        with self.assertRaises(ValueError):
            template.format()

    def test_invalid_history_item_rejected(self) -> None:
        template = ChatPromptTemplate.from_messages([("placeholder", "history")])
        with self.assertRaises(ValueError):
            template.format(history=[object()])


class PartialTests(unittest.TestCase):
    def test_partial_binds_and_overrides(self) -> None:
        template = ChatPromptTemplate.from_messages([("system", "{{A}}-{{B}}")]).partial(A="1")
        self.assertEqual(template.format(B="2")[0].content, "1-2")
        # Call-site variables win over partials.
        self.assertEqual(template.format(A="9", B="2")[0].content, "9-2")

    def test_input_variables_excludes_partials(self) -> None:
        template = ChatPromptTemplate.from_messages(
            [("system", "{{A}}"), ("placeholder", "history"), ("human", "{{B}} {{A}}")]
        ).partial(A="1")
        self.assertEqual(template.input_variables(), ["B"])


class FewShotTests(unittest.TestCase):
    def test_examples_expand_to_turns_and_cap(self) -> None:
        few_shot = FewShotExamples(
            examples=[("q1", "a1"), ("q2", "a2"), ("q3", "a3")],
            max_examples=2,
        )
        template = ChatPromptTemplate.from_messages([("system", "s"), few_shot, ("human", "now")])
        messages = template.format()
        self.assertEqual(
            [(m.role, m.content) for m in messages],
            [
                ("system", "s"),
                ("human", "Example input:\nq2"),
                ("assistant", "Example output:\na2"),
                ("human", "Example input:\nq3"),
                ("assistant", "Example output:\na3"),
                ("human", "now"),
            ],
        )

    def test_zero_max_examples_disables(self) -> None:
        few_shot = FewShotExamples(examples=[("q", "a")], max_examples=0)
        template = ChatPromptTemplate.from_messages([few_shot])
        self.assertEqual(template.format(), [])

    def test_format_system_joins_contents(self) -> None:
        template = ChatPromptTemplate.from_messages([("system", "a {{X}}"), ("human", "b")])
        self.assertEqual(template.format_system(X="1"), "a 1\nb")


class AgentPromptMigrationTests(unittest.TestCase):
    def test_render_system_prompt_unchanged(self) -> None:
        from ghostchimera.stealth.agent_prompt import render_system_prompt

        text = render_system_prompt(
            agent_name="Maria",
            integrations=["slack", "google-mail"],
            event_payload={"from": "client@example.com", "intent": "reschedule"},
        )
        self.assertNotIn("{{", text)
        self.assertIn("Maria", text)
        self.assertIn("slack, google-mail", text)
        self.assertIn('"intent": "reschedule"', text)

    def test_substituted_values_not_rescanned(self) -> None:
        from ghostchimera.stealth.agent_prompt import render_system_prompt

        text = render_system_prompt(
            agent_name="{{NOT_A_SLOT}}",
            integrations=[],
            event_payload={},
        )
        self.assertIn("{{NOT_A_SLOT}}", text)


if __name__ == "__main__":
    unittest.main()
