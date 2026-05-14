"""Tests for GitHub task audit records."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.integrations.github_audit import GitHubAuditLog


class GitHubAuditTests(unittest.TestCase):
    def test_audit_log_appends_jsonl_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = GitHubAuditLog(Path(tmp))
            path = log.record("owner/repo", "issue-plan", {"issue": 42, "approved": True})
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(records[0]["repo"], "owner/repo")
        self.assertEqual(records[0]["event"], "issue-plan")
        self.assertTrue(records[0]["payload"]["approved"])


if __name__ == "__main__":
    unittest.main()
