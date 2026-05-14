"""Tests for persisted Ghost path selection."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ghostchimera.personalization.path_state import get_active_ghost_path, set_active_ghost_path


class PathStateTests(unittest.TestCase):
    def test_set_active_ghost_path_persists_synthesized_profile(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-path-state-") as tmp:
            config_path = Path(tmp) / "config.json"

            saved = set_active_ghost_path(
                "ai-engineer-proxy",
                preferences={"training_mode": "rag-first", "approval_level": "supervised"},
                config_path=config_path,
            )
            loaded = get_active_ghost_path(config_path=config_path)

        self.assertEqual(saved["profile_id"], "ai-engineer-proxy")
        self.assertEqual(loaded["profile_id"], "ai-engineer-proxy")
        self.assertEqual(loaded["synthesis"]["role"]["id"], "ai-engineer-proxy")
        self.assertTrue(loaded["synthesis"]["proxy_policy"]["disclosure_required"])


if __name__ == "__main__":
    unittest.main()
