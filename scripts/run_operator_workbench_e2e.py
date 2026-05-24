#!/usr/bin/env python3
"""Deterministic browser-facing Operator Workbench E2E proof.

This starts the real Ghost Console HTTP server on a local ephemeral port,
fetches the same assets/API a browser would load, and writes a small proof
artifact.  A Playwright screenshot can be added later without making browser
automation a required runtime dependency.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - local loopback E2E only
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - local loopback E2E only
        return response.read().decode("utf-8", errors="replace")


def run_e2e(*, artifact_dir: Path, no_screenshot: bool = False) -> dict[str, Any]:
    from ghostchimera.control_plane.console import run_console
    from ghostchimera.superiority import contains_secret_like_text

    artifact_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ghostchimera-workbench-e2e-") as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            server = run_console(host="127.0.0.1", port=0, http_port=0, state_dir=tmp, open_browser=False, block=False)
        try:
            http_port = server._http_server.server_address[1] if server._http_server else server.http_port
            base_url = f"http://127.0.0.1:{http_port}"
            # Give the HTTP thread a short moment to accept connections.
            time.sleep(0.2)
            html = _fetch_text(base_url + "/")
            scorecard = _fetch_json(base_url + "/api/console/superiority")
            summary = _fetch_json(base_url + "/api/console/operator/summary")
            serialized_payloads = json.dumps({"scorecard": scorecard, "summary": summary}, sort_keys=True)
            checks = {
                "operator_workbench": "operatorWorkbench" in html,
                "command_search": "operatorCommandSearch" in html,
                "next_best_actions": "nextBestActions" in html and bool(scorecard.get("next_best_actions")),
                "scorecard_api": scorecard.get("ok") is True and scorecard.get("score_ratio", 0) >= 0.85,
                "operator_summary_embeds_scorecard": "superiority" in summary,
                "no_secret_leak": not contains_secret_like_text(serialized_payloads),
            }
            artifact = {
                "ok": all(checks.values()),
                "base_url": base_url,
                "checks": checks,
                "score_ratio": scorecard.get("score_ratio"),
                "grade": scorecard.get("grade"),
                "screenshot": "disabled" if no_screenshot else "not_configured",
            }
            path = artifact_dir / "operator_workbench_e2e.json"
            path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
            artifact["artifact_path"] = str(path)
            return artifact
        finally:
            server.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Ghost Console Operator Workbench E2E proof.")
    parser.add_argument("--artifact-dir", default=str(ROOT / ".ghost-artifacts" / "e2e"))
    parser.add_argument("--no-screenshot", action="store_true", help="Skip optional screenshot capture.")
    args = parser.parse_args(argv)
    payload = run_e2e(artifact_dir=Path(args.artifact_dir), no_screenshot=args.no_screenshot)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
