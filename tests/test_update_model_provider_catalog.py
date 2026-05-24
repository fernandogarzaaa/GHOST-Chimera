from __future__ import annotations

from scripts.update_model_provider_catalog import build_snapshot, render_markdown


def test_build_snapshot_limits_models_and_excludes_raw_metadata() -> None:
    cache = {
        "models": {
            "openrouter": [
                {
                    "source": "openrouter",
                    "provider": "openrouter",
                    "model_id": "z",
                    "display_name": "Z",
                    "context_length": 1000,
                    "compatibility_status": "needs_key",
                    "capability_badges": ["text"],
                    "raw_metadata": {"secret_like": "not exported"},
                },
                {
                    "source": "openrouter",
                    "provider": "openrouter",
                    "model_id": "a",
                    "display_name": "A",
                    "context_length": 2000,
                    "compatibility_status": "ready",
                    "capability_badges": ["text", "tool-calling"],
                },
            ]
        },
        "sources": {"openrouter": {"ok": True, "count": 2, "last_refreshed": 10}},
    }

    snapshot = build_snapshot(cache, sources=["openrouter"], generated_at=20, max_models_per_source=1)

    assert snapshot["model_count"] == 1
    assert snapshot["models"][0]["model_id"] == "a"
    assert "raw_metadata" not in snapshot["models"][0]
    assert snapshot["policy"]["secrets_included"] is False


def test_render_markdown_documents_review_then_activate_policy() -> None:
    snapshot = {
        "generated_at_iso": "2026-05-24T00:00:00Z",
        "sources": {"openrouter": {"ok": True, "count": 1, "included_count": 1, "last_refreshed": 20, "error": ""}},
        "models": [
            {
                "source": "openrouter",
                "model_id": "openai/gpt-test",
                "compatibility_status": "needs_key",
                "context_length": 128000,
                "cost_class": "low",
                "capability_badges": ["text", "long-context"],
                "recommended_use_cases": ["analyst"],
            }
        ],
    }

    markdown = render_markdown(snapshot)

    assert "advisory only" in markdown
    assert "openai/gpt-test" in markdown
    assert "long-context" in markdown
