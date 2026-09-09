"""Model catalog 2026 refresh + models.dev sync tests (offline)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ghostchimera.model_layer.model_catalog import get_catalog_entry, list_catalog

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_legacy_entries_intact() -> None:
    entry = get_catalog_entry("openai", "gpt-4o-mini")
    assert entry is not None and entry.context_window_tokens == 128_000
    assert len(list_catalog()) >= 61


def test_2026_flagships_present() -> None:
    expected = [
        ("openai", "gpt-5.2", 400_000),
        ("openai", "gpt-5.5-pro", 1_050_000),
        ("anthropic", "claude-opus-4-5", 200_000),
        ("anthropic", "claude-sonnet-4-5", 1_000_000),
        ("anthropic", "claude-sonnet-4-6", 1_000_000),
        ("gemini", "gemini-3-pro", 1_048_576),
        ("deepseek", "deepseek-v4-pro", 1_000_000),
        ("qwen", "qwen3.8-max", 1_000_000),
        ("moonshot", "kimi-k3", 1_048_576),
        ("glm", "glm-5.3", 1_000_000),
        ("xai", "grok-4.5", 500_000),
        ("xai", "grok-4.6", 500_000),
        ("openrouter", "meta/muse-spark-1.3", 1_048_576),
        ("openrouter", "meta/muse-spark-1.3-contributor", 1_048_576),
    ]
    for provider, model_id, ctx in expected:
        entry = get_catalog_entry(provider, model_id)
        assert entry is not None, f"missing {provider}/{model_id}"
        assert entry.context_window_tokens == ctx, (provider, model_id)


def test_muse_spark_cost_estimate() -> None:
    entry = get_catalog_entry("openrouter", "meta/muse-spark-1.3-contributor")
    assert entry is not None
    assert entry.estimate_cost_usd(1_000_000, 0) == 0.1  # $0.10 / 1M in
    full = get_catalog_entry("openrouter", "meta/muse-spark-1.3")
    assert full is not None and full.supports_vision and full.supports_streaming


def test_openrouter_provider_accepts_muse_spark_model(monkeypatch) -> None:
    from ghostchimera.model_layer.openai_compatible_providers import OpenRouterProvider

    monkeypatch.setenv("OPENROUTER_MODEL", "meta/muse-spark-1.3-contributor")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = OpenRouterProvider()
    assert provider.model == "meta/muse-spark-1.3-contributor"
    assert provider.available is False  # no key -> cleanly unavailable
    headers = provider._build_headers()
    assert headers["X-Title"] == "Ghost Chimera"
    assert headers["HTTP-Referer"] == "https://github.com/fernandogarzaaa/GHOST-Chimera"
    try:
        provider.chat("sys", "hi")
    except RuntimeError as exc:
        assert "OPENROUTER_API_KEY" in str(exc)
    else:
        raise AssertionError("chat without key must raise")


def test_refresh_models_dev_offline(tmp_path) -> None:
    fixture = {
        "openai": {
            "name": "OpenAI", "env": ["OPENAI_API_KEY"], "doc": "https://x",
            "models": {
                "gpt-5.2": {"name": "GPT 5.2", "limit": {"context": 400000, "output": 128000},
                            "tool_call": True, "reasoning": True,
                            "modalities": {"input": ["text"], "output": ["text"]},
                            "cost": {"input": 1.75, "output": 14}, "release_date": "2026-01-01"},
            },
        }
    }
    src = tmp_path / "api.json"
    src.write_text(json.dumps(fixture), encoding="utf-8")
    out = tmp_path / "snapshot.json"
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "refresh_models_dev.py"),
         "--input", str(src), "--out", str(out)],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    snapshot = json.loads(out.read_text(encoding="utf-8"))
    assert snapshot["source"] == "models.dev"
    models = snapshot["providers"]["openai"]["models"]
    assert models[0]["model_id"] == "gpt-5.2"
    assert models[0]["cost_input_per_1m"] == 1.75
    assert "SECRET" not in json.dumps(snapshot)
