"""Tests for BatchAgent and ParallelAgent."""

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.agent_pool import BatchAgent, ParallelAgent


class TestBatchAgent(unittest.TestCase):
    def test_run_single_objective(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BatchAgent(
                objectives=["test objective"],
                workers=1,
                output_dir=tmpdir,
            )
            summary = runner.run()
            self.assertEqual(summary.total_tasks, 1)
            self.assertEqual(summary.successful_tasks, 1)

    def test_run_multiple_objectives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BatchAgent(
                objectives=["obj1", "obj2", "obj3"],
                workers=2,
                output_dir=tmpdir,
            )
            summary = runner.run()
            self.assertEqual(summary.total_tasks, 3)
            self.assertEqual(summary.successful_tasks, 3)

    def test_run_output_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BatchAgent(
                objectives=["hello"],
                workers=1,
                output_dir=tmpdir,
            )
            summary = runner.run()
            output_path = Path(tmpdir)
            self.assertTrue((output_path / "results.jsonl").exists())
            self.assertTrue((output_path / "summary.json").exists())


class TestParallelAgent(unittest.TestCase):
    def test_run_from_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "objectives.jsonl"
            with open(jsonl_path, "w") as f:
                f.write(json.dumps({"objective": "hello"}) + "\n")
                f.write(json.dumps({"objective": "world"}) + "\n")

            output_dir = Path(tmpdir) / "output"
            runner = ParallelAgent(
                jsonl_file=str(jsonl_path),
                workers=1,
                output_dir=str(output_dir),
            )
            summary = runner.run()
            self.assertEqual(summary.total_tasks, 2)

    def test_run_from_jsonl_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "empty.jsonl"
            jsonl_path.write_text("")

            runner = ParallelAgent(
                jsonl_file=str(jsonl_path),
                workers=1,
                output_dir=tmpdir,
            )
            summary = runner.run()
            self.assertEqual(summary.total_tasks, 0)
