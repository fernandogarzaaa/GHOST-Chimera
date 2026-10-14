"""Regression: CI runs ``ruff check .`` before the test suite (codeaudit F1).

An unused import in ``tool_layer/browser.py`` turned every CI matrix job red.
Keep the repo lint-clean so a stray import fails here, not only in CI.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="ruff not installed")
def test_ruff_check_repo_is_clean() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "concise", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
