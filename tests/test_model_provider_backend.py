from __future__ import annotations

import unittest
from unittest.mock import patch

from ghostchimera.chimera_pilot.backends.model_provider import ModelProviderBackend
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec


class _FakeProvider:
    available = True
    model = "fake-live-model"

    def validate_config(self) -> list[str]:
        return []

    def chat(self, system_message: str, user_message: str) -> str:
        return f"live reply: {user_message}"


class _UnavailableProvider(_FakeProvider):
    available = False

    def validate_config(self) -> list[str]:
        return ["missing auth"]


class ModelProviderBackendTests(unittest.TestCase):
    def test_model_provider_backend_returns_human_readable_provider_output(self) -> None:
        with patch("ghostchimera.chimera_pilot.backends.model_provider.get_provider", return_value=_FakeProvider()):
            backend = ModelProviderBackend("codex_cli")
            task = TaskSpec.create(kind=TaskKind.REASONING, objective="explain what you did")

            result = backend.execute(task)

        self.assertTrue(result.ok)
        self.assertIn("live reply: explain what you did", result.output)
        self.assertEqual(result.metrics["provider"], "codex_cli")
        self.assertNotEqual(result.output, "ok")

    def test_model_provider_backend_fails_closed_when_provider_unavailable(self) -> None:
        with patch(
            "ghostchimera.chimera_pilot.backends.model_provider.get_provider",
            return_value=_UnavailableProvider(),
        ):
            backend = ModelProviderBackend("codex_cli")
            task = TaskSpec.create(kind=TaskKind.REASONING, objective="inspect status")

            result = backend.execute(task)

        self.assertFalse(result.ok)
        self.assertIn("missing auth", result.error or "")


if __name__ == "__main__":
    unittest.main()
