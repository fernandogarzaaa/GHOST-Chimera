from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

from ghostchimera.model_layer.opencode_cli_provider import (
    OpenCodeCliProvider,
    _extract_json_answer,
    get_opencode_cli_status,
    opencode_login_command,
)


def _ndjson(*events: dict) -> str:
    return "\n".join(json.dumps(event) for event in events)


def _text_event(text: str) -> dict:
    return {"type": "text", "timestamp": 1, "sessionID": "s", "part": {"id": "p", "type": "text", "text": text}}


class ExtractJsonAnswerTests(unittest.TestCase):
    def test_collects_text_parts_and_skips_control_events(self) -> None:
        stdout = _ndjson(
            {"type": "step_start", "timestamp": 1, "sessionID": "s", "part": {"type": "step-start"}},
            _text_event("hello"),
            _text_event("world"),
            {"type": "step_finish", "timestamp": 2, "sessionID": "s", "part": {"type": "step-finish"}},
            "not json",
        )

        self.assertEqual(_extract_json_answer(stdout), "hello\nworld")

    def test_empty_output_extracts_nothing(self) -> None:
        self.assertEqual(_extract_json_answer(""), "")
        self.assertEqual(_extract_json_answer("plain text, no json"), "")


class OpenCodeCliStatusTests(unittest.TestCase):
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.shutil.which", return_value=None)
    def test_status_reports_missing_cli(self, _which: mock.Mock) -> None:
        status = get_opencode_cli_status()

        self.assertFalse(status.available)
        self.assertFalse(status.logged_in)
        self.assertIn("not found", status.detail.lower())

    def test_login_command_points_at_opencode_auth(self) -> None:
        self.assertEqual(opencode_login_command(), "opencode auth login")


class OpenCodeCliProviderTests(unittest.TestCase):
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.subprocess.run")
    def test_chat_parses_json_answer_from_stdout(self, run_mock: mock.Mock, status_mock: mock.Mock) -> None:
        status_mock.return_value = mock.Mock(available=True, logged_in=True, to_dict=lambda: {})
        run_mock.return_value = subprocess.CompletedProcess(
            args=["opencode"],
            returncode=0,
            stdout=_ndjson({"type": "step_start"}, _text_event("final answer")),
            stderr="",
        )
        provider = OpenCodeCliProvider()

        self.assertEqual(provider.chat("system", "user"), "final answer")
        args = run_mock.call_args.args[0]
        self.assertIn("run", args)
        self.assertIn("--format", args)
        self.assertIn("json", args)
        self.assertIn(provider.model, args)
        self.assertTrue(run_mock.call_args.kwargs["input"].startswith("You are being called"))

    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.subprocess.run")
    def test_chat_attaches_files_for_vision(self, run_mock: mock.Mock, status_mock: mock.Mock) -> None:
        status_mock.return_value = mock.Mock(available=True, logged_in=True, to_dict=lambda: {})
        run_mock.return_value = subprocess.CompletedProcess(
            args=["opencode"], returncode=0, stdout=_ndjson(_text_event("a dialog box")), stderr=""
        )
        provider = OpenCodeCliProvider()

        result = provider.chat_with_files("see", "describe this", ["shot.png"])

        self.assertEqual(result, "a dialog box")
        args = run_mock.call_args.args[0]
        self.assertIn("--file", args)
        self.assertIn("shot.png", args)

    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.subprocess.run")
    def test_chat_raises_compact_error_on_failure(self, run_mock: mock.Mock, status_mock: mock.Mock) -> None:
        status_mock.return_value = mock.Mock(available=True, logged_in=True, to_dict=lambda: {})
        run_mock.return_value = subprocess.CompletedProcess(
            args=["opencode"],
            returncode=1,
            stdout="",
            stderr="WARN noisy startup line\nERROR: model overloaded, retry later\n",
        )
        provider = OpenCodeCliProvider()

        with self.assertRaises(RuntimeError) as exc:
            provider.chat("system", "user")

        message = str(exc.exception)
        self.assertIn("model overloaded", message)
        self.assertNotIn("WARN noisy", message)

    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    def test_chat_refuses_when_not_available(self, status_mock: mock.Mock) -> None:
        status_mock.return_value = mock.Mock(available=False, logged_in=False, to_dict=lambda: {})
        provider = OpenCodeCliProvider()

        with self.assertRaises(RuntimeError):
            provider.chat("system", "user")

    def test_default_model_is_free_tier_and_env_overrides(self) -> None:
        with (
            mock.patch.dict("os.environ", {"GHOSTCHIMERA_OPENCODE_MODEL": "opencode/custom-free"}, clear=False),
            mock.patch(
                "ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status",
                return_value=mock.Mock(available=True, logged_in=True, to_dict=lambda: {}),
            ),
        ):
            self.assertEqual(OpenCodeCliProvider().model, "opencode/custom-free")
        self.assertIn("free", OpenCodeCliProvider.default_model)


if __name__ == "__main__":
    unittest.main()
