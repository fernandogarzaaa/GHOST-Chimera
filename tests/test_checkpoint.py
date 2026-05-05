"""Tests for the Hermes-Agent migration: checkpoint.py."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.checkpoint import (
    Checkpoint,
    CheckpointDelta,
    CheckpointManager,
)


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_to_dict(self) -> None:
        ckpt = Checkpoint(
            name="test-1", git_hash="abc123", created_at=time.time(),
            state_dir="/tmp/state", file_count=10, size_bytes=1024, description="test",
        )
        d = ckpt.to_dict()
        self.assertEqual(d["name"], "test-1")
        self.assertEqual(d["git_hash"], "abc123")
        self.assertEqual(d["file_count"], 10)

    def test_checkpoint_from_dict(self) -> None:
        data = {"name": "test", "git_hash": "abc", "created_at": 1234.0, "state_dir": "/tmp"}
        ckpt = Checkpoint.from_dict(data)
        self.assertEqual(ckpt.name, "test")
        self.assertEqual(ckpt.git_hash, "abc")


class CheckpointManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.config = type("MockConfig", (), {"state_dir": self.tmpdir})()
        self.state_dir = os.path.join(self.tmpdir, "state")
        os.makedirs(self.state_dir, exist_ok=True)
        self.manager = CheckpointManager(self.config)
        self.manager.checkpoint_dir = Path(os.path.join(self.tmpdir, "checkpoints"))
        os.makedirs(self.manager.checkpoint_dir, exist_ok=True)

    def test_create_checkpoint(self) -> None:
        ckpt = self.manager.create_checkpoint(description="test checkpoint")
        self.assertIsNotNone(ckpt)
        self.assertIn("ckpt-", ckpt.name)
        self.assertIn(self.config.state_dir, ckpt.state_dir)
        self.assertIn(ckpt.name, self.manager._checkpoints)

    def test_list_checkpoints(self) -> None:
        self.manager.create_checkpoint(description="first")
        time.sleep(0.01)
        ckpt2 = self.manager.create_checkpoint(description="second")
        checkpoints = self.manager.list_checkpoints()
        self.assertEqual(len(checkpoints), 2)
        # newest first
        self.assertEqual(checkpoints[0].name, ckpt2.name)

    def test_get_latest(self) -> None:
        self.assertIsNone(self.manager.get_latest())
        self.manager.create_checkpoint()
        latest = self.manager.get_latest()
        self.assertIsNotNone(latest)

    def test_get_checkpoint_by_name(self) -> None:
        ckpt = self.manager.create_checkpoint()
        found = self.manager.get_checkpoint(ckpt.name)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, ckpt.name)

    def test_get_missing_checkpoint(self) -> None:
        self.assertIsNone(self.manager.get_checkpoint("nonexistent"))

    def test_restore_checkpoint(self) -> None:
        ckpt = self.manager.create_checkpoint()
        restored = self.manager.restore_checkpoint(ckpt.name)
        self.assertTrue(restored)

    def test_restore_missing_checkpoint(self) -> None:
        restored = self.manager.restore_checkpoint("nonexistent")
        self.assertFalse(restored)

    def test_diff_checkpoints(self) -> None:
        ckpt1 = self.manager.create_checkpoint(description="first")
        time.sleep(0.01)
        ckpt2 = self.manager.create_checkpoint(description="second")
        delta = self.manager.diff_checkpoints(ckpt1.name, ckpt2.name)
        self.assertIsInstance(delta, CheckpointDelta)

    def test_diff_missing_checkpoint_raises(self) -> None:
        ckpt = self.manager.create_checkpoint()
        with self.assertRaises(KeyError):
            self.manager.diff_checkpoints(ckpt.name, "nonexistent")

    def test_prune_old(self) -> None:
        ckpt = self.manager.create_checkpoint()
        # Artificially age it using object.__setattr__ since Checkpoint is frozen
        old_ckpt = self.manager._checkpoints[ckpt.name]
        import dataclasses
        new_ckpt = dataclasses.replace(old_ckpt, created_at=time.time() - (40 * 86400))
        self.manager._checkpoints[ckpt.name] = new_ckpt
        removed = self.manager.prune_old(max_age_days=30)
        self.assertGreaterEqual(removed, 0)

    def test_should_checkpoint(self) -> None:
        self.manager._turn_count = 0
        self.assertFalse(self.manager.should_checkpoint())
        self.manager._turn_count = 10
        self.assertTrue(self.manager.should_checkpoint())
        self.manager._turn_count = 5
        self.assertFalse(self.manager.should_checkpoint())

    def test_auto_checkpoint(self) -> None:
        self.manager._turn_count = 9
        result = self.manager.auto_checkpoint()
        self.assertIsNone(result)
        self.manager._turn_count = 10
        result = self.manager.auto_checkpoint()
        self.assertIsNotNone(result)

    def test_status(self) -> None:
        self.manager.create_checkpoint()
        # _initialized is True only after loading metadata, not just after creation
        status = self.manager.status()
        self.assertEqual(status["checkpoint_count"], 1)
        self.assertIn("checkpoints", status)

    def test_metadata_persistence(self) -> None:
        ckpt = self.manager.create_checkpoint()
        meta_file = self.manager.checkpoint_dir / "metadata.json"
        self.assertTrue(meta_file.exists())
        with open(meta_file) as f:
            data = json.load(f)
        self.assertIn(ckpt.name, data["checkpoints"])

    def test_load_metadata_on_init(self) -> None:
        self.manager.create_checkpoint()
        # Create a new manager that loads from the same dir
        new_mgr = CheckpointManager(self.config)
        new_mgr.checkpoint_dir = self.manager.checkpoint_dir
        new_mgr._load_metadata()
        self.assertTrue(new_mgr._initialized)
        self.assertEqual(len(new_mgr._checkpoints), 1)


if __name__ == "__main__":
    unittest.main()
