"""Every upstream project whose code patterns we adapt is credited in NOTICE."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_notice_credits_hermes_agent_with_mit_text() -> None:
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "https://github.com/NousResearch/hermes-agent" in notice
    assert "Copyright (c) 2025 Nous Research" in notice
    assert "The above copyright notice and this permission notice shall be included" in notice


def test_modules_citing_hermes_agent_are_covered_by_notice() -> None:
    citing = [
        path
        for path in (ROOT / "ghostchimera").rglob("*.py")
        if re.search(r"hermes-agent", path.read_text(encoding="utf-8", errors="ignore"), re.IGNORECASE)
    ]
    assert citing, "expected modules that cite Hermes-Agent"
    assert "Hermes-Agent" in (ROOT / "NOTICE").read_text(encoding="utf-8")
