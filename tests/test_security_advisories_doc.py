"""Item 8: the unfixed diskcache advisory (via the [local] extra) is documented."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_diskcache_advisory_is_documented_while_unfixed() -> None:
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "CVE-2025-69872" in text
    assert "No fixed" in text and "[local]" in text


def test_diskcache_is_not_a_base_dependency() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    base = " ".join(project.get("dependencies", [])).lower()
    assert "diskcache" not in base and "llama-cpp-python" not in base
