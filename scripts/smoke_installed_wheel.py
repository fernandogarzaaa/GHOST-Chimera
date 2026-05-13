#!/usr/bin/env python3
"""Smoke a built Ghost Chimera wheel in a clean virtual environment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _latest_wheel(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("ghostchimera-*.whl"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not wheels:
        raise FileNotFoundError(f"No Ghost Chimera wheel found in {dist_dir}. Run 'python -m build' first.")
    return wheels[0]


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _package_spec(wheel: Path, extras: str) -> str:
    if not extras:
        return str(wheel)
    normalized = ",".join(part.strip() for part in extras.split(",") if part.strip())
    return f"ghostchimera[{normalized}] @ {wheel.resolve().as_uri()}"


def _run(command: list[str], *, timeout: int = 120) -> dict[str, object]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=timeout)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "ok": completed.returncode == 0,
    }


def _smoke_commands(python: Path, extras: str, state_dir: Path) -> list[list[str]]:
    personal_source_dir = state_dir / "personal-minimind-source"
    personal_source_dir.mkdir(parents=True, exist_ok=True)
    (personal_source_dir / "operator-notes.txt").write_text(
        "Installed wheel Personal MiniMind smoke note for local dataset bootstrap.",
        encoding="utf-8",
    )
    personal_memory = state_dir / "personal-minimind.sqlite3"
    commands = [
        [str(python), "-c", "import ghostchimera; print(ghostchimera.__version__)"],
        [str(python), "-m", "ghostchimera", "--help"],
        [str(python), "-m", "ghostchimera", "run", "--help"],
        [str(python), "-m", "ghostchimera", "batch", "--help"],
        [str(python), "-m", "ghostchimera", "--config-show"],
        [str(python), "-m", "ghostchimera", "workspace", "show", "--state-dir", str(state_dir)],
        [
            str(python),
            "-m",
            "ghostchimera",
            "workspace",
            "add-evidence",
            "--state-dir",
            str(state_dir),
            "--source",
            "wheel-smoke",
            "--content",
            "workspace sync smoke feeds retrieval",
            "--confidence",
            "0.95",
        ],
        [
            str(python),
            "-m",
            "ghostchimera",
            "workspace",
            "sync-memory",
            "--state-dir",
            str(state_dir),
            "--memory-db",
            str(state_dir / "memory.sqlite3"),
            "--min-confidence",
            "0.9",
            "--stale-after-days",
            "30",
        ],
        [str(python), "-m", "ghostchimera", "minimind", "architectures"],
        [str(python), "-m", "ghostchimera", "minimind", "status"],
        [
            str(python),
            "-m",
            "ghostchimera",
            "minimind",
            "personal-status",
            "--state-dir",
            str(state_dir),
            "--memory-db",
            str(personal_memory),
        ],
        [
            str(python),
            "-m",
            "ghostchimera",
            "minimind",
            "personal-consent",
            "--state-dir",
            str(state_dir),
            "--memory-db",
            str(personal_memory),
            "--admin-controls",
            "--allow-machine-crawl",
            "--allow-training",
            "--crawl-root",
            str(personal_source_dir),
        ],
        [
            str(python),
            "-m",
            "ghostchimera",
            "minimind",
            "personal-bootstrap",
            "--state-dir",
            str(state_dir),
            "--memory-db",
            str(personal_memory),
            "--max-files",
            "10",
        ],
        [
            str(python),
            "-m",
            "ghostchimera",
            "minimind",
            "personal-revoke",
            "--state-dir",
            str(state_dir),
            "--memory-db",
            str(personal_memory),
        ],
    ]
    if extras:
        commands.extend(
            [
                [str(python), "-m", "ghostchimera", "console", "--help"],
                [str(python), "-m", "ghostchimera.evals", "run", "--suite", "user-journey"],
            ]
        )
    return commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke a built Ghost Chimera wheel in a clean venv")
    parser.add_argument("--dist-dir", default=str(ROOT / "dist"), help="Directory containing built wheel artifacts.")
    parser.add_argument("--extras", default="", help="Optional extras to install from the built wheel, for example 'gateway'.")
    args = parser.parse_args(argv)

    wheel = _latest_wheel(Path(args.dist_dir))
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="ghostchimera-wheel-smoke-") as tmp:
        venv_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python = _venv_python(venv_dir)
        install_spec = _package_spec(wheel, args.extras)
        install_results = [
            _run([str(python), "-m", "pip", "install", "--upgrade", "pip"], timeout=180),
            _run([str(python), "-m", "pip", "install", install_spec], timeout=240),
            _run([str(python), "-m", "pip", "check"], timeout=120),
        ]
        results.extend(install_results)
        if all(item["ok"] for item in install_results):
            for command in _smoke_commands(python, args.extras, Path(tmp) / "state"):
                results.append(_run(command, timeout=120))

    ok = all(item["ok"] for item in results)
    payload = {
        "ok": ok,
        "wheel": str(wheel),
        "extras": args.extras,
        "checks": results,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
