from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.model_layer.local_profiles import get_local_model_profile
from ghostchimera.model_layer.runtime_specialization import (
    RuntimeEnvironment,
    WorkloadPhase,
    WorkloadShape,
    plan_runtime_specialization,
    workload_from_messages,
)


class RuntimeSpecializationTests(unittest.TestCase):
    def test_decode_workload_uses_latency_plan(self) -> None:
        profile = get_local_model_profile("tiny")
        plan = plan_runtime_specialization(
            profile=profile,
            workload=WorkloadShape(input_tokens=64, output_tokens=2, dtype="bf16"),
            environment=RuntimeEnvironment(n_gpu_layers=20, architecture="sm100", sm_count=160, cute_dsl_available=True),
        )

        self.assertEqual(plan.phase, WorkloadPhase.DECODE)
        self.assertEqual(plan.execution_path, "llama_cpp.gpu_with_cute_dsl_hints")
        self.assertEqual(plan.load_width_bits, 256)
        self.assertEqual(plan.vector_width_elements, 16)
        self.assertEqual(plan.recommended_warps, 1)
        self.assertTrue(plan.use_grid_barrier)
        self.assertEqual(plan.llama_cpp_n_batch, 128)

    def test_prefill_workload_uses_throughput_batching_and_manifest_cache(self) -> None:
        profile = get_local_model_profile("balanced")

        with tempfile.TemporaryDirectory(prefix="ghostchimera-specialization-") as tmp:
            plan = plan_runtime_specialization(
                profile=profile,
                workload=WorkloadShape(input_tokens=1500, output_tokens=256, dtype="q4"),
                environment=RuntimeEnvironment(n_gpu_layers=0, cute_dsl_available=False),
                cache_dir=tmp,
            )
            manifest = Path(tmp) / f"{plan.cache_key}.json"

            self.assertEqual(plan.phase, WorkloadPhase.PREFILL)
            self.assertEqual(plan.execution_path, "llama_cpp.cpu")
            self.assertEqual(plan.vector_width_elements, 32)
            self.assertEqual(plan.llama_cpp_n_batch, 2048)
            self.assertTrue(manifest.exists())
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["cache_key"], plan.cache_key)

    def test_workload_from_messages_estimates_shape_without_tokenizer(self) -> None:
        workload = workload_from_messages(
            system_message="system",
            user_message="abcd" * 100,
            estimated_output_tokens=8,
            batch_size=2,
        )

        self.assertGreaterEqual(workload.input_tokens, 100)
        self.assertEqual(workload.output_tokens, 8)
        self.assertEqual(workload.batch_size, 2)
        self.assertIn(workload.phase(), {WorkloadPhase.DECODE, WorkloadPhase.HYBRID, WorkloadPhase.PREFILL})


if __name__ == "__main__":
    unittest.main()
