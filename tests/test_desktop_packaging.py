"""Static checks for the desktop-distribution scaffolding.

Follows the repo's static-content test pattern: assert the installer inputs
reference the right entry points, versions, and artifacts without executing
heavyweight builds.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "ghostchimera.spec"
ENTRY = ROOT / "packaging" / "ghost_console_entry.py"
ISS = ROOT / "packaging" / "windows" / "ghost-chimera.iss"
PLIST = ROOT / "packaging" / "macos" / "Info.plist"
WORKFLOW = ROOT / ".github" / "workflows" / "desktop.yml"


class DesktopPackagingTests(unittest.TestCase):
    def test_frozen_entry_starts_console(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        self.assertIn("from ghostchimera.control_plane.console import run_console", text)
        self.assertIn("run_console(", text)
        self.assertIn("open_browser=True", text)

    def test_pyinstaller_spec_collects_runtime(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn("ghost_console_entry.py", text)
        self.assertIn('collect_submodules("ghostchimera")', text)
        self.assertIn('collect_data_files("ghostchimera"', text)
        self.assertIn('"torch"', text)  # heavy extras stay out of the bundle
        self.assertIn("GhostConsole", text)
        self.assertIn("GhostChimera", text)

    def test_inno_script_packages_bundle(self) -> None:
        text = ISS.read_text(encoding="utf-8")
        self.assertIn("AppName=Ghost Chimera", text)
        self.assertIn("AppVersion={#AppVersion}", text)
        self.assertIn("GhostConsole.exe", text)
        self.assertIn("GhostChimeraSetup-{#AppVersion}", text)
        self.assertIn("recursesubdirs", text)

    def test_macos_bundle_identity(self) -> None:
        text = PLIST.read_text(encoding="utf-8")
        self.assertIn("ai.ghostchimera.console", text)
        self.assertIn("__GHOSTCHIMERA_VERSION__", text)
        self.assertIn("GhostConsole", text)

    def test_desktop_workflow_builds_on_release(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("published", text)
        self.assertIn("workflow_dispatch", text)
        self.assertIn("windows-latest", text)
        self.assertIn("macos-14", text)
        self.assertIn("build-windows.ps1", text)
        self.assertIn("build-macos-app.sh", text)

    def test_icon_generator_produces_desktop_icons(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-icons-") as tmp:
            completed = subprocess.run(
                [sys.executable, str(ROOT / "packaging" / "assets" / "generate_icons.py"), "--out", tmp],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
            out = Path(tmp)
            self.assertTrue((out / "icon.png").is_file())
            self.assertTrue((out / "ghost.ico").is_file())
            self.assertGreater((out / "ghost.ico").stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
