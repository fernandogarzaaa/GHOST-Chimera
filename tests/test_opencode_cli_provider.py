from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

from ghostchimera.model_layer.opencode_cli_provider import (
    FREE_TIER_DATA_USE_NOTICE,
    KNOWN_FREE_MODELS,
    OpenCodeCliProvider,
    OpenCodeCliStatus,
    _extract_json_answer,
    get_opencode_cli_status,
    opencode_login_command,
    opencode_setup_guidance,
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


def _available_status() -> mock.Mock:
    return mock.Mock(available=True, logged_in=True, to_dict=lambda: {})


class TimeoutHandlingTests(unittest.TestCase):
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.subprocess.run")
    def test_chat_raises_operator_error_on_timeout(self, run_mock: mock.Mock, status_mock: mock.Mock) -> None:
        status_mock.return_value = _available_status()
        run_mock.side_effect = subprocess.TimeoutExpired(cmd=["opencode"], timeout=180)
        provider = OpenCodeCliProvider()

        with self.assertRaises(RuntimeError) as exc:
            provider.chat("system", "user")

        message = str(exc.exception)
        self.assertIn("timed out", message)
        self.assertIn("GHOSTCHIMERA_OPENCODE_TIMEOUT_SECONDS", message)

    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.subprocess.run")
    def test_chat_raises_operator_error_when_cli_cannot_launch(
        self, run_mock: mock.Mock, status_mock: mock.Mock
    ) -> None:
        status_mock.return_value = _available_status()
        run_mock.side_effect = OSError("noexec")
        provider = OpenCodeCliProvider()

        with self.assertRaises(RuntimeError) as exc:
            provider.chat("system", "user")

        self.assertIn("could not launch", str(exc.exception))

    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    def test_invalid_timeout_env_raises_clear_error(self, status_mock: mock.Mock) -> None:
        status_mock.return_value = _available_status()
        for bad in ("abc", "0", "-5"):
            with (
                mock.patch.dict("os.environ", {"GHOSTCHIMERA_OPENCODE_TIMEOUT_SECONDS": bad}),
                self.assertRaises(RuntimeError) as exc,
            ):
                OpenCodeCliProvider()
            self.assertIn("GHOSTCHIMERA_OPENCODE_TIMEOUT_SECONDS", str(exc.exception))

    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    def test_valid_timeout_env_is_honored(self, status_mock: mock.Mock) -> None:
        status_mock.return_value = _available_status()
        with mock.patch.dict("os.environ", {"GHOSTCHIMERA_OPENCODE_TIMEOUT_SECONDS": "45"}):
            self.assertEqual(OpenCodeCliProvider().timeout_seconds, 45.0)


class FreeModelRotationTests(unittest.TestCase):
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    def test_default_candidates_follow_known_free_list(self, status_mock: mock.Mock) -> None:
        status_mock.return_value = _available_status()
        with mock.patch.dict("os.environ", {}, clear=False):
            provider = OpenCodeCliProvider()

        self.assertEqual(provider.resolve_model_candidates(), list(KNOWN_FREE_MODELS))
        self.assertEqual(provider.model, KNOWN_FREE_MODELS[0])

    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    def test_explicit_non_free_model_is_never_silently_replaced(self, status_mock: mock.Mock) -> None:
        status_mock.return_value = _available_status()
        with mock.patch.dict("os.environ", {"GHOSTCHIMERA_OPENCODE_MODEL": "opencode/custom-paid"}):
            provider = OpenCodeCliProvider()

        self.assertEqual(provider.resolve_model_candidates(), ["opencode/custom-paid"])

    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.subprocess.run")
    def test_chat_falls_through_to_next_free_model_when_retired(
        self, run_mock: mock.Mock, status_mock: mock.Mock
    ) -> None:
        status_mock.return_value = _available_status()
        run_mock.side_effect = [
            subprocess.CompletedProcess(
                args=["opencode"],
                returncode=1,
                stdout="",
                stderr="Error: model not found: opencode/mimo-v2.5-free",
            ),
            subprocess.CompletedProcess(
                args=["opencode"],
                returncode=0,
                stdout=_ndjson(_text_event("fallback answer")),
                stderr="",
            ),
        ]
        with mock.patch.dict("os.environ", {"GHOSTCHIMERA_OPENCODE_MODEL": KNOWN_FREE_MODELS[0]}):
            provider = OpenCodeCliProvider()

        self.assertEqual(provider.chat("system", "user"), "fallback answer")
        self.assertEqual(provider.last_model_used, KNOWN_FREE_MODELS[1])
        attempted = [call.args[0][call.args[0].index("--model") + 1] for call in run_mock.call_args_list]
        self.assertEqual(attempted, [KNOWN_FREE_MODELS[0], KNOWN_FREE_MODELS[1]])

    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.subprocess.run")
    def test_chat_does_not_retry_non_model_errors(self, run_mock: mock.Mock, status_mock: mock.Mock) -> None:
        status_mock.return_value = _available_status()
        run_mock.return_value = subprocess.CompletedProcess(
            args=["opencode"], returncode=1, stdout="", stderr="Error: rate limited, slow down"
        )
        with mock.patch.dict("os.environ", {"GHOSTCHIMERA_OPENCODE_MODEL": KNOWN_FREE_MODELS[0]}):
            provider = OpenCodeCliProvider()

        with self.assertRaises(RuntimeError) as exc:
            provider.chat("system", "user")

        self.assertEqual(run_mock.call_count, 1)
        self.assertIn("rate limited", str(exc.exception))

    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.subprocess.run")
    def test_exhausted_free_models_raise_actionable_error(
        self, run_mock: mock.Mock, status_mock: mock.Mock
    ) -> None:
        status_mock.return_value = _available_status()
        run_mock.return_value = subprocess.CompletedProcess(
            args=["opencode"], returncode=1, stdout="", stderr="Error: unknown model"
        )
        with mock.patch.dict("os.environ", {"GHOSTCHIMERA_OPENCODE_MODEL": KNOWN_FREE_MODELS[0]}):
            provider = OpenCodeCliProvider()

        with self.assertRaises(RuntimeError) as exc:
            provider.chat("system", "user")

        message = str(exc.exception)
        self.assertEqual(run_mock.call_count, len(KNOWN_FREE_MODELS))
        self.assertIn("retired or unknown", message)
        self.assertIn("GHOSTCHIMERA_OPENCODE_MODEL", message)


class DataUseNoticeTests(unittest.TestCase):
    def test_notice_warns_about_training_use(self) -> None:
        self.assertIn("prompts", FREE_TIER_DATA_USE_NOTICE)
        self.assertIn("confidential", FREE_TIER_DATA_USE_NOTICE)

    @mock.patch("ghostchimera.model_layer.opencode_cli_provider.get_opencode_cli_status")
    def test_to_dict_surfaces_notice_and_last_model(self, status_mock: mock.Mock) -> None:
        status_mock.return_value = _available_status()
        provider = OpenCodeCliProvider()

        payload = provider.to_dict()
        self.assertEqual(payload["data_use_notice"], FREE_TIER_DATA_USE_NOTICE)
        self.assertEqual(payload["last_model_used"], "")
        self.assertEqual(payload["model_candidates"], list(KNOWN_FREE_MODELS))


class SetupGuidanceTests(unittest.TestCase):
    def test_missing_cli_guidance_covers_install_and_login(self) -> None:
        lines = opencode_setup_guidance(
            OpenCodeCliStatus(
                available=False, logged_in=False, command="opencode", model="", detail=""
            )
        )

        joined = "\n".join(lines)
        self.assertIn("PATH", joined)
        self.assertIn("opencode auth login", joined)
        self.assertIn("docs/OPENCODE_FREE_TIER.md", joined)

    def test_not_logged_in_guidance_points_at_login(self) -> None:
        lines = opencode_setup_guidance(
            OpenCodeCliStatus(
                available=True, logged_in=False, command="opencode", model="", detail=""
            )
        )

        joined = "\n".join(lines)
        self.assertIn("opencode auth login", joined)
        self.assertIn("never reads", joined)

    def test_ready_cli_returns_no_guidance(self) -> None:
        self.assertEqual(
            opencode_setup_guidance(
                OpenCodeCliStatus(
                    available=True, logged_in=True, command="opencode", model="", detail=""
                )
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
