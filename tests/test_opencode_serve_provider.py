"""Tests for the OpenCode Serve provider (private local ``opencode serve``)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ghostchimera.model_layer.opencode_serve_provider import (
    OpenCodeServeProvider,
    _scrubbed_env,
    _write_lockdown_config,
)


class ModelIdTests(unittest.TestCase):
    def test_strips_opencode_prefix(self) -> None:
        provider = OpenCodeServeProvider.__new__(OpenCodeServeProvider)
        provider.model = "opencode/big-pickle"
        self.assertEqual(provider._model_id(), "big-pickle")

    def test_bare_model_id_passes_through(self) -> None:
        provider = OpenCodeServeProvider.__new__(OpenCodeServeProvider)
        provider.model = "big-pickle"
        self.assertEqual(provider._model_id(), "big-pickle")

    def test_empty_model_falls_back_to_default(self) -> None:
        provider = OpenCodeServeProvider.__new__(OpenCodeServeProvider)
        provider.model = ""
        self.assertEqual(provider._model_id(), "big-pickle")


class ExtractTextTests(unittest.TestCase):
    def test_collects_text_parts(self) -> None:
        message = {
            "parts": [
                {"type": "text", "text": "hello"},
                {"type": "tool", "text": "ignored"},
                {"type": "text", "text": "  world  "},
            ]
        }
        self.assertEqual(OpenCodeServeProvider._extract_text(message), "hello\nworld")

    def test_empty_message_extracts_nothing(self) -> None:
        self.assertEqual(OpenCodeServeProvider._extract_text({}), "")
        self.assertEqual(OpenCodeServeProvider._extract_text(None), "")


class ScrubbedEnvTests(unittest.TestCase):
    def test_removes_secret_like_keys(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"MY_API_KEY": "x", "AUTH_TOKEN": "y", "DB_PASSWORD": "z", "KEEP_ME": "ok"},
            clear=False,
        ):
            env = _scrubbed_env()
        self.assertNotIn("MY_API_KEY", env)
        self.assertNotIn("AUTH_TOKEN", env)
        self.assertNotIn("DB_PASSWORD", env)
        self.assertEqual(env.get("KEEP_ME"), "ok")


class LockdownConfigTests(unittest.TestCase):
    def test_writes_ask_all_and_no_share(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_lockdown_config(tmp)
            config = json.loads(Path(tmp, "opencode.json").read_text(encoding="utf-8"))
        self.assertEqual(config["permission"], {"*": "ask"})
        self.assertEqual(config["share"], "disabled")
        self.assertFalse(config["autoupdate"])


class ValidateConfigTests(unittest.TestCase):
    def test_missing_binary_reports_error(self) -> None:
        with mock.patch(
            "ghostchimera.model_layer.opencode_serve_provider._resolve_opencode_executable",
            return_value=None,
        ):
            provider = OpenCodeServeProvider()
        self.assertFalse(provider.available)
        errors = provider.validate_config()
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0])

    def test_present_binary_validates_clean(self) -> None:
        with mock.patch(
            "ghostchimera.model_layer.opencode_serve_provider._resolve_opencode_executable",
            return_value="/usr/bin/opencode",
        ):
            provider = OpenCodeServeProvider()
        self.assertTrue(provider.available)
        self.assertEqual(provider.validate_config(), [])


class ChatFlowTests(unittest.TestCase):
    def _provider(self) -> OpenCodeServeProvider:
        with mock.patch(
            "ghostchimera.model_layer.opencode_serve_provider._resolve_opencode_executable",
            return_value="/usr/bin/opencode",
        ):
            return OpenCodeServeProvider()

    def test_chat_creates_messages_and_deletes_session(self) -> None:
        provider = self._provider()
        calls: list[tuple[str, str, object]] = []

        def fake_call(handle: object, method: str, path: str, body: object = None) -> object:
            calls.append((method, path, body))
            if method == "POST" and path == "/session":
                return {"id": "sess-1"}
            if path == "/permission":
                return []
            if method == "POST" and path.endswith("/message"):
                return {"parts": [{"type": "text", "text": "hi there"}]}
            return None

        handle = mock.MagicMock()
        with (
            mock.patch.object(provider, "_ensure_server", return_value=handle),
            mock.patch.object(provider, "_call", side_effect=fake_call),
        ):
            answer = provider.chat("sys", "hello")

        self.assertEqual(answer, "hi there")
        methods_paths = [(method, path) for method, path, _ in calls]
        self.assertIn(("POST", "/session"), methods_paths)
        self.assertIn(("POST", "/session/sess-1/message"), methods_paths)
        self.assertIn(("DELETE", "/session/sess-1"), methods_paths)

    def test_chat_sends_model_and_locks_down_tools(self) -> None:
        provider = self._provider()
        provider.model = "opencode/mimo-v2.5-free"
        seen: dict[str, object] = {}

        def fake_call(handle: object, method: str, path: str, body: object = None) -> object:
            if path.endswith("/message"):
                seen["body"] = body
                return {"parts": [{"type": "text", "text": "ok"}]}
            if method == "POST" and path == "/session":
                return {"id": "s"}
            return []

        handle = mock.MagicMock()
        with (
            mock.patch.object(provider, "_ensure_server", return_value=handle),
            mock.patch.object(provider, "_call", side_effect=fake_call),
        ):
            provider.chat("be brief", "ping")

        body = seen["body"]
        assert isinstance(body, dict)
        self.assertEqual(body["model"], {"providerID": "opencode", "modelID": "mimo-v2.5-free"})
        assert isinstance(body["system"], str)
        self.assertIn("Do not use tools", body["system"])

    def test_chat_raises_when_unavailable(self) -> None:
        with mock.patch(
            "ghostchimera.model_layer.opencode_serve_provider._resolve_opencode_executable",
            return_value=None,
        ):
            provider = OpenCodeServeProvider()
        with self.assertRaises(RuntimeError):
            provider.chat("sys", "hello")

    def test_chat_raises_on_empty_answer(self) -> None:
        provider = self._provider()

        def fake_call(handle: object, method: str, path: str, body: object = None) -> object:
            if method == "POST" and path == "/session":
                return {"id": "s"}
            if path.endswith("/message"):
                return {"parts": []}
            return []

        handle = mock.MagicMock()
        with (
            mock.patch.object(provider, "_ensure_server", return_value=handle),
            mock.patch.object(provider, "_call", side_effect=fake_call),
            self.assertRaises(RuntimeError),
        ):
            provider.chat("sys", "hello")


class ToDictTests(unittest.TestCase):
    def test_to_dict_shape(self) -> None:
        with mock.patch(
            "ghostchimera.model_layer.opencode_serve_provider._resolve_opencode_executable",
            return_value="/usr/bin/opencode",
        ):
            provider = OpenCodeServeProvider()
        data = provider.to_dict()
        self.assertEqual(data["name"], "opencode_serve")
        self.assertTrue(data["available"])
        self.assertIn("model", data)


if __name__ == "__main__":
    unittest.main()
