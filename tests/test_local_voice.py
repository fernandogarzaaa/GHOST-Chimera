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
            self.assertTrue(any("WebM" in item for item in status["browser_network_fallback"]["configuration"]))
            self.assertTrue(any(provider["id"] == "custom-command" for provider in status["providers"]))

    def test_custom_command_transcribes_base64_audio_without_persisting_audio(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-local-voice-") as tmp:
            os.environ["GHOSTCHIMERA_LOCAL_STT_COMMAND"] = f'"{sys.executable}" -c "print(\'hello local ghost\')"'
            # Realistic payload size (sub-KB clips are rejected as empty recordings).
            audio_base64 = base64.b64encode(b"fake webm bytes" + b"x" * 2048).decode("ascii")

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

    def test_tiny_recordings_fail_with_clear_guidance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-local-voice-") as tmp:
            transcriber = LocalVoiceTranscriber(tmp)
            self.assertFalse(transcriber.transcribe_bytes(b"")["ok"])
            tiny = transcriber.transcribe_bytes(b"RIFF" * 100, mime_type="audio/webm")
            self.assertFalse(tiny["ok"])
            self.assertIn("empty", tiny["error"])
            self.assertIn("hint", tiny)

    def test_warmup_without_model_never_raises(self) -> None:
        old_model = os.environ.pop("GHOSTCHIMERA_LOCAL_STT_MODEL", None)
        try:
            with tempfile.TemporaryDirectory(prefix="ghost-local-voice-") as tmp:
                transcriber = LocalVoiceTranscriber(tmp)
                first = transcriber.warmup()
                second = transcriber.warmup()
                self.assertFalse(first["ok"])
                self.assertFalse(first["warmed"])
                self.assertEqual(first, second)  # idempotent, no crash
        finally:
            if old_model is not None:
                os.environ["GHOSTCHIMERA_LOCAL_STT_MODEL"] = old_model

    def test_warmup_caches_model_instance(self) -> None:
        import sys as _sys
        from unittest import mock

        class FakeModel:
            instances = 0

            def __init__(self, *args, **kwargs) -> None:
                type(self).instances += 1

        with tempfile.TemporaryDirectory(prefix="ghost-local-voice-") as tmp:
            fake_module = type(_sys)("faster_whisper")
            fake_module.WhisperModel = FakeModel
            _sys.modules["faster_whisper"] = fake_module
            old_model = os.environ.get("GHOSTCHIMERA_LOCAL_STT_MODEL")
            os.environ["GHOSTCHIMERA_LOCAL_STT_MODEL"] = str(tmp)
            try:
                with mock.patch(
                    "ghostchimera.control_plane.local_voice._module_installed",
                    return_value=True,
                ):
                    transcriber = LocalVoiceTranscriber(tmp)
                    self.assertTrue(transcriber.warmup()["ok"])
                    self.assertTrue(transcriber.warmup()["cached"])
                    self.assertEqual(FakeModel.instances, 1)  # loaded once, reused
            finally:
                _sys.modules.pop("faster_whisper", None)
                if old_model is not None:
                    os.environ["GHOSTCHIMERA_LOCAL_STT_MODEL"] = old_model
                else:
                    os.environ.pop("GHOSTCHIMERA_LOCAL_STT_MODEL", None)


class LocalVoiceConsoleRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_command = os.environ.pop("GHOSTCHIMERA_LOCAL_STT_COMMAND", None)

    def tearDown(self) -> None:
        os.environ.pop("GHOSTCHIMERA_LOCAL_STT_COMMAND", None)
        if self._old_command is not None:
            os.environ["GHOSTCHIMERA_LOCAL_STT_COMMAND"] = self._old_command

    def test_console_routes_local_voice_turn_through_conversation_runtime(self) -> None:
        """Route local speech transcription through the conversation readiness flow."""
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
                            "audio_base64": base64.b64encode(b"fake audio" + b"x" * 2048).decode("ascii"),
                            "mime_type": "audio/webm",
                        }
                    ),
                    "query": {},
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["local_voice"]["provider"], "custom-command")
            self.assertFalse(result["local_voice"]["raw_audio_stored"])
            self.assertIn("autonomous-engineer", result["reply"])
            self.assertIn("Warnings:", result["reply"])


class FakeEdgeCommunicate:
    def __init__(self, text, voice, rate="+0%", pitch="+0Hz"):
        self.text = text
        self.voice = voice
        self.rate = rate
        self.pitch = pitch

    async def save(self, path):
        from pathlib import Path

        Path(path).write_bytes(b"ID3fake-mp3-bytes")


class FakeEdgeTts:
    last_voice = ""
    last_pitch = "+0Hz"

    @staticmethod
    async def list_voices():
        return [
            {"ShortName": "en-US-AvaNeural", "FriendlyName": "Ava", "Locale": "en-US", "Gender": "Female"},
            {"ShortName": "de-DE-KatjaNeural", "FriendlyName": "Katja", "Locale": "de-DE", "Gender": "Female"},
        ]

    def Communicate(self, text, voice, rate="+0%", pitch="+0Hz"):
        FakeEdgeTts.last_voice = voice
        FakeEdgeTts.last_pitch = pitch
        return FakeEdgeCommunicate(text, voice, rate, pitch)


class _FakeEdgeModule:
    """Install/remove a fake edge_tts module (with a valid __spec__)."""

    def __init__(self, test_case: unittest.TestCase) -> None:
        import importlib.machinery
        import sys
        import types

        self._real_edge = sys.modules.get("edge_tts")
        fake = types.ModuleType("edge_tts")
        fake.__spec__ = importlib.machinery.ModuleSpec("edge_tts", loader=None)
        fake.Communicate = FakeEdgeTts().Communicate
        fake.list_voices = FakeEdgeTts.list_voices
        sys.modules["edge_tts"] = fake
        test_case.addCleanup(self._restore)

    def _restore(self) -> None:
        import sys

        if self._real_edge is not None:
            sys.modules["edge_tts"] = self._real_edge
        else:
            sys.modules.pop("edge_tts", None)


class EdgeSpeechProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeEdgeModule(self)

    def tearDown(self) -> None:
        pass

    def test_available_with_package_present(self) -> None:
        from ghostchimera.model_layer.media_providers import EdgeSpeechProvider, get_media_provider

        provider = EdgeSpeechProvider()
        self.assertTrue(provider.available)
        self.assertEqual(provider.validate_config(), [])
        registered = get_media_provider("speech", "edge_speech")
        self.assertIsNotNone(registered)

    def test_synthesize_returns_mp3(self) -> None:
        from ghostchimera.model_layer.media_providers import EdgeSpeechProvider

        result = EdgeSpeechProvider().synthesize("Hello Ghost.", voice="en-US-AvaNeural", speed=1.2)
        self.assertTrue(result.ok)
        self.assertEqual(result.mime_type, "audio/mpeg")
        self.assertTrue(result.audio_data.startswith(b"ID3"))
        self.assertEqual(FakeEdgeTts.last_voice, "en-US-AvaNeural")

    def test_pitch_passthrough_and_validation(self) -> None:
        from ghostchimera.model_layer.media_providers import EdgeSpeechProvider, _edge_pitch

        self.assertEqual(_edge_pitch("+10Hz"), "+10Hz")
        self.assertEqual(_edge_pitch("-5Hz"), "-5Hz")
        self.assertEqual(_edge_pitch("loud"), "+0Hz")
        EdgeSpeechProvider().synthesize("Hi.", pitch="-8Hz")
        self.assertEqual(FakeEdgeTts.last_pitch, "-8Hz")

    def test_synthesize_rejects_empty_text(self) -> None:
        from ghostchimera.model_layer.media_providers import EdgeSpeechProvider

        with self.assertRaises(RuntimeError):
            EdgeSpeechProvider().synthesize("   ")

    def test_list_voices_filters_locale(self) -> None:
        from ghostchimera.model_layer.media_providers import EdgeSpeechProvider

        voices = EdgeSpeechProvider.list_voices()
        self.assertEqual([v["id"] for v in voices], ["en-US-AvaNeural"])
        all_voices = EdgeSpeechProvider.list_voices(locale_prefix="")
        self.assertEqual(len(all_voices), 2)


class EdgeTtsConsoleRouteTests(unittest.TestCase):
    def _server(self, tmp):
        server = GatewayServer()
        register_console_routes(server, state_dir=tmp)
        return server

    def test_tts_routes_registered(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-tts-routes-") as tmp:
            server = self._server(tmp)
            self.assertIsNotNone(server.routes.find("GET", "/api/console/voice/tts/voices"))
            self.assertIsNotNone(server.routes.find("POST", "/api/console/voice/tts/speak"))

    def test_speak_validation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-tts-routes-") as tmp:
            server = self._server(tmp)
            route = server.routes.find("POST", "/api/console/voice/tts/speak")
            empty = route.handler({"method": "POST", "path": "/x", "headers": {}, "body": json.dumps({}), "query": {}})
            self.assertFalse(empty["ok"])
            long = route.handler(
                {"method": "POST", "path": "/x", "headers": {}, "body": json.dumps({"text": "x" * 2001}), "query": {}}
            )
            self.assertFalse(long["ok"])

    def test_speak_success_with_mock(self) -> None:
        _FakeEdgeModule(self)
        with tempfile.TemporaryDirectory(prefix="ghost-tts-routes-") as tmp:
            server = self._server(tmp)
            route = server.routes.find("POST", "/api/console/voice/tts/speak")
            payload = route.handler(
                {
                    "method": "POST",
                    "path": "/x",
                    "headers": {},
                    "body": json.dumps({"text": "Hello Ghost.", "voice": "en-US-AvaNeural"}),
                    "query": {},
                }
            )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mime_type"], "audio/mpeg")
        self.assertTrue(base64.b64decode(payload["audio_base64"]).startswith(b"ID3"))

    def test_speak_serves_cache_on_repeat(self) -> None:
        _FakeEdgeModule(self)
        with tempfile.TemporaryDirectory(prefix="ghost-tts-routes-") as tmp:
            server = self._server(tmp)
            route = server.routes.find("POST", "/api/console/voice/tts/speak")
            body = {"method": "POST", "path": "/x", "headers": {}, "query": {}}
            first = route.handler({**body, "body": json.dumps({"text": "Cached hello."})})
            second = route.handler({**body, "body": json.dumps({"text": "Cached hello."})})
        self.assertTrue(first["ok"])
        self.assertFalse(first["cached"])
        self.assertTrue(second["ok"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["audio_base64"], first["audio_base64"])


class FakeWhisperSegment:
    def __init__(self, text="", no_speech_prob=0.0, start=0.0, end=1.0):
        self.text = text
        self.no_speech_prob = no_speech_prob
        self.start = start
        self.end = end


class FakeWhisperModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, path, beam_size=1):
        return self._segments, {}


class FasterWhisperNoSpeechTests(unittest.TestCase):
    def _transcriber(self, segments):
        from ghostchimera.control_plane.local_voice import LocalVoiceTranscriber

        transcriber = LocalVoiceTranscriber.__new__(LocalVoiceTranscriber)
        import threading
        from pathlib import Path

        transcriber.state_dir = Path(".")
        transcriber._model_lock = threading.Lock()
        transcriber._whisper_model = FakeWhisperModel(segments)
        transcriber._whisper_key = "test"
        transcriber.warmup = lambda: {"ok": True, "warmed": True, "cached": True}
        return transcriber

    def test_transcript_returned_when_speech_present(self) -> None:
        transcriber = self._transcriber([FakeWhisperSegment("hello ghost", 0.05, 0.0, 1.2)])
        self.assertEqual(transcriber._transcribe_faster_whisper(__file__), "hello ghost")

    def test_silence_reports_no_speech_detected(self) -> None:
        transcriber = self._transcriber([FakeWhisperSegment("", 0.95, 0.0, 1.0), FakeWhisperSegment("", 0.9, 1.0, 2.0)])
        with self.assertRaises(RuntimeError) as exc:
            transcriber._transcribe_faster_whisper(__file__)
        self.assertIn("no speech detected", str(exc.exception))

    def test_short_clip_reports_too_short(self) -> None:
        transcriber = self._transcriber([FakeWhisperSegment("", 0.1, 0.0, 0.2)])
        with self.assertRaises(RuntimeError) as exc:
            transcriber._transcribe_faster_whisper(__file__)
        self.assertIn("too short", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
