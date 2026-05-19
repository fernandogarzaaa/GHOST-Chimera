from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.context_compressor import compress_text_query_aware
from ghostchimera.cognition_layer.trust import (
    GhostBelief,
    GhostHandoff,
    guard_belief,
    pack_handoff,
    summarize_operational_trace,
    verify_handoff,
)
from ghostchimera.mcp.normalization import normalize_mcp_server_entry
from ghostchimera.model_layer.local_model_inventory import (
    HardwareProfile,
    discover_local_model_inventory,
    recommend_quantization,
    resolve_model_source,
)


class GhostCognitionTrustTests(unittest.TestCase):
    def test_belief_guard_checks_confidence_and_variance(self) -> None:
        passed = guard_belief(GhostBelief.from_confidence("claim", 0.86, variance=0.02), max_risk=0.2)
        failed = guard_belief(GhostBelief.from_confidence("claim", 0.86, variance=0.09), max_risk=0.2)

        self.assertTrue(passed.passed)
        self.assertFalse(failed.passed)
        self.assertIn("variance", failed.violation)

    def test_handoff_rejects_tampered_payload(self) -> None:
        handoff = pack_handoff(
            sender="planner",
            receiver="executor",
            tool="ghost.guard",
            args={"confidence": 0.91},
            payload={"passed": True, "confidence": 0.91},
            summary_text="Planner passed a confidence gate.",
        )
        verified = verify_handoff(handoff)
        self.assertTrue(verified.accepted)

        tampered = GhostHandoff.from_json(handoff.to_json())
        tampered.payload["confidence"] = 0.1
        rejected = verify_handoff(tampered)
        self.assertFalse(rejected.accepted)
        self.assertIn("hash", rejected.failure_reason)

    def test_operational_trace_has_safe_stage_labels(self) -> None:
        trace = summarize_operational_trace(
            goal="prepare release",
            sources=["workspace", "release checklist"],
            policy_decision="approval_required",
            tool_candidates=["pytest", "validate_release"],
        )
        stages = [stage["stage"] for stage in trace["stages"]]
        self.assertEqual(stages[0], "goal_intake")
        self.assertIn("policy_check", stages)
        self.assertNotIn("chain_of_thought", json.dumps(trace))


class QueryAwareCompressionTests(unittest.TestCase):
    def test_query_aware_compression_preserves_code_blocks_and_focus_terms(self) -> None:
        text = """
        This release note is very very important.
        ```python
        print("keep me")
        ```
        Latency latency latency budget budget budget matters for the model route.
        Please note that latency budget matters for the model route.
        """
        result = compress_text_query_aware(text, budget_tokens=45, focus="latency model route")

        self.assertTrue(result.ok)
        self.assertIn("```python", result.text)
        self.assertIn("print(\"keep me\")", result.text)
        self.assertLess(result.compressed_tokens, result.original_tokens)
        self.assertIn("latency", result.focus_terms)


class NativeLocalModelInventoryTests(unittest.TestCase):
    def test_resolver_handles_hf_id_hf_url_local_gguf_and_invalid_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-local-models-") as tmp:
            gguf = Path(tmp) / "llama-3.1-8b.Q4_K_M.gguf"
            gguf.write_text("fake", encoding="utf-8")

            hf_id = resolve_model_source("Qwen/Qwen2.5-7B-Instruct")
            hf_url = resolve_model_source("https://huggingface.co/org/model/resolve/main/model.Q5_K_M.gguf")
            local = resolve_model_source(str(gguf))
            invalid = resolve_model_source(str(Path(tmp) / "missing.gguf"))

        self.assertEqual(hf_id.source_type, "huggingface_model")
        self.assertEqual(hf_url.source_type, "huggingface_file")
        self.assertEqual(hf_url.quantization, "Q5_K_M")
        self.assertEqual(local.source_type, "local_gguf")
        self.assertEqual(local.quantization, "Q4_K_M")
        self.assertEqual(invalid.compatibility_status, "missing")

    def test_inventory_discovers_local_gguf_and_safetensors_preview_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-inventory-") as tmp:
            root = Path(tmp)
            (root / "phi-3.5-mini.Q4_K_M.gguf").write_text("fake", encoding="utf-8")
            (root / "model.safetensors").write_text("fake", encoding="utf-8")
            inventory = discover_local_model_inventory([root])

        self.assertEqual(inventory["policy"]["activation"], "preview_only")
        self.assertEqual(inventory["count"], 2)
        self.assertTrue(all(not item["auto_download"] for item in inventory["models"]))

    def test_quantization_recommendation_uses_hardware_budget(self) -> None:
        tiny = HardwareProfile(ram_mb=8192, free_ram_mb=4096, usable_vram_mb=0, cpu_cores=4)
        strong = HardwareProfile(ram_mb=65536, free_ram_mb=32000, usable_vram_mb=24576, cpu_cores=16)

        self.assertIn(recommend_quantization(3.0, tiny), {"Q4_K_M", "Q5_K_M"})
        self.assertIn(recommend_quantization(7.0, strong), {"Q6_K", "Q8_0", "F16"})


class MCPNormalizationTests(unittest.TestCase):
    def test_normalize_mcp_server_entry_has_stable_safe_fields(self) -> None:
        entry = normalize_mcp_server_entry(
            "chimera-lang",
            {"command": "python", "args": ["-m", "server"], "api_key": "secret-value"},
            source_path="local.json",
        )

        self.assertEqual(entry["id"], "chimera-lang")
        self.assertEqual(entry["transport"], "stdio")
        self.assertEqual(entry["status"], "registered")
        self.assertNotIn("api_key", entry)
        self.assertEqual(entry["source"], "local.json")

