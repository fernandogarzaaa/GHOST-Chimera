from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

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
    # The default extras are gateway,dev; the docs must not claim "full runtime".
    assert "defaults to `gateway,dev`" in readme
    assert "defaults to the full" not in readme


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


# --- newcomer P0-2: the post-install dependency check must match pyproject ---

_IMPORT_NAMES = {"pyautogui": "pyautogui", "mcp": "mcp"}


def _requirement_name(spec: str) -> str:
    return re.split(r"[<>=!~;\[ ]", spec, maxsplit=1)[0].strip().lower()


def _check_lists(text: str) -> tuple[list[str], dict[str, list[str]]]:
    required = ast.literal_eval(re.search(r"^required = (\[.*?\])$", text, re.M).group(1))
    extra_modules = ast.literal_eval(re.search(r"^extra_modules = (\{.*?\})$", text, re.M).group(1))
    return required, extra_modules


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


@pytest.mark.parametrize("script", ["install.sh", "install.ps1"])
def test_install_dependency_check_matches_pyproject_extras(script: str) -> None:
    text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
    required, extra_modules = _check_lists(text)
    project = _pyproject()
    base = {_requirement_name(dep) for dep in project["dependencies"]}
    optional = project["optional-dependencies"]

    # Unconditional checks are exactly the base dependencies.
    assert set(required) == base
    # Every conditional module ships in the extra that triggers it.
    for extra, modules in extra_modules.items():
        assert extra in optional, f"{script}: unknown extra {extra!r}"
        provided = {_requirement_name(dep) for dep in optional[extra]}
        for module in modules:
            assert module in provided, f"{script}: {module} is not in [{extra}]"

    # The default profile (gateway,dev) must not require anything it doesn't install.
    default_installed = base | {_requirement_name(dep) for extra in ("gateway", "dev") for dep in optional[extra]}
    needed = set(required) | {m for e in ("gateway", "dev") for m in extra_modules.get(e, [])}
    assert needed <= default_installed, needed - default_installed
    assert "pyautogui" not in needed


def test_install_sh_and_ps1_check_the_same_modules() -> None:
    sh = _check_lists((ROOT / "scripts" / "install.sh").read_text(encoding="utf-8"))
    ps1 = _check_lists((ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8"))
    assert sh == ps1


@pytest.mark.parametrize("extras", ["gateway,dev", ""])
def test_install_sh_dependency_check_passes_for_default_profile(extras: str) -> None:
    text = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    match = re.search(r'^"\$VENV_PYTHON" - "\$EXTRAS" <<\'PY\'\n(.*?)^PY$', text, re.M | re.S)
    assert match, "dependency-check heredoc not found"
    proc = subprocess.run(
        [sys.executable, "-", extras],
        input=match.group(1),
        capture_output=True,
        text=True,
        timeout=60,
    )
    # This interpreter has the base deps but not pyautogui; the old check failed here.
    assert proc.returncode == 0, proc.stderr
    assert "runtime dependency surface ok" in proc.stdout
