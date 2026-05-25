from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.model_layer.model_discovery import (
    DEFAULT_SOURCES,
    get_model_discovery,
    normalize_huggingface_models,
    normalize_openrouter_models,
    normalize_vultr_models,
    refresh_model_discovery,
    save_model_discovery_cache,
    select_discovered_model,
)


class ModelDiscoveryTests(unittest.TestCase):
    def test_default_sources_include_local_discovery(self) -> None:
        self.assertIn("openrouter", DEFAULT_SOURCES)
        self.assertIn("local", DEFAULT_SOURCES)

    def test_normalizes_openrouter_model_as_compatible_needing_key(self) -> None:
        payload = {
            "data": [
                {
                    "id": "openai/gpt-4o-mini",
                    "name": "GPT-4o mini",
                    "description": "Fast multimodal model.",
                    "context_length": 128000,
                    "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
                    "supported_parameters": ["temperature", "tools", "max_tokens"],
                    "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                }
            ]
        }

        models = normalize_openrouter_models(payload, has_api_key=False, timestamp=123.0)

        self.assertEqual(len(models), 1)
        model = models[0].to_dict()
        self.assertEqual(model["provider"], "openrouter")
        self.assertEqual(model["compatibility_status"], "needs_key")
        self.assertIn("vision", model["capability_badges"])
        self.assertIn("tool-calling", model["capability_badges"])
        self.assertIn("long-context", model["capability_badges"])

    def test_normalizes_vultr_model_as_ready(self) -> None:
        payload = {"data": [{"id": "kimi-k2-instruct", "features": ["tool_choice"], "created": "2026-01-01"}]}

        model = normalize_vultr_models(payload, timestamp=456.0)[0].to_dict()

        self.assertEqual(model["source"], "vultr")
        self.assertEqual(model["provider"], "vultr")
        self.assertEqual(model["compatibility_status"], "ready")
        self.assertIn("tool-calling", model["capability_badges"])

    def test_huggingface_models_are_candidate_only(self) -> None:
        payload = [{"modelId": "mistralai/Mistral-7B-Instruct-v0.3", "tags": ["text-generation", "safetensors"]}]

        model = normalize_huggingface_models(payload, has_api_key=True, timestamp=789.0)[0].to_dict()

        self.assertEqual(model["provider"], "huggingface")
        self.assertEqual(model["compatibility_status"], "candidate_only")
        self.assertIn("open-weight", model["capability_badges"])

    def test_refresh_uses_saved_key_without_echoing_it(self) -> None:
        calls: list[tuple[str, dict[str, str]]] = []

        def fake_fetch(url: str, headers: dict[str, str], timeout: float):
            calls.append((url, headers))
            return {
                "data": [
                    {
                        "id": "meta-llama/llama-3.3-70b-instruct",
                        "name": "Llama 3.3 70B",
                        "pricing": {"prompt": "0.00000059", "completion": "0.00000079"},
                        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                    }
                ]
            }

        with tempfile.TemporaryDirectory(prefix="ghostchimera-model-discovery-") as tmp:
            result = refresh_model_discovery(
                config={"model": {"provider": "openrouter", "api_key": "router-secret"}},
                state_dir=tmp,
                sources=["openrouter"],
                fetch_json=fake_fetch,
                now=1000.0,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(calls[0][1]["Authorization"], "Bearer router-secret")
            serialized = json.dumps(result)
            self.assertNotIn("router-secret", serialized)
            self.assertEqual(result["models"][0]["compatibility_status"], "ready")
            self.assertTrue((Path(tmp) / "model_discovery_cache.json").exists())

    def test_refresh_keeps_source_error_when_vultr_key_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-model-discovery-") as tmp:
            result = refresh_model_discovery(config={"model": {}}, state_dir=tmp, sources=["vultr"], now=1000.0)

            self.assertTrue(result["ok"])
            self.assertFalse(result["sources"]["vultr"]["ok"])
            self.assertIn("not configured", result["sources"]["vultr"]["error"])

    def test_refresh_reports_model_change_alerts(self) -> None:
        def fake_fetch(url: str, headers: dict[str, str], timeout: float):
            return {
                "data": [
                    {
                        "id": "openai/gpt-4o-mini",
                        "name": "GPT-4o mini",
                        "pricing": {"prompt": "0.0000001", "completion": "0.0000002"},
                        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                    }
                ]
            }

        with tempfile.TemporaryDirectory(prefix="ghostchimera-model-discovery-") as tmp:
            save_model_discovery_cache(
                tmp,
                {
                    "version": 1,
                    "sources": {"openrouter": {"ok": True, "count": 1}},
                    "models": {
                        "openrouter": [
                            {
                                "source": "openrouter",
                                "provider": "openrouter",
                                "model_id": "openai/gpt-4o-mini",
                                "display_name": "GPT-4o mini",
                                "compatibility_status": "needs_key",
                                "pricing": {"prompt": "0.0000009"},
                                "capability_badges": ["text"],
                            }
                        ]
                    },
                },
            )

            result = refresh_model_discovery(
                config={"model": {}}, state_dir=tmp, sources=["openrouter"], fetch_json=fake_fetch, now=1000.0
            )

            self.assertTrue(result["alerts"])
            self.assertEqual(result["alerts"][0]["kind"], "pricing_changed")

    def test_get_model_discovery_filters_cached_capabilities(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-model-discovery-") as tmp:
            save_model_discovery_cache(
                tmp,
                {
                    "version": 1,
                    "sources": {"openrouter": {"ok": True, "count": 2}},
                    "models": {
                        "openrouter": [
                            {
                                "source": "openrouter",
                                "provider": "openrouter",
                                "model_id": "cheap",
                                "display_name": "Cheap",
                                "compatibility_status": "needs_key",
                                "capability_badges": ["text", "low-cost"],
                                "modalities": ["text"],
                            },
                            {
                                "source": "openrouter",
                                "provider": "openrouter",
                                "model_id": "vision",
                                "display_name": "Vision",
                                "compatibility_status": "needs_key",
                                "capability_badges": ["text", "vision"],
                                "modalities": ["text", "image"],
                            },
                        ]
                    },
                },
            )

            result = get_model_discovery(
                config={"model": {}}, state_dir=tmp, sources=["openrouter"], capabilities=["vision"]
            )

            self.assertEqual(result["model_count"], 1)
            self.assertEqual(result["models"][0]["model_id"], "vision")
            self.assertGreaterEqual(result["provider_catalog"]["count"], 20)
            self.assertIn("ollama", result["provider_catalog"]["local_private"])

    def test_select_discovered_model_updates_config_only_for_selectable_models(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-model-discovery-") as tmp:
            save_model_discovery_cache(
                tmp,
                {
                    "version": 1,
                    "sources": {"openrouter": {"ok": True, "count": 1}},
                    "models": {
                        "openrouter": [
                            {
                                "source": "openrouter",
                                "provider": "openrouter",
                                "model_id": "openai/gpt-4o-mini",
                                "display_name": "GPT-4o mini",
                                "compatibility_status": "needs_key",
                            },
                            {
                                "source": "openrouter",
                                "provider": "huggingface",
                                "model_id": "owner/model",
                                "display_name": "Candidate",
                                "compatibility_status": "candidate_only",
                            },
                        ]
                    },
                },
            )

            selected = select_discovered_model(
                config={"model": {"provider": "minimind"}},
                state_dir=tmp,
                source="openrouter",
                provider="openrouter",
                model_id="openai/gpt-4o-mini",
            )
            rejected = select_discovered_model(
                config={"model": {}},
                state_dir=tmp,
                source="openrouter",
                provider="huggingface",
                model_id="owner/model",
            )

            self.assertTrue(selected["ok"])
            self.assertEqual(selected["config"]["model"]["provider"], "openrouter")
            self.assertEqual(selected["config"]["model"]["model"], "openai/gpt-4o-mini")
            self.assertTrue(selected["requires_api_key"])
            self.assertFalse(rejected["ok"])
            self.assertIn("candidate", rejected["error"])


if __name__ == "__main__":
    unittest.main()
