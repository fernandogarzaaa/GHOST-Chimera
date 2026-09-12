"""Production packaging tests: npm wrapper, brew formula, PyPI metadata (offline)."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> str:
    return (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_npm_package_valid_and_version_synced() -> None:
    pkg = json.loads((REPO_ROOT / "npm" / "package.json").read_text(encoding="utf-8"))
    assert pkg["name"] == "ghostchimera"
    assert set(pkg["bin"]) == {"ghostchimera", "ghost"}
    assert (REPO_ROOT / "npm" / "bin" / "ghostchimera.js").exists()
    assert (REPO_ROOT / "npm" / "install.js").exists()
    launcher = (REPO_ROOT / "npm" / "bin" / "ghostchimera.js").read_text(encoding="utf-8")
    assert "ghostchimera" in launcher and "3.11" in launcher
    assert "GHOSTCHIMERA_SKIP_PIP" in launcher
    # npm semver prerelease mirrors the Python beta version.
    py_version = re.search(r'^version = "([^"]+)"', _pyproject(), re.M).group(1)
    assert (
        pkg["version"].replace("-", ".").startswith(py_version.replace("-beta", "").replace("-", "."))
        or pkg["version"] == py_version
    )


def test_brew_formula_shape() -> None:
    formula = (REPO_ROOT / "homebrew" / "ghostchimera.rb").read_text(encoding="utf-8")
    assert "class Ghostchimera < Formula" in formula
    assert 'depends_on "python@3.12"' in formula
    assert "virtualenv_install_with_resources" in formula
    assert 'bin/"ghostchimera", "doctor"' in formula
    assert "REPLACE_WITH_RELEASE_TARBALL_SHA256" in formula  # filled per release
    assert (REPO_ROOT / "homebrew" / "README.tap.md").exists()


def test_pypi_metadata_complete() -> None:
    pyproject = _pyproject()
    assert "[project.urls]" in pyproject
    assert "https://github.com/fernandogarzaaa/GHOST-Chimera" in pyproject
    for section in ("desktop", "quantum", "local", "minimind", "mcp", "gateway", "voice", "all", "dev"):
        assert f"\n{section} = [" in pyproject, f"missing extra [{section}]"


def test_headless_core_has_no_gui_dependency() -> None:
    """pyautogui (desktop automation) must stay optional for server/brew installs."""
    deps = re.search(r"^dependencies = \[(.*?)\]", _pyproject(), re.M | re.S).group(1)
    assert "pyautogui" not in deps
    assert "pyautogui" in _pyproject()  # still available via [desktop]/[all]


def test_console_entry_points_declared() -> None:
    scripts = re.search(r"\[project\.scripts\](.*?)(?=\n\[|\Z)", _pyproject(), re.S).group(1)
    for entry in ("ghostchimera", "ghost", "chimera-pilot", "ghostchimera-eval"):
        assert entry in scripts


def test_install_channels_default_to_full() -> None:
    """Every install path must pull optional backends, never just the core."""
    postinstall = (REPO_ROOT / "npm" / "install.js").read_text(encoding="utf-8")
    assert "ghostchimera[all]" in postinstall
    assert "Falling back" in postinstall or "fallback" in postinstall.lower()
    formula = (REPO_ROOT / "homebrew" / "ghostchimera.rb").read_text(encoding="utf-8")
    for extra in ("desktop", "mcp", "gateway", "local", "minimind", "voice"):
        assert extra in formula
    install_doc = (REPO_ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
    assert 'pip install "ghostchimera[all]"' in install_doc


def test_npm_launcher_delegates_to_backend() -> None:
    """The npx path, exercised for real (skipped where node is absent)."""
    import shutil
    import subprocess

    if shutil.which("node") is None:
        import pytest

        pytest.skip("node not installed")
    env = dict(__import__("os").environ, GHOSTCHIMERA_SKIP_PIP="1")
    result = subprocess.run(
        ["node", str(REPO_ROOT / "npm" / "bin" / "ghostchimera.js"), "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(REPO_ROOT),
        env=env,
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
