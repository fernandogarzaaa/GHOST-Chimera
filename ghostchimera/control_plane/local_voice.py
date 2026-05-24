"""Local speech-to-text fallback for Ghost Console voice input.

Browser speech recognition can fail for reasons outside Ghost Chimera's
control, especially the Web Speech ``network`` error. This module provides a
local-machine fallback contract that accepts browser-recorded audio, tries
installed local STT providers, and returns a redacted transcript without
persisting raw audio.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LocalVoiceProviderStatus:
    id: str
    label: str
    installed: bool
    ready: bool
    privacy: str = "local/private"
    latency: str = "medium"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "installed": self.installed,
            "ready": self.ready,
            "privacy": self.privacy,
            "latency": self.latency,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LocalVoiceStatus:
    ok: bool
    ready: bool
    providers: list[LocalVoiceProviderStatus] = field(default_factory=list)
    recommended_provider: str = ""
    raw_audio_stored: bool = False
    guidance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "ready": self.ready,
            "providers": [provider.to_dict() for provider in self.providers],
            "recommended_provider": self.recommended_provider,
            "raw_audio_stored": self.raw_audio_stored,
            "guidance": list(self.guidance),
        }


def _module_installed(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.exists() else None


def _audio_suffix(mime_type: str, filename: str = "") -> str:
    lowered = f"{mime_type} {filename}".lower()
    if "wav" in lowered:
        return ".wav"
    if "ogg" in lowered or "opus" in lowered:
        return ".ogg"
    if "mp3" in lowered or "mpeg" in lowered:
        return ".mp3"
    if "mp4" in lowered or "m4a" in lowered:
        return ".m4a"
    return ".webm"


class LocalVoiceTranscriber:
    """Best-effort local STT provider adapter.

    Providers are intentionally optional. Ghost Chimera does not download
    models, install packages, or send audio to network services from this
    fallback. Users can enable a custom local command, or install one of the
    supported local runtimes.
    """

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir).expanduser()

    def status(self) -> dict[str, Any]:
        custom_command = os.environ.get("GHOSTCHIMERA_LOCAL_STT_COMMAND", "").strip()
        faster_model = _env_path("GHOSTCHIMERA_LOCAL_STT_MODEL")
        vosk_model = _env_path("GHOSTCHIMERA_VOSK_MODEL_PATH")
        providers = [
            LocalVoiceProviderStatus(
                id="custom-command",
                label="Custom Local STT Command",
                installed=bool(custom_command),
                ready=bool(custom_command),
                latency="depends",
                reason="Set GHOSTCHIMERA_LOCAL_STT_COMMAND with {audio} to enable." if not custom_command else "",
            ),
            LocalVoiceProviderStatus(
                id="faster-whisper",
                label="faster-whisper Local",
                installed=_module_installed("faster_whisper"),
                ready=_module_installed("faster_whisper") and faster_model is not None,
                latency="medium",
                reason=(
                    "Install faster-whisper and set GHOSTCHIMERA_LOCAL_STT_MODEL to a local model path."
                    if not (_module_installed("faster_whisper") and faster_model is not None)
                    else ""
                ),
            ),
            LocalVoiceProviderStatus(
                id="vosk",
                label="Vosk Local",
                installed=_module_installed("vosk"),
                ready=_module_installed("vosk") and vosk_model is not None,
                latency="low",
                reason=(
                    "Install vosk and set GHOSTCHIMERA_VOSK_MODEL_PATH to a local Vosk model folder."
                    if not (_module_installed("vosk") and vosk_model is not None)
                    else ""
                ),
            ),
            LocalVoiceProviderStatus(
                id="sphinx",
                label="PocketSphinx Local",
                installed=_module_installed("speech_recognition") and _module_installed("pocketsphinx"),
                ready=_module_installed("speech_recognition") and _module_installed("pocketsphinx"),
                latency="medium",
                reason="Install SpeechRecognition and pocketsphinx for offline WAV transcription."
                if not (_module_installed("speech_recognition") and _module_installed("pocketsphinx"))
                else "",
            ),
        ]
        ready = [provider for provider in providers if provider.ready]
        return LocalVoiceStatus(
            ok=True,
            ready=bool(ready),
            providers=providers,
            recommended_provider=ready[0].id if ready else "",
            guidance=[
                "Browser Web Speech is tried first.",
                "If it fails, Ghost can record a short local audio clip and run an installed local STT provider.",
                "Raw audio is kept in a temporary file only for transcription and is deleted immediately after use.",
            ],
        ).to_dict()

    def transcribe_base64(
        self,
        audio_base64: str,
        *,
        mime_type: str = "",
        filename: str = "",
        provider: str = "auto",
    ) -> dict[str, Any]:
        if not audio_base64.strip():
            return {"ok": False, "error": "audio_base64 is required", "transcript": ""}
        try:
            audio = base64.b64decode(audio_base64, validate=True)
        except Exception:
            return {"ok": False, "error": "audio_base64 is not valid base64", "transcript": ""}
        return self.transcribe_bytes(audio, mime_type=mime_type, filename=filename, provider=provider)

    def transcribe_bytes(
        self,
        audio: bytes,
        *,
        mime_type: str = "",
        filename: str = "",
        provider: str = "auto",
    ) -> dict[str, Any]:
        if not audio:
            return {"ok": False, "error": "audio payload is empty", "transcript": ""}
        suffix = _audio_suffix(mime_type, filename)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="ghost-local-voice-", dir=str(self.state_dir)))
        audio_path = tmp_dir / f"input{suffix}"
        try:
            audio_path.write_bytes(audio)
            return self.transcribe_file(audio_path, provider=provider)
        finally:
            try:
                audio_path.unlink(missing_ok=True)
                tmp_dir.rmdir()
            except OSError:
                pass

    def transcribe_file(self, audio_path: str | Path, *, provider: str = "auto") -> dict[str, Any]:
        path = Path(audio_path).expanduser()
        if not path.exists() or not path.is_file():
            return {"ok": False, "error": "audio file does not exist", "transcript": ""}

        providers = self._provider_order(provider)
        errors: list[str] = []
        for provider_id in providers:
            try:
                if provider_id == "custom-command":
                    transcript = self._transcribe_custom_command(path)
                elif provider_id == "faster-whisper":
                    transcript = self._transcribe_faster_whisper(path)
                elif provider_id == "vosk":
                    transcript = self._transcribe_vosk(path)
                elif provider_id == "sphinx":
                    transcript = self._transcribe_sphinx(path)
                else:
                    continue
                transcript = " ".join(str(transcript or "").split())
                if transcript:
                    return {
                        "ok": True,
                        "provider": provider_id,
                        "transcript": transcript,
                        "raw_audio_stored": False,
                        "timestamp": time.time(),
                    }
                errors.append(f"{provider_id}: empty transcript")
            except Exception as exc:
                errors.append(f"{provider_id}: {exc}")

        return {
            "ok": False,
            "error": "No local speech-to-text provider could transcribe the audio.",
            "provider_errors": errors,
            "status": self.status(),
            "transcript": "",
            "raw_audio_stored": False,
        }

    def _provider_order(self, requested: str) -> list[str]:
        provider = str(requested or "auto").strip()
        known = ["custom-command", "faster-whisper", "vosk", "sphinx"]
        if provider and provider != "auto":
            return [provider]
        return known

    def _transcribe_custom_command(self, audio_path: Path) -> str:
        command = os.environ.get("GHOSTCHIMERA_LOCAL_STT_COMMAND", "").strip()
        if not command:
            raise RuntimeError("GHOSTCHIMERA_LOCAL_STT_COMMAND is not configured")
        rendered = command.replace("{audio}", str(audio_path))
        completed = subprocess.run(
            rendered,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=float(os.environ.get("GHOSTCHIMERA_LOCAL_STT_TIMEOUT", "45")),
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            raise RuntimeError(stderr or f"local STT command exited with {completed.returncode}")
        return (completed.stdout or "").strip()

    def _transcribe_faster_whisper(self, audio_path: Path) -> str:
        model_path = _env_path("GHOSTCHIMERA_LOCAL_STT_MODEL")
        if model_path is None:
            raise RuntimeError("GHOSTCHIMERA_LOCAL_STT_MODEL must point to a local faster-whisper model")
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(str(model_path), device=os.environ.get("GHOSTCHIMERA_LOCAL_STT_DEVICE", "cpu"))
        segments, _info = model.transcribe(str(audio_path), beam_size=1)
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip())

    def _transcribe_vosk(self, audio_path: Path) -> str:
        model_path = _env_path("GHOSTCHIMERA_VOSK_MODEL_PATH")
        if model_path is None:
            raise RuntimeError("GHOSTCHIMERA_VOSK_MODEL_PATH must point to a local Vosk model")
        import vosk  # type: ignore

        with wave.open(str(audio_path), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise RuntimeError("Vosk fallback requires mono 16-bit PCM WAV audio")
            recognizer = vosk.KaldiRecognizer(vosk.Model(str(model_path)), wav.getframerate())
            chunks: list[str] = []
            while True:
                data = wav.readframes(4000)
                if not data:
                    break
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    if result.get("text"):
                        chunks.append(str(result["text"]))
            final = json.loads(recognizer.FinalResult())
            if final.get("text"):
                chunks.append(str(final["text"]))
        return " ".join(chunks)

    def _transcribe_sphinx(self, audio_path: Path) -> str:
        import speech_recognition as sr  # type: ignore

        recognizer = sr.Recognizer()
        with sr.AudioFile(str(audio_path)) as source:
            audio = recognizer.record(source)
        return str(recognizer.recognize_sphinx(audio))


__all__ = ["LocalVoiceTranscriber"]
