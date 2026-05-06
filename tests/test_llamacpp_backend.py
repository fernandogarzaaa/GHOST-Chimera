from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from ghostchimera.chimera_pilot import ChimeraPilotKernel, TaskKind, TaskSpec
from ghostchimera.chimera_pilot.backends.llamacpp import LlamaCppBackend
from ghostchimera.model_layer.providers import LlamaCppProvider


class LlamaCppRuntimeTests(unittest.TestCase):
    def test_backend_reports_unavailable_without_runtime_or_model_path(self) -> None:
        with patch.dict(sys.modules, {"llama_cpp": None}):
            backend = LlamaCppBackend(model_path="")
            health = backend.probe()

        self.assertFalse(health.available)
        self.assertIn("model path", health.last_error or "")

    def test_provider_uses_fake_llama_cpp_chat_completion(self) -> None:
        fake = types.ModuleType("llama_cpp")
        calls: list[dict] = []

        class FakeLlama:
            def __init__(self, **kwargs):
                calls.append({"init": kwargs})

            def create_chat_completion(self, messages, **kwargs):
                calls.append({"messages": messages, "kwargs": kwargs})
                return {"choices": [{"message": {"content": "local llama response"}}]}

        fake.Llama = FakeLlama  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory(prefix="ghostchimera-llama-test-") as tmp:
            model_path = Path(tmp) / "tiny.gguf"
            model_path.write_bytes(b"fake")
            with patch.dict(sys.modules, {"llama_cpp": fake}):
                with patch.dict(
                    os.environ,
                    {
                        "LLAMACPP_MODEL_PATH": str(model_path),
                        "LLAMACPP_MODEL_PROFILE": "tiny",
                        "LLAMACPP_N_GPU_LAYERS": "12",
                    },
                    clear=False,
                ):
                    provider = LlamaCppProvider()
                    response = provider.chat("system", "hello")

        self.assertTrue(provider.available)
        self.assertEqual(response, "local llama response")
        self.assertEqual(calls[0]["init"]["model_path"], str(model_path))
        self.assertEqual(calls[0]["init"]["n_ctx"], 8192)
        self.assertEqual(calls[0]["init"]["n_gpu_layers"], 12)

    def test_backend_runs_reasoning_task_with_fake_llama_cpp(self) -> None:
        fake = types.ModuleType("llama_cpp")

        class FakeLlama:
            def __init__(self, **_kwargs):
                self.kwargs = _kwargs

            def create_chat_completion(self, messages, **_kwargs):
                return {"choices": [{"message": {"content": f"answer: {messages[-1]['content']}"}}]}

        fake.Llama = FakeLlama  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory(prefix="ghostchimera-llama-test-") as tmp:
            model_path = Path(tmp) / "tiny.gguf"
            model_path.write_bytes(b"fake")
            with patch.dict(sys.modules, {"llama_cpp": fake}):
                backend = LlamaCppBackend(model_path=str(model_path), profile_name="tiny")
                task = TaskSpec.create(kind=TaskKind.REASONING, objective="summarize local runtime")
                result = backend.execute(task)

        self.assertTrue(result.ok)
        self.assertEqual(result.backend_id, "llamacpp.local")
        self.assertIn("summarize local runtime", result.output)

    def test_kernel_can_register_optional_llama_backend(self) -> None:
        fake = types.ModuleType("llama_cpp")

        class FakeLlama:
            def __init__(self, **_kwargs):
                self.kwargs = _kwargs

            def create_chat_completion(self, messages, **_kwargs):
                return {"choices": [{"message": {"content": "kernel local answer"}}]}

        fake.Llama = FakeLlama  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory(prefix="ghostchimera-llama-test-") as tmp:
            model_path = Path(tmp) / "tiny.gguf"
            model_path.write_bytes(b"fake")
            with patch.dict(sys.modules, {"llama_cpp": fake}):
                kernel = ChimeraPilotKernel.default(local_model_path=str(model_path), local_model_profile="tiny")
                execution = kernel.run("explain local runtime")[0]

        self.assertTrue(execution.ok)
        self.assertEqual(execution.result.backend_id, "llamacpp.local")
        self.assertEqual(execution.result.output, "kernel local answer")

    def test_cli_lists_model_profiles(self) -> None:
        import json
        import subprocess

        completed = subprocess.run(
            [sys.executable, "-m", "ghostchimera.chimera_pilot.cli", "model-profiles"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertIn("tiny", [profile["name"] for profile in payload["profiles"]])


if __name__ == "__main__":
    unittest.main()
