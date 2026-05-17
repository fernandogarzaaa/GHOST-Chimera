from __future__ import annotations

import json
import unittest
from pathlib import Path

from ghostchimera.harness.case import HarnessCase, MemoryDocument
from ghostchimera.harness.runner import HarnessRunner


class HarnessRunnerTests(unittest.TestCase):
    def test_harness_runs_offline_case_and_writes_artifacts(self) -> None:
        with self.subTest("run"), self._tmpdir() as out_dir:
            case = HarnessCase(
                id="case-1",
                objective="retrieve harness memory",
                kernel={"include_deterministic_backend": True, "allow_network": False},
                memory_documents=(MemoryDocument(source="harness", content="Harness memory retrieval works."),),
            )
            runner = HarnessRunner(output_dir=out_dir)
            results = runner.run([case])

            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].ok)
            self.assertEqual(results[0].executions[0]["backend_id"], "cwr.local")

            events = Path(out_dir) / "events.jsonl"
            outputs = Path(out_dir) / "results.jsonl"
            self.assertTrue(events.exists())
            self.assertTrue(outputs.exists())

            last_line = outputs.read_text(encoding="utf-8").splitlines()[-1]
            payload = json.loads(last_line)
            self.assertEqual(payload["id"], "case-1")

    def test_harness_expectations_can_fail(self) -> None:
        with self._tmpdir() as out_dir:
            case = HarnessCase.from_dict(
                {
                    "id": "case-2",
                    "objective": "retrieve harness memory",
                    "kernel": {"include_deterministic_backend": True},
                    "memory_documents": [{"source": "harness", "content": "x"}],
                    "expect": {"backend_ids": ["deterministic.local"]},  # intentionally wrong
                }
            )
            runner = HarnessRunner(output_dir=out_dir)
            result = runner.run_case(case)
            self.assertFalse(result.ok)

    class _tmpdir:
        def __enter__(self) -> str:
            import tempfile

            self._dir = tempfile.TemporaryDirectory(prefix="ghostchimera-harness-")
            return self._dir.name

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            self._dir.cleanup()
