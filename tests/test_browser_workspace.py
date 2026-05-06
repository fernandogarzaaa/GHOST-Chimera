"""Tests for optional agent-browser workspace integration."""

from __future__ import annotations

import subprocess
import unittest

from ghostchimera.tool_layer.browser_workspace import AgentBrowserWorkspace


class AgentBrowserWorkspaceTests(unittest.TestCase):
    def test_status_reports_unavailable_when_binary_missing(self) -> None:
        workspace = AgentBrowserWorkspace(binary="definitely-missing-agent-browser")

        status = workspace.status()

        self.assertFalse(status["available"])
        self.assertEqual(status["binary"], "definitely-missing-agent-browser")
        self.assertIn("not found", status["detail"])

    def test_snapshot_runs_agent_browser_with_safe_session(self) -> None:
        calls: list[list[str]] = []

        def runner(command, **kwargs):
            calls.append(list(command))
            return subprocess.CompletedProcess(command, 0, stdout="@e1 [heading] Example", stderr="")

        workspace = AgentBrowserWorkspace(binary="agent-browser", runner=runner, resolver=lambda binary: binary)

        result = workspace.snapshot(url="https://example.com", session="demo")

        self.assertTrue(result["ok"])
        self.assertEqual(result["output"], "@e1 [heading] Example")
        self.assertEqual(calls[0], ["agent-browser", "--session", "demo", "open", "https://example.com"])
        self.assertEqual(calls[1], ["agent-browser", "--session", "demo", "snapshot", "-i"])

    def test_rejects_unsafe_urls_and_session_names(self) -> None:
        workspace = AgentBrowserWorkspace(binary="agent-browser", runner=lambda *args, **kwargs: None, resolver=lambda binary: binary)

        with self.assertRaises(ValueError):
            workspace.open("http://example.com")

        with self.assertRaises(ValueError):
            workspace.snapshot(url="https://example.com", session="../bad")


if __name__ == "__main__":
    unittest.main()
