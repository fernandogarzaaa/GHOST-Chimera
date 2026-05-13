from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ghostchimera.model_layer.minimind_beta_orchestrator import (
    BetaVisionConfig,
    _extract_email_tasks,
    load_beta_config,
    run_beta_vision,
)


def _make_config(base: Path, **overrides) -> dict:
    defaults = {
        "memory_db": str(base / "memory.sqlite3"),
        "file_paths": [],
        "email_paths": [],
        "run_autonomy_jobs": False,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# load_beta_config
# ---------------------------------------------------------------------------


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


def test_load_beta_config_uses_defaults_for_missing_optional_fields() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-beta-config-") as tmp:
        base = Path(tmp)
        config_path = base / "min.json"
        config_path.write_text(
            json.dumps({"memory_db": str(base / "mem.sqlite3")}),
            encoding="utf-8",
        )
        config = load_beta_config(config_path)
        assert config.file_paths == []
        assert config.email_paths == []
        assert config.run_autonomy_jobs is False
        assert config.autonomy_profile == "supervised"
        assert "self-audit" in config.autonomy_jobs
        assert "memory-refresh" in config.autonomy_jobs


def test_load_beta_config_respects_explicit_values() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-beta-config-explicit-") as tmp:
        base = Path(tmp)
        config_path = base / "full.json"
        config_path.write_text(
            json.dumps(
                {
                    "memory_db": str(base / "mem.sqlite3"),
                    "file_paths": ["/some/file.txt"],
                    "email_paths": ["/some/mail.eml"],
                    "run_autonomy_jobs": True,
                    "autonomy_profile": "autonomous",
                    "autonomy_jobs": ["self-audit"],
                }
            ),
            encoding="utf-8",
        )
        config = load_beta_config(config_path)
        assert config.file_paths == ["/some/file.txt"]
        assert config.email_paths == ["/some/mail.eml"]
        assert config.run_autonomy_jobs is True
        assert config.autonomy_profile == "autonomous"
        assert config.autonomy_jobs == ["self-audit"]


def test_load_beta_config_falls_back_to_default_memory_db_when_falsy() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-beta-config-fallback-") as tmp:
        base = Path(tmp)
        config_path = base / "empty_db.json"
        config_path.write_text(json.dumps({"memory_db": ""}), encoding="utf-8")
        config = load_beta_config(config_path)
        assert config.memory_db == ".ghostchimera-memory.sqlite3"


def test_load_beta_config_raises_for_missing_file() -> None:
    with pytest.raises((FileNotFoundError, OSError)):
        load_beta_config("/nonexistent/path/config.json")


def test_load_beta_config_raises_for_invalid_json() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-beta-invalid-") as tmp:
        bad_path = Path(tmp) / "bad.json"
        bad_path.write_text("not json {{", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_beta_config(bad_path)


def test_load_beta_config_coerces_single_string_paths_to_lists() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-beta-config-string-paths-") as tmp:
        base = Path(tmp)
        config_path = base / "string_paths.json"
        config_path.write_text(
            json.dumps(
                {
                    "memory_db": str(base / "mem.sqlite3"),
                    "file_paths": "/tmp/file.txt",
                    "email_paths": "/tmp/mail.eml",
                    "autonomy_jobs": "self-audit",
                }
            ),
            encoding="utf-8",
        )
        config = load_beta_config(config_path)
        assert config.file_paths == ["/tmp/file.txt"]
        assert config.email_paths == ["/tmp/mail.eml"]
        assert config.autonomy_jobs == ["self-audit"]


# ---------------------------------------------------------------------------
# BetaVisionConfig dataclass
# ---------------------------------------------------------------------------


def test_beta_vision_config_is_frozen() -> None:
    config = BetaVisionConfig(
        memory_db="mem.sqlite3",
        file_paths=[],
        email_paths=[],
        run_autonomy_jobs=False,
        autonomy_profile="supervised",
        autonomy_jobs=["self-audit"],
    )
    with pytest.raises((AttributeError, TypeError)):
        config.memory_db = "other.sqlite3"  # type: ignore[misc]


def test_beta_vision_config_coerces_types_from_load() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-beta-types-") as tmp:
        base = Path(tmp)
        config_path = base / "types.json"
        # file_paths contains integers which should be coerced to str
        config_path.write_text(
            json.dumps({"memory_db": str(base / "mem.sqlite3"), "file_paths": [1, 2]}),
            encoding="utf-8",
        )
        config = load_beta_config(config_path)
        assert all(isinstance(p, str) for p in config.file_paths)


# ---------------------------------------------------------------------------
# _extract_email_tasks
# ---------------------------------------------------------------------------


def test_extract_email_tasks_returns_empty_for_empty_memory_db() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-extract-") as tmp:
        db = Path(tmp) / "empty.sqlite3"
        results = _extract_email_tasks(db)
        assert results == []


def test_extract_email_tasks_returns_empty_list_type() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-extract-type-") as tmp:
        db = Path(tmp) / "empty.sqlite3"
        result = _extract_email_tasks(db, limit=5)
        assert isinstance(result, list)


def test_extract_email_tasks_custom_limit_accepted() -> None:
    """Verify that limit parameter does not raise and returns a list."""
    with tempfile.TemporaryDirectory(prefix="ghostchimera-extract-limit-") as tmp:
        db = Path(tmp) / "empty.sqlite3"
        result = _extract_email_tasks(db, limit=1)
        assert isinstance(result, list)


def test_extract_email_tasks_items_have_required_keys() -> None:
    """After ingesting a doc with a TODO, extracted tasks should contain source and task_hint."""
    with tempfile.TemporaryDirectory(prefix="ghostchimera-extract-keys-") as tmp:
        base = Path(tmp)
        note = base / "note.txt"
        note.write_text("TODO: finish writing unit tests", encoding="utf-8")
        db = base / "mem.sqlite3"
        # Bootstrap via lifecycle so data is in MemoryStore
        from ghostchimera.model_layer.minimind_lifecycle import MiniMindLifecycle

        lc = MiniMindLifecycle(profile_name="tiny", state_dir=base / "state")
        lc.bootstrap_personal_dataset(
            memory_db=db,
            allow_files=True,
            allow_email=False,
            file_paths=[str(note)],
        )
        results = _extract_email_tasks(db)
        # Results may be empty (depends on FTS search), but if non-empty must have keys
        for item in results:
            assert "source" in item
            assert "task_hint" in item
            assert isinstance(item["task_hint"], str)
            assert len(item["task_hint"]) > 0


# ---------------------------------------------------------------------------
# run_beta_vision
# ---------------------------------------------------------------------------


def test_run_beta_vision_returns_expected_top_level_keys() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-run-keys-") as tmp:
        base = Path(tmp)
        config = BetaVisionConfig(
            memory_db=str(base / "mem.sqlite3"),
            file_paths=[],
            email_paths=[],
            run_autonomy_jobs=False,
            autonomy_profile="supervised",
            autonomy_jobs=[],
        )
        result = run_beta_vision(config=config, state_dir=base / "state", profile_name="tiny")
        assert result["ok"] is True
        assert "bootstrap" in result
        assert "task_hints" in result
        assert "queued_jobs" in result
        assert "next_step" in result


def test_run_beta_vision_no_files_produces_zero_dataset_records() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-run-empty-") as tmp:
        base = Path(tmp)
        config = BetaVisionConfig(
            memory_db=str(base / "mem.sqlite3"),
            file_paths=[],
            email_paths=[],
            run_autonomy_jobs=False,
            autonomy_profile="supervised",
            autonomy_jobs=[],
        )
        result = run_beta_vision(config=config, state_dir=base / "state", profile_name="tiny")
        assert result["bootstrap"]["dataset_records"] == 0
        assert result["queued_jobs"] == []


def test_run_beta_vision_with_file_produces_bootstrap_records() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-run-file-") as tmp:
        base = Path(tmp)
        note = base / "notes.txt"
        note.write_text("Meeting notes: action item to deploy service by EOD.", encoding="utf-8")
        config = BetaVisionConfig(
            memory_db=str(base / "mem.sqlite3"),
            file_paths=[str(note)],
            email_paths=[],
            run_autonomy_jobs=False,
            autonomy_profile="supervised",
            autonomy_jobs=[],
        )
        result = run_beta_vision(config=config, state_dir=base / "state", profile_name="tiny")
        assert result["ok"] is True
        assert result["bootstrap"]["dataset_records"] >= 1
        assert result["bootstrap"]["allow_files"] is True
        assert result["bootstrap"]["allow_email"] is False


def test_run_beta_vision_with_eml_file() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-run-eml-") as tmp:
        base = Path(tmp)
        eml = base / "action.eml"
        eml.write_text(
            "Subject: Deadline reminder\nFrom: boss@example.com\n\nDeadline: submit report by Friday.",
            encoding="utf-8",
        )
        config = BetaVisionConfig(
            memory_db=str(base / "mem.sqlite3"),
            file_paths=[],
            email_paths=[str(eml)],
            run_autonomy_jobs=False,
            autonomy_profile="supervised",
            autonomy_jobs=[],
        )
        result = run_beta_vision(config=config, state_dir=base / "state", profile_name="tiny")
        assert result["ok"] is True
        bootstrap = result["bootstrap"]
        assert bootstrap["dataset_records"] >= 1
        assert bootstrap["allow_files"] is False
        assert bootstrap["allow_email"] is True
        assert len(bootstrap["emails"]) == 1


def test_run_beta_vision_queues_autonomy_jobs_when_enabled() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-run-jobs-") as tmp:
        base = Path(tmp)
        config = BetaVisionConfig(
            memory_db=str(base / "mem.sqlite3"),
            file_paths=[],
            email_paths=[],
            run_autonomy_jobs=True,
            autonomy_profile="supervised",
            autonomy_jobs=["self-audit", "memory-refresh"],
        )
        result = run_beta_vision(config=config, state_dir=base / "state", profile_name="tiny")
        assert result["ok"] is True
        queued = result["queued_jobs"]
        assert len(queued) == 2
        names = {job["name"] for job in queued}
        assert "self-audit" in names
        assert "memory-refresh" in names


def test_run_beta_vision_empty_autonomy_jobs_list() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-run-nojobs-") as tmp:
        base = Path(tmp)
        config = BetaVisionConfig(
            memory_db=str(base / "mem.sqlite3"),
            file_paths=[],
            email_paths=[],
            run_autonomy_jobs=True,
            autonomy_profile="supervised",
            autonomy_jobs=[],
        )
        result = run_beta_vision(config=config, state_dir=base / "state", profile_name="tiny")
        assert result["queued_jobs"] == []


def test_run_beta_vision_next_step_message_is_string() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-run-nextstep-") as tmp:
        base = Path(tmp)
        config = BetaVisionConfig(
            memory_db=str(base / "mem.sqlite3"),
            file_paths=[],
            email_paths=[],
            run_autonomy_jobs=False,
            autonomy_profile="supervised",
            autonomy_jobs=[],
        )
        result = run_beta_vision(config=config, state_dir=base / "state", profile_name="tiny")
        assert isinstance(result["next_step"], str)
        assert len(result["next_step"]) > 0


def test_run_beta_vision_task_hints_is_list() -> None:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-run-hints-") as tmp:
        base = Path(tmp)
        config = BetaVisionConfig(
            memory_db=str(base / "mem.sqlite3"),
            file_paths=[],
            email_paths=[],
            run_autonomy_jobs=False,
            autonomy_profile="supervised",
            autonomy_jobs=[],
        )
        result = run_beta_vision(config=config, state_dir=base / "state", profile_name="tiny")
        assert isinstance(result["task_hints"], list)


def test_load_beta_config_then_run_roundtrip() -> None:
    """Load a config from JSON then run: end-to-end roundtrip."""
    with tempfile.TemporaryDirectory(prefix="ghostchimera-roundtrip-") as tmp:
        base = Path(tmp)
        note = base / "roundtrip.txt"
        note.write_text("Follow-up: check on the deployment status.", encoding="utf-8")
        config_path = base / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "memory_db": str(base / "mem.sqlite3"),
                    "file_paths": [str(note)],
                    "email_paths": [],
                    "run_autonomy_jobs": False,
                    "autonomy_profile": "supervised",
                    "autonomy_jobs": [],
                }
            ),
            encoding="utf-8",
        )
        config = load_beta_config(config_path)
        result = run_beta_vision(config=config, state_dir=base / "state", profile_name="tiny")
        assert result["ok"] is True
        assert result["bootstrap"]["dataset_records"] >= 1
