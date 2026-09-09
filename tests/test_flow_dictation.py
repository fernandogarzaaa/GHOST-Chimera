"""Flow dictation tests: deterministic formatting, history, pipeline."""

from __future__ import annotations

import json
import urllib.request

from ghostchimera.control_plane.flow_dictation import (
    FlowHistory,
    FlowProfile,
    apply_smart_formatting,
    format_transcript,
    strip_fillers,
    transcribe_and_format,
)


def test_inline_formatting() -> None:
    result = format_transcript("hello comma world period new paragraph next")
    assert "Hello, world." in result.text
    assert "\n\n" in result.text
    assert any(r.startswith("inline:") for r in result.rules_applied)


def test_smart_formatting_email_and_time() -> None:
    text, _ = apply_smart_formatting("mail john at example dot com at 3 p m")
    assert "john@example.com" in text
    assert "3 PM" in text


def test_filler_stripping() -> None:
    text, rules = strip_fillers("um hello uh world you know")
    assert text == "hello world"
    assert rules


def test_verbatim_profile() -> None:
    result = format_transcript("hello um world", "code")
    assert result.text == "hello um world"
    assert result.rules_applied == []


def test_vocabulary_corrections() -> None:
    profile = FlowProfile(name="test", vocabulary={"cap x": "CAPEX", "ghost chimera": "Ghost Chimera"})
    result = format_transcript("the cap x report for ghost chimera", profile)
    assert "CAPEX" in result.text and "Ghost Chimera" in result.text


def test_history_round_trip(tmp_path) -> None:
    history = FlowHistory(tmp_path, limit=3)
    for i in range(5):
        history.record(format_transcript(f"note number {i}"))
    recent = history.recent(10)
    assert len(recent) == 3
    assert recent[-1]["text"].startswith("Note number")


def test_pipeline_with_stub_transcriber(tmp_path) -> None:
    class Stub:
        def transcribe_base64(self, audio_base64, *, mime_type=""):
            assert audio_base64
            return {"ok": True, "provider": "stub",
                    "transcript": "hello um comma world"}

    history = FlowHistory(tmp_path)
    result = transcribe_and_format(Stub(), "QUJD", profile="dictation", history=history)
    assert result["ok"] is True and result["provider"] == "stub"
    assert "Hello," in result["text"] and "um" not in result["text"]
    assert len(history.recent()) == 1


def test_pipeline_propagates_transcriber_failure(tmp_path) -> None:
    class Failing:
        def transcribe_base64(self, audio_base64, *, mime_type=""):
            return {"ok": False, "error": "no provider", "transcript": ""}

    result = transcribe_and_format(Failing(), "QUJD", history=FlowHistory(tmp_path))
    assert result["ok"] is False and result["text"] == ""


def _live_console(tmp_path, port_base: int = 18771):
    from ghostchimera.control_plane.console import run_console

    return run_console(host="127.0.0.1", port=port_base, http_port=port_base + 1,
                       state_dir=str(tmp_path), open_browser=False, block=False)


def _api(method: str, url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data if method == "POST" else None,
                                 headers={"Content-Type": "application/json"},
                                 method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def test_console_flow_routes_contract(tmp_path) -> None:
    """Routes respond with well-formed envelopes even with no STT installed."""
    server = _live_console(tmp_path)
    try:
        base = "http://127.0.0.1:18772"
        status = _api("GET", base + "/api/console/conversation/local-voice/status")
        assert status["ok"] is True and "providers" in status
        flow = _api("POST", base + "/api/console/voice/flow",
                    {"audio_base64": "", "profile": "dictation"})
        assert flow["ok"] is False and "text" in flow  # empty audio, honest error
        history = _api("POST", base + "/api/console/voice/flow/history", {"limit": 5})
        assert history["ok"] is True and history["history"] == []
    finally:
        server.stop()
