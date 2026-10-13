"""The CLI colour helpers honour NO_COLOR, FORCE_COLOR and non-TTY output."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

from ghostchimera.control_plane import colors
from ghostchimera.control_plane.colors import Colors, color, color_enabled, print_success


class _TTY(io.StringIO):
    def isatty(self) -> bool:  # pragma: no cover - trivial
        return True


class ColorEnabledTests(unittest.TestCase):
    def _env(self, **env: str):
        clean = {k: v for k, v in os.environ.items() if k not in {"NO_COLOR", "FORCE_COLOR", "TERM"}}
        clean.update(env)
        return mock.patch.dict(os.environ, clean, clear=True)

    def test_non_tty_has_no_escape_codes(self) -> None:
        buf = io.StringIO()
        with self._env(), redirect_stdout(buf):
            print_success("ok")
            print(color("hi", Colors.RED, bold=True))
        self.assertNotIn("\033[", buf.getvalue())
        self.assertIn("ok", buf.getvalue())
        self.assertIn("hi", buf.getvalue())

    def test_tty_gets_colour(self) -> None:
        buf = _TTY()
        with self._env(TERM="xterm"), redirect_stdout(buf):
            print_success("ok")
        self.assertIn("\033[92m", buf.getvalue())

    def test_no_color_wins_over_tty(self) -> None:
        buf = _TTY()
        with self._env(NO_COLOR="1", TERM="xterm"), redirect_stdout(buf):
            print_success("ok")
            self.assertEqual(Colors.RED, "")
        self.assertNotIn("\033[", buf.getvalue())

    def test_empty_no_color_is_ignored(self) -> None:
        with self._env(NO_COLOR="", TERM="xterm"):
            self.assertTrue(color_enabled(_TTY()))

    def test_force_color_on_pipe(self) -> None:
        with self._env(FORCE_COLOR="1"):
            self.assertTrue(color_enabled(io.StringIO()))
        with self._env(FORCE_COLOR="0"):
            self.assertFalse(color_enabled(io.StringIO()))

    def test_dumb_terminal(self) -> None:
        with self._env(TERM="dumb"):
            self.assertFalse(color_enabled(_TTY()))

    def test_cli_piped_output_is_plain(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in {"NO_COLOR", "FORCE_COLOR"}}
        proc = subprocess.run(
            [sys.executable, "-m", "ghostchimera.control_plane.cli", "doctor"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        self.assertNotIn("\033[", proc.stdout + proc.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
