from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_one_line_install_scripts_exist() -> None:
    assert (ROOT / "scripts" / "install.ps1").is_file()
    assert (ROOT / "scripts" / "install.sh").is_file()


def test_install_scripts_default_to_lean_runtime_profile() -> None:
    powershell = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    bash = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    # Lean default: gateway + dev. "all" stays opt-in via GHOSTCHIMERA_EXTRAS.
    assert '"gateway,dev"' in powershell
    assert 'EXTRAS="gateway,dev"' in bash
    # The default applies only when GHOSTCHIMERA_EXTRAS is UNSET; an explicitly
    # empty value means "no extras, base install only" and must be honored.
    assert "$null -ne $env:GHOSTCHIMERA_EXTRAS" in powershell
    assert "${GHOSTCHIMERA_EXTRAS+x}" in bash
    assert "all,dev" in powershell  # documented opt-in
    assert "all,dev" in bash  # documented opt-in


def test_readme_documents_one_line_install_and_specs() -> None:
    # The long-form install/specs content moved from README.md to docs/OVERVIEW.md.
    readme = (ROOT / "docs" / "OVERVIEW.md").read_text(encoding="utf-8")

    assert "## One-Line Install" in readme
    assert "scripts/install.ps1" in readme
    assert "scripts/install.sh" in readme
    assert "## Runtime Specs" in readme
    assert "Python | 3.11" in readme
    assert "GHOSTCHIMERA_EXTRAS" in readme
    assert "full Ghost Chimera runtime" in readme


def test_readme_top_block_points_judges_at_demo_and_overview() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "pip install ghostchimera" in readme
    assert "ghost demo" in readme
    # The video placeholder was replaced by a real link; keep it a real URL.
    assert "DEMO_VIDEO_URL" not in readme
    assert re.search(r"\*\*Demo video:\*\* \[[^\]]+\]\(https://[^)\s]+\)", readme)
    assert "docs/OVERVIEW.md" in readme


def test_readme_badges_are_live() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    # Live workflow status, not a static "brightgreen" image.
    assert "actions/workflows/ci.yml/badge.svg" in readme
    assert "img.shields.io/badge/CI-" not in readme
    # Version comes from PyPI, so it cannot drift from the published release.
    assert "img.shields.io/pypi/v/ghostchimera" in readme
    assert "img.shields.io/badge/version-" not in readme
