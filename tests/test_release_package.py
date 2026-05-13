from __future__ import annotations

import json
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleasePackageTests(unittest.TestCase):
    def test_pyproject_has_cli_entrypoints(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = data["project"]["scripts"]
        package_data = data["tool"]["setuptools"]["package-data"]["ghostchimera"]

        self.assertEqual(data["project"]["name"], "ghostchimera")
        self.assertEqual(scripts["ghostchimera"], "ghostchimera.control_plane.cli:_main")
        self.assertEqual(scripts["chimera-pilot"], "ghostchimera.chimera_pilot.cli:main")
        self.assertEqual(scripts["ghostchimera-eval"], "ghostchimera.evals.__main__:main")
        self.assertIn("control_plane/static/*.html", package_data)
        self.assertIn("control_plane/static/*.js", package_data)
        self.assertIn("control_plane/static/*.css", package_data)

    def test_runtime_version_matches_pyproject(self) -> None:
        import ghostchimera

        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(ghostchimera.__version__, data["project"]["version"])

    def test_required_release_docs_exist(self) -> None:
        required = [
            "README.md",
            "LICENSE",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CHANGELOG.md",
            "CHIMERA_PILOT.md",
            "docs/ARCHITECTURE.md",
            "docs/CLEAN_ROOM.md",
            "docs/COMPETITIVE_CAPABILITY_MATRIX.md",
            "docs/RELEASE_CHECKLIST.md",
        ]

        missing = [path for path in required if not (ROOT / path).exists()]

        self.assertEqual(missing, [])

    def test_env_example_documents_runtime_state_variables(self) -> None:
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn("GHOSTCHIMERA_STATE_DIR=", env_example)
        self.assertIn("GHOSTCHIMERA_MEMORY_DB=", env_example)
        self.assertIn("GHOSTCHIMERA_AUDIT_FILE=", env_example)

    def test_release_checklist_documents_installed_wheel_and_user_journey_gate(self) -> None:
        checklist = (ROOT / "docs" / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")

        self.assertIn("python -m ghostchimera.evals run --suite user-journey", checklist)
        self.assertIn("python -m ghostchimera.evals run --suite competitive", checklist)
        self.assertIn("ghostchimera capabilities --format json", checklist)
        self.assertIn("python scripts/smoke_installed_wheel.py", checklist)
        self.assertIn("python scripts/smoke_installed_wheel.py --extras gateway", checklist)
        self.assertIn("gateway extras", checklist)

    def test_installed_wheel_smoke_covers_personal_minimind_cli(self) -> None:
        smoke = (ROOT / "scripts" / "smoke_installed_wheel.py").read_text(encoding="utf-8")

        self.assertIn('"personal-status"', smoke)
        self.assertIn('"personal-consent"', smoke)
        self.assertIn('"personal-bootstrap"', smoke)

    def test_manifest_includes_release_scripts(self) -> None:
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

        self.assertIn("recursive-include scripts *.py", manifest)

    def test_chimera_pilot_cli_status_outputs_json(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "ghostchimera.chimera_pilot.cli", "status", "--include-deterministic-backend"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertGreaterEqual(payload["backend_count"], 1)
        self.assertFalse(payload["policy"]["allow_python_execution"])

    def test_chimera_pilot_cli_denies_python_without_opt_in(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "ghostchimera.chimera_pilot.cli", "run", "python: print(2 + 3)"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("disabled by policy", payload["error"])


if __name__ == "__main__":
    unittest.main()
