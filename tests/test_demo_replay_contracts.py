"""Contracts for `ghost demo` (written from testteeth survivors in demo/replay.py).

The rendered transcript is what a judge sees first, so its lines are pinned;
the offline guard must refuse every non-loopback connect path; recording must
fail loudly and write nothing when a live call fails.
"""

from __future__ import annotations

import importlib
import io
import json
import socket
from pathlib import Path
from typing import Any

import pytest

rp = importlib.import_module("ghostchimera.demo.replay")  # the package re-exports a `replay` function


@pytest.fixture()
def session() -> dict[str, Any]:
    return rp.load_session()


# ---------------------------------------------------------------------------
# Session loading and providers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "s.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_session_rejects_bad_files(tmp_path: Path, session: dict) -> None:
    with pytest.raises(ValueError, match="format"):
        rp.load_session(_write(tmp_path, {**session, "format": "other"}))
    with pytest.raises(ValueError, match="no events"):
        rp.load_session(_write(tmp_path, {**session, "events": []}))
    with pytest.raises(ValueError, match="no events"):
        rp.load_session(_write(tmp_path, {**session, "events": "x"}))
    assert rp.load_session(_write(tmp_path, session))["events"] == session["events"]


def test_replay_provider_counts_and_missing_predict(session: dict) -> None:
    provider = rp.ReplayProvider(session, model="m", role="predict")
    assert provider.calls == 0 and provider.available is True and provider.model == "m"
    assert provider.chat("s", "u") == str(session["predict"])
    provider.chat("s", "u")
    assert provider.calls == 2
    empty = rp.ReplayProvider({**session, "predict": None}, model="m", role="predict")
    with pytest.raises(LookupError, match="PREDICT"):
        empty.chat("s", "u")
    assert empty.calls == 1


def test_recording_provider_keeps_errors_and_reraises() -> None:
    class Boom:
        model = "inner-model"

        def chat(self, system: str, user: str) -> str:
            raise TimeoutError("slow")

    recorder = rp.RecordingProvider(Boom())
    with pytest.raises(TimeoutError):
        recorder.chat("s", "u")
    assert recorder.errors == ["TimeoutError: slow"]
    assert recorder.replies == []
    assert recorder.model == "inner-model"  # attribute passthrough


def test_recording_provider_indexes_first_reply_per_event_type(session: dict) -> None:
    class Echo:
        def __init__(self) -> None:
            self.n = 0

        def chat(self, system: str, user: str) -> str:
            self.n += 1
            return f"r{self.n}"

    first_type = session["events"][0]["event_type"]
    recorder = rp.RecordingProvider(Echo())
    # Build a user message the way the reasoner does, so the event regex matches.
    msg = f"event_type: {first_type}\npayload: {{}}"
    if not rp._EVENT_TYPE_RE.search(msg):
        pytest.skip("event-type marker format changed")
    assert recorder.chat("s", msg) == "r1"
    assert recorder.chat("s", msg) == "r2"
    assert recorder.replies == ["r1", "r2"]
    assert recorder.by_event_type == {first_type.lower(): "r1"}


# ---------------------------------------------------------------------------
# Offline guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("/tmp/sock", True),
        (b"/tmp/sock", True),
        (("127.0.0.1", 80), True),
        (("::1", 80, 0, 0), True),
        (("fe80::1%lo", 80), False),
        (("::1%lo", 80), True),
        ((b"127.0.0.2", 1), True),
        (("LOCALHOST", 1), True),
        (("8.8.8.8", 53), False),
        (("example.com", 443), False),
        ((), False),
        (None, False),
        (["127.0.0.1", 80], False),
    ],
)
def test_is_loopback(address: Any, expected: bool) -> None:
    assert rp._is_loopback(address) is expected


def test_no_network_refuses_every_connect_path_and_restores() -> None:
    before = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection)
    with rp.no_network():
        with pytest.raises(rp.OfflineNetworkError):
            socket.create_connection(("203.0.113.9", 80), timeout=0.1)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(rp.OfflineNetworkError):
                sock.connect(("203.0.113.9", 80))
            with pytest.raises(rp.OfflineNetworkError):
                sock.connect_ex(("203.0.113.9", 80))
        finally:
            sock.close()
        # Loopback connect_ex still reaches the real implementation (refused -> errno, not an exception).
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.settimeout(1)
            assert isinstance(probe.connect_ex(("127.0.0.1", 1)), int)
        finally:
            probe.close()
    assert (socket.socket.connect, socket.socket.connect_ex, socket.create_connection) == before


# ---------------------------------------------------------------------------
# Replay result and rendering
# ---------------------------------------------------------------------------


def test_replay_result_shape(session: dict) -> None:
    result = rp.replay()
    assert result.title == session["title"]
    assert result.provenance == "recorded"
    assert result.models["predict"] == session["models"]["predict"]
    assert [s.event_type for s in result.steps] == [e["event_type"] for e in session["events"]]
    assert {s.source for s in result.steps} == {e.get("source") or "demo" for e in session["events"]}
    assert all(s.understand for s in result.steps)
    assert result.predictions and result.predict_source in {"reasoner", "stealth-loop"}
    assert 0 < result.elapsed_s < 60
    data = result.to_dict()
    assert data["elapsed_s"] == round(result.elapsed_s, 3)
    assert data["steps"][0]["event_type"] == session["events"][0]["event_type"]


def test_replay_defaults_for_sparse_session(tmp_path: Path, session: dict) -> None:
    sparse = {k: v for k, v in session.items() if k not in {"title", "provenance_note", "models", "session_id"}}
    sparse["events"] = [{k: v for k, v in e.items() if k != "source"} for e in session["events"]]
    result = rp.replay(_write(tmp_path, sparse))
    assert result.title == "Ghost Chimera demo"
    assert result.provenance_note == ""
    assert {s.source for s in result.steps} == {"demo"}
    assert result.models["understand"]  # defaults to the Nano model id


def test_render_text_pins_the_transcript(session: dict) -> None:
    result = rp.replay()
    buf = io.StringIO()
    rp.render_text(result, buf)
    lines = buf.getvalue().splitlines()
    assert lines[0] == f"Ghost Chimera demo: {session['title']}"
    assert lines[1].startswith("Replaying a Nemotron session (recorded) offline")
    assert lines[2] == f"  UNDERSTAND: {result.models['understand']}"
    assert lines[3] == f"  PREDICT:    {result.models['predict']}"
    assert lines[4] == ""
    first = result.steps[0]
    assert lines[5] == f"[1] {first.event_type}  (from {first.source})"
    assert lines[6].startswith(f"    UNDERSTAND -> intent={first.understand['intent']}")
    assert lines[7] == f"                  {first.understand['rationale']}"
    assert lines[8] == f"    DECIDE     -> {first.decision}"
    last = result.steps[-1]
    assert f"[{len(result.steps)}] {last.event_type}  (from {last.source})" in lines
    assert any(line.startswith("PREDICT (Nemotron 3 Super, via ") for line in lines)
    top = result.predictions[0]
    assert f"  {float(top['probability']):.0%}  {top['action']}  - {top.get('rationale', '')}" in lines
    assert lines[-2] == f"Note: {result.provenance_note}"
    assert lines[-1].startswith("Run it live: export NEBIUS_API_KEY=")


def test_render_text_without_insight_or_prediction() -> None:
    result = rp.DemoResult(
        title="t",
        provenance="synthetic",
        provenance_note="",
        models={"understand": "u", "predict": "p"},
        steps=[rp.DemoStep("x.y", "src", "drop", None), rp.DemoStep("a.b", "s2", "store", {"intent": "i"})],
        predictions=None,
        predict_source="stealth-loop",
        elapsed_s=0.0,
    )
    buf = io.StringIO()
    rp.render_text(result, buf)
    text = buf.getvalue()
    assert "    UNDERSTAND -> (no cloud insight; local loop only)" in text
    assert "workflow=-  risk=none" in text
    assert "PREDICT (Nemotron 3 Super, inside the Stealth Loop)" in text
    assert "  (no prediction in this session)" in text
    assert "Note:" not in text


def test_run_demo_cli_text_json_and_errors(tmp_path: Path, capsys) -> None:
    buf = io.StringIO()
    assert rp.run_demo_cli(stream=buf) == 0
    assert buf.getvalue().startswith("Ghost Chimera demo:")
    buf = io.StringIO()
    assert rp.run_demo_cli(as_json=True, stream=buf) == 0
    parsed = json.loads(buf.getvalue())
    assert parsed["provenance"] == "recorded"
    assert buf.getvalue().startswith('{\n  "elapsed_s"')  # sorted keys, indent=2
    assert rp.run_demo_cli(session=str(tmp_path / "missing.json")) == 1
    assert "ghost demo:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Recording guards
# ---------------------------------------------------------------------------


def test_check_output_path(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    assert rp._check_output_path(target) == target
    target.write_text("{}")
    assert rp._check_output_path(target) == target  # existing file may be overwritten
    with pytest.raises(OSError, match="is a directory"):
        rp._check_output_path(tmp_path)
    with pytest.raises(OSError, match="does not exist"):
        rp._check_output_path(tmp_path / "nope" / "x.json")


def test_check_output_path_unwritable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rp.os, "access", lambda *_a: False)
    with pytest.raises(OSError, match="not writable"):
        rp._check_output_path(tmp_path / "x.json")


def test_record_requires_key_before_anything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.setattr(rp, "_check_output_path", lambda *_a: pytest.fail("must fail before path checks"))
    with pytest.raises(RuntimeError, match="NEBIUS_API_KEY"):
        rp.record(tmp_path / "x.json")
    monkeypatch.setenv("NEBIUS_API_KEY", "   ")
    with pytest.raises(RuntimeError, match="NEBIUS_API_KEY"):
        rp.record(tmp_path / "x.json")


def test_stderr_progress(capsys) -> None:
    rp._stderr_progress(2, 5, "file.modified", 1.25, {"nemotron": {"intent": "x"}})
    rp._stderr_progress(3, 5, "file.saved", 0.0, {})
    rp._stderr_progress(4, 5, "x", 0.0, None)  # type: ignore[arg-type]
    err = capsys.readouterr().err.splitlines()
    assert err == [
        "  [2/5] UNDERSTAND file.modified  1.2s  ok",
        "  [3/5] UNDERSTAND file.saved  0.0s  no reply",
        "  [4/5] UNDERSTAND x  0.0s  no reply",
    ]
