from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from ghostchimera.model_layer.codex_cli_provider import CodexCliProvider, get_codex_cli_status


class CodexCliProviderTests(unittest.TestCase):
    @mock.patch("ghostchimera.model_layer.codex_cli_provider.shutil.which", return_value=None)
    def test_status_reports_missing_cli_without_reading_token_files(self, _which: mock.Mock) -> None:
        status = get_codex_cli_status()

        self.assertFalse(status.available)
        self.assertFalse(status.logged_in)
        self.assertIn("not found", status.detail.lower())

    @mock.patch("ghostchimera.model_layer.codex_cli_provider.shutil.which", return_value="codex")
    @mock.patch("ghostchimera.model_layer.codex_cli_provider.subprocess.run")
    def test_status_reports_logged_in_from_cli_status(self, run_mock: mock.Mock, _which: mock.Mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=["codex", "login", "status"],
            returncode=0,
            stdout="Logged in using ChatGPT\n",
            stderr="",
        )

        status = get_codex_cli_status()

        self.assertTrue(status.available)
        self.assertTrue(status.logged_in)
        self.assertIn("ChatGPT", status.detail)

    @mock.patch("ghostchimera.model_layer.codex_cli_provider.get_codex_cli_status")
    @mock.patch("ghostchimera.model_layer.codex_cli_provider.subprocess.run")
    def test_provider_delegates_to_codex_exec_with_read_only_ephemeral_run(
        self, run_mock: mock.Mock, status_mock: mock.Mock
    ) -> None:
        status_mock.return_value = mock.Mock(available=True, logged_in=True, to_dict=lambda: {})

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            output_path = Path(args[args.index("--output-last-message") + 1])
            output_path.write_text("codex answer", encoding="utf-8")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        run_mock.side_effect = fake_run
        provider = CodexCliProvider()

        result = provider.chat("system", "user")

        self.assertEqual(result, "codex answer")
        args = run_mock.call_args.args[0]
        self.assertIn("exec", args)
        self.assertIn("--ephemeral", args)
        self.assertIn("--sandbox", args)
        self.assertIn("read-only", args)
        self.assertIn("--skip-git-repo-check", args)


if __name__ == "__main__":
    unittest.main()
