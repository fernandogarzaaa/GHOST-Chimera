from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.control_plane.local_voice import LocalVoiceTranscriber


class LocalVoiceTranscriberTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_command = os.environ.pop("GHOSTCHIMERA_LOCAL_STT_COMMAND", None)

    def tearDown(self) -> None:
        os.environ.pop("GHOSTCHIMERA_LOCAL_STT_COMMAND", None)
        if self._old_command is not None:
            os.environ["GHOSTCHIMERA_LOCAL_STT_COMMAND"] = self._old_command

    def test_status_reports_no_raw_audio_storage_and_provider_guidance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-local-voice-") as tmp:
            status = LocalVoiceTranscriber(tmp).status()

            self.assertTrue(status["ok"])
            self.assertFalse(status["raw_audio_stored"])
            self.assertIn("providers", status)
            self.assertGreaterEqual(len(status["providers"]), 3)
            self.assertIn("browser_network_fallback", status)
            self.assertEqual(
                status["browser_network_fallback"]["endpoint"],
                "/api/console/conversation/local-voice/status",
            )
            self.assertIn("network", status["browser_network_fallback"]["reason"].lower())
            self.assertIn("browser_audio_conversion", status["browser_network_fallback"])
            self.assertTrue(
                any("WebM" in item for item in status["browser_network_fallback"]["configuration"])
            )
            self.assertTrue(any(provider["id"] == "custom-command" for provider in status["providers"]))

    def test_custom_command_transcribes_base64_audio_without_persisting_audio(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-local-voice-") as tmp:
            os.environ["GHOSTCHIMERA_LOCAL_STT_COMMAND"] = f'"{sys.executable}" -c "print(\'hello local ghost\')"'
            audio_base64 = base64.b64encode(b"fake webm bytes").decode("ascii")

            result = LocalVoiceTranscriber(tmp).transcribe_base64(audio_base64, mime_type="audio/webm")

            self.assertTrue(result["ok"])
            self.assertEqual(result["provider"], "custom-command")
            self.assertEqual(result["transcript"], "hello local ghost")
            self.assertFalse(result["raw_audio_stored"])

    def test_invalid_audio_base64_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-local-voice-") as tmp:
            result = LocalVoiceTranscriber(tmp).transcribe_base64("not base64")

            self.assertFalse(result["ok"])
            self.assertIn("valid base64", result["error"])


class LocalVoiceConsoleRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_command = os.environ.pop("GHOSTCHIMERA_LOCAL_STT_COMMAND", None)

    def tearDown(self) -> None:
        os.environ.pop("GHOSTCHIMERA_LOCAL_STT_COMMAND", None)
        if self._old_command is not None:
            os.environ["GHOSTCHIMERA_LOCAL_STT_COMMAND"] = self._old_command

    def test_console_routes_local_voice_turn_through_conversation_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-console-local-voice-") as tmp:
            os.environ["GHOSTCHIMERA_LOCAL_STT_COMMAND"] = f'"{sys.executable}" -c "print(\'run readiness check\')"'
            server = GatewayServer()
            register_console_routes(
                server,
                state_dir=tmp,
                run_objective=lambda objective: {"ok": True, "operator_report": f"ran {objective}"},
            )
            create_route = server.routes.find("POST", "/api/console/conversation/sessions")
            voice_route = server.routes.find("POST", "/api/console/conversation/sessions/demo/local-voice-turn")
            status_route = server.routes.find("GET", "/api/console/conversation/local-voice/status")

            self.assertIsNotNone(create_route)
            self.assertIsNotNone(voice_route)
            self.assertIsNotNone(status_route)

            create_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/conversation/sessions",
                    "headers": {},
                    "body": json.dumps({"session_id": "demo", "always_listening": True}),
                    "query": {},
                }
            )
            result = voice_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/conversation/sessions/demo/local-voice-turn",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "audio_base64": base64.b64encode(b"fake audio").decode("ascii"),
                            "mime_type": "audio/webm",
                        }
                    ),
                    "query": {},
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["local_voice"]["provider"], "custom-command")
            self.assertFalse(result["local_voice"]["raw_audio_stored"])
            self.assertIn("Readiness check", result["reply"])


if __name__ == "__main__":
    unittest.main()
