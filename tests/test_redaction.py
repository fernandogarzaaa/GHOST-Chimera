"""Tests for shared redaction primitives and module delegation."""

from __future__ import annotations

import unittest

from ghostchimera.redaction import (
    BASE_MARKERS,
    POISON_PATTERNS,
    RISK_ORDER,
    SECRET_MARKERS,
    SECRET_PATTERNS,
    redact_text,
    redact_value,
)

_FIXTURE = {
    "api_key": "sk-abcdefghijklmnop",
    "nested": {"password": "hunter2", "safe": "hello"},
    "items": [{"token": "ghp_1234567890abcdef"}, "plain"],
    "empty": "",
    "count": 3,
}


class CanonicalBehaviorTests(unittest.TestCase):
    def test_constants_cover_expected_markers(self) -> None:
        for marker in ("token", "secret", "api_key", "password", "credential", "authorization", "bearer"):
            self.assertIn(marker, SECRET_MARKERS)
            self.assertIn(marker, BASE_MARKERS)
        self.assertEqual(len(SECRET_PATTERNS), 3)
        self.assertTrue(POISON_PATTERNS)
        self.assertEqual(RISK_ORDER["critical"], 4)

    def test_redact_text_scrubs_key_shapes(self) -> None:
        text = "key sk-abcdefghijklmnop and Bearer abcdefghijklmnop done"

        redacted = redact_text(text)

        self.assertNotIn("sk-abcdefghijklmnop", redacted)
        self.assertNotIn("Bearer abcdefghijklmnop", redacted)
        self.assertIn("done", redacted)

    def test_redact_value_recurses_and_preserves_falsy(self) -> None:
        redacted = redact_value(_FIXTURE)

        self.assertEqual(redacted["api_key"], "[redacted]")
        self.assertEqual(redacted["nested"]["password"], "[redacted]")
        self.assertEqual(redacted["nested"]["safe"], "hello")
        self.assertEqual(redacted["items"][0]["token"], "[redacted]")
        self.assertEqual(redacted["items"][1], "plain")
        self.assertEqual(redacted["empty"], "")
        self.assertEqual(redacted["count"], 3)

    def test_redact_value_does_not_mutate_input(self) -> None:
        original = {"api_key": "sk-abcdefghijklmnop", "nested": {"x": 1}}

        redact_value(original)

        self.assertEqual(original, {"api_key": "sk-abcdefghijklmnop", "nested": {"x": 1}})

    def test_extra_markers_extend_matching(self) -> None:
        redacted = redact_value({"confirmation": "yes", "other": 1}, markers=BASE_MARKERS + ("confirmation",))

        self.assertEqual(redacted["confirmation"], "[redacted]")
        self.assertEqual(redacted["other"], 1)

    def test_redact_strings_false_skips_free_text(self) -> None:
        redacted = redact_value({"note": "sk-abcdefghijklmnop", "api_key": "x"}, redact_strings=False)

        self.assertEqual(redacted["note"], "sk-abcdefghijklmnop")
        self.assertEqual(redacted["api_key"], "[redacted]")

    def test_passthrough_keys_recurse_instead(self) -> None:
        redacted = redact_value(
            {"webhook_path": {"token": "abc"}, "api_key": "x"},
            passthrough_keys=frozenset({"webhook_path"}),
        )

        self.assertEqual(redacted["webhook_path"], {"token": "[redacted]"})
        self.assertEqual(redacted["api_key"], "[redacted]")


class ModuleDelegationTests(unittest.TestCase):
    def test_trust_runtime_wrappers_match_shared(self) -> None:
        from ghostchimera.trust_runtime import _redact_text as trust_text
        from ghostchimera.trust_runtime import _redact_value as trust_value

        self.assertEqual(trust_text("sk-abcdefghijklmnop ok"), redact_text("sk-abcdefghijklmnop ok"))
        self.assertEqual(trust_value(_FIXTURE), redact_value(_FIXTURE))

    def test_capability_admission_wrappers_match_shared(self) -> None:
        from ghostchimera.capability_admission import _redact_value as admission_value

        self.assertEqual(admission_value(_FIXTURE), redact_value(_FIXTURE))

    def test_conversation_wrappers_match_shared(self) -> None:
        from ghostchimera.control_plane.conversation import _redact_text as conversation_text
        from ghostchimera.control_plane.conversation import _redact_value as conversation_value

        self.assertEqual(conversation_text("Bearer abcdefghijklmnop"), redact_text("Bearer abcdefghijklmnop"))
        self.assertEqual(conversation_value(_FIXTURE), redact_value(_FIXTURE))

    def test_host_execution_preserves_narrower_behavior(self) -> None:
        from ghostchimera.control_plane.host_execution import SECRET_MARKERS as host_markers
        from ghostchimera.control_plane.host_execution import _redact_value as host_value

        self.assertNotIn("bearer", host_markers)
        self.assertIn("confirmation", host_markers)
        self.assertEqual(
            host_value({"bearer": "x", "confirmation": "yes", "note": "sk-abcdefghijklmnop"}),
            {"bearer": "x", "confirmation": "[redacted]", "note": "sk-abcdefghijklmnop"},
        )

    def test_evolution_preserves_narrower_behavior(self) -> None:
        from ghostchimera.control_plane.evolution import SECRET_MARKERS as evolution_markers
        from ghostchimera.control_plane.evolution import _redact_value as evolution_value

        self.assertNotIn("bearer", evolution_markers)
        self.assertEqual(evolution_value({"bearer": "x"}), {"bearer": "x"})

    def test_remote_control_preserves_exceptions(self) -> None:
        from ghostchimera.integrations.remote_control import _redact_value as remote_value

        redacted = remote_value({"webhook_path": {"token": "abc"}, "bot_token": "x", "name": "y"})

        self.assertEqual(redacted["webhook_path"], {"token": "[redacted]"})
        self.assertEqual(redacted["bot_token"], "[redacted]")
        self.assertEqual(redacted["name"], "y")


if __name__ == "__main__":
    unittest.main()
