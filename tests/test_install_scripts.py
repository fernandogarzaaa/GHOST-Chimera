from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_one_line_install_scripts_exist() -> None:
    assert (ROOT / "scripts" / "install.ps1").is_file()
    assert (ROOT / "scripts" / "install.sh").is_file()


def test_install_scripts_default_to_full_runtime_profile() -> None:
    powershell = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    bash = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert '"all,dev"' in powershell
    assert "GHOSTCHIMERA_EXTRAS:-all,dev" in bash
    assert "Installing full Python runtime dependencies" in powershell
    assert "Installing full Python runtime dependencies" in bash
    assert "pip check" in powershell
    assert "pip check" in bash
    assert "runtime dependency surface ok" in powershell
    assert "runtime dependency surface ok" in bash
    assert "ghostchimera.exe console" in powershell
    assert "ghostchimera console" in bash


def test_readme_documents_one_line_install_and_specs() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## One-Line Install" in readme
    assert "scripts/install.ps1" in readme
    assert "scripts/install.sh" in readme
    assert "## Runtime Specs" in readme
    assert "Python | 3.11" in readme
    assert "GHOSTCHIMERA_EXTRAS" in readme
    assert "full Ghost Chimera runtime" in readme
