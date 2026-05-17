"""Regression tests for the optional IBM Bob tooling boundary."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PACKAGE = ROOT / "ghostchimera"


def test_bob_tooling_is_not_referenced_by_runtime_package() -> None:
    """Ghost Chimera runtime code must not depend on hackathon Bob tooling."""
    forbidden_markers = (
        "IBM Bob",
        "Bob-to-Ghost",
        "bob_accelerator",
        "bob_delivery_package",
    )

    offenders: list[str] = []
    for path in RUNTIME_PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in forbidden_markers:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {marker!r}")

    assert offenders == []


def test_bob_optional_boundary_doc_exists_and_explains_opt_out() -> None:
    doc = ROOT / "docs" / "BOB_OPTIONAL_TOOLING.md"
    assert doc.exists()

    content = doc.read_text(encoding="utf-8")
    assert "not required to run Ghost Chimera" in content
    assert "Users who do not care about IBM Bob can ignore all Bob-named files" in content
    assert "Do not import Bob tooling from `ghostchimera/`" in content
