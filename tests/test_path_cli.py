"""CLI coverage for durable Ghost path selection."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ghostchimera.control_plane.cli import _main


def test_path_cli_sets_and_shows_active_path(capsys) -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-path-cli-") as tmp:
        config_path = Path(tmp) / "config.json"

        rc = _main(
            [
                "path",
                "set",
                "--profile",
                "ai-engineer-proxy",
                "--training-mode",
                "rag-first",
                "--config-path",
                str(config_path),
            ]
        )
        assert rc == 0
        set_payload = json.loads(capsys.readouterr().out)
        assert set_payload["profile_id"] == "ai-engineer-proxy"

        rc = _main(["path", "show", "--config-path", str(config_path)])
        assert rc == 0
        show_payload = json.loads(capsys.readouterr().out)

    assert show_payload["profile_id"] == "ai-engineer-proxy"
    assert show_payload["synthesis"]["role"]["id"] == "ai-engineer-proxy"
