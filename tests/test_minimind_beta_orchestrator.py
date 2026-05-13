from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ghostchimera.model_layer.minimind_beta_orchestrator import load_beta_config, run_beta_vision


def test_beta_vision_bootstrap_and_task_hints() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-beta-vision-") as tmp:
        base = Path(tmp)
        note = base / "note.txt"
        note.write_text("TODO: submit expense report by Friday.", encoding="utf-8")
        eml = base / "mail.eml"
        eml.write_text("Subject: Action needed\n\nFollow-up: review PR before deadline.", encoding="utf-8")
        config_path = base / "vision.json"
        config_path.write_text(
            json.dumps(
                {
                    "memory_db": str(base / "memory.sqlite3"),
                    "file_paths": [str(note)],
                    "email_paths": [str(eml)],
                    "run_autonomy_jobs": False,
                }
            ),
            encoding="utf-8",
        )
        config = load_beta_config(config_path)
        result = run_beta_vision(config=config, state_dir=base / "state", profile_name="tiny")
        assert result["ok"] is True
        assert result["bootstrap"]["dataset_records"] >= 1
        assert isinstance(result["task_hints"], list)

