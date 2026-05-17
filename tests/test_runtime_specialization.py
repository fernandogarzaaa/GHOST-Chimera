from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ghostchimera.model_layer.local_profiles import get_local_model_profile
from ghostchimera.model_layer.runtime_specialization import (
    RuntimeEnvironment,
    WorkloadPhase,
    WorkloadShape,
    plan_runtime_specialization,
    warm_runtime_specialization_cache,
    workload_from_messages,
)


class RuntimeSpecializationTests(unittest.TestCase):
    def test_decode_workload_uses_latency_plan(self) -> None:
        profile = get_local_model_profile("tiny")
        plan = plan_runtime_specialization(
            profile=profile,
            workload=WorkloadShape(input_tokens=64, output_tokens=2, dtype="bf16"),
            environment=RuntimeEnvironment(
                n_gpu_layers=20, architecture="sm100", sm_count=160, cute_dsl_available=True
            ),
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

    def test_warmup_cache_writes_profile_manifest_index(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-warmup-") as tmp:
            payload = warm_runtime_specialization_cache(
                cache_dir=tmp,
                profile_names=["tiny"],
                environment=RuntimeEnvironment(n_gpu_layers=12, architecture="sm100", sm_count=160),
            )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["profiles"], ["tiny"])
            self.assertEqual(payload["manifest_count"], 3)
            self.assertTrue(Path(payload["index_path"]).exists())
            for manifest_path in payload["manifest_paths"]:
                self.assertTrue(Path(manifest_path).exists())
            phases = {item["plan"]["phase"] for item in payload["plans"]}
            self.assertEqual(phases, {"decode", "hybrid", "prefill"})

    def test_chimera_pilot_cli_warms_runtime_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-warmup-cli-") as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.chimera_pilot.cli",
                    "runtime-warmup",
                    "--runtime-specialization-cache-dir",
                    tmp,
                    "--local-model-profile",
                    "tiny",
                    "--local-model-gpu-layers",
                    "12",
                    "--gpu-architecture",
                    "sm100",
                    "--gpu-sm-count",
                    "160",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["manifest_count"], 3)
            self.assertTrue(Path(tmp, "index.json").exists())


if __name__ == "__main__":
    unittest.main()
