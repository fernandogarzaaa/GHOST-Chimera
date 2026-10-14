"""`ghost demo` replays a Nemotron session offline: no keys, no network."""

from __future__ import annotations

import json
import os
import socket

import pytest

from ghostchimera.control_plane import cli
from ghostchimera.demo import OfflineNetworkError, ReplayProvider, load_session, no_network, replay


@pytest.fixture
def offline(monkeypatch):
    """Strip every provider key and make any non-loopback connection fail loudly.

    Loopback stays allowed: on Windows ``socket.socketpair()`` (asyncio's
    self-pipe) is emulated with a connect to 127.0.0.1.
    """
    from ghostchimera.demo.replay import _is_loopback

    for key in list(os.environ):
        if key.endswith("_API_KEY") or key.startswith(("NEBIUS_", "TAVILY_", "LANGSMITH_")):
            monkeypatch.delenv(key, raising=False)
    attempts: list[object] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection

    def _guard(real):
        def _blocked(*args, **kwargs):
            address = args[1] if real is not real_create_connection else args[0]
            if _is_loopback(address):
                return real(*args, **kwargs)
            attempts.append(address)
            raise OSError("network disabled by test")

        return _blocked

    monkeypatch.setattr(socket.socket, "connect", _guard(real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", _guard(real_connect_ex))
    monkeypatch.setattr(socket, "create_connection", _guard(real_create_connection))
    return attempts


def _recorded_intent(index: int) -> str:
    return json.loads(load_session()["events"][index]["understand"])["intent"]


def _recorded_first_prediction() -> str:
    return json.loads(load_session()["predict"])[0]["action"]


def test_bundled_session_is_package_data() -> None:
    session = load_session()
    assert session["events"]
    assert session["predict"]
    assert session["models"]["predict"].startswith("nvidia/nemotron-3-super")


def test_bundled_session_is_a_real_recording() -> None:
    session = load_session()
    assert session["provenance"] == "recorded"
    assert "illustrative" not in json.dumps(session).lower()
    assert all(event["understand"] for event in session["events"])


def test_cli_demo_runs_offline_without_keys(offline, capsys) -> None:
    rc = cli._main(["demo"])
    out = capsys.readouterr().out
    assert rc == 0
    assert offline == []  # nothing even tried to open a socket
    assert f"UNDERSTAND -> intent={_recorded_intent(0)}" in out
    assert "PREDICT (Nemotron 3 Super" in out
    assert _recorded_first_prediction() in out
    assert "network disabled" in out


def test_cli_demo_json(offline, capsys) -> None:
    rc = cli._main(["demo", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert len(payload["steps"]) == len(load_session()["events"])
    assert all(step["understand"] for step in payload["steps"])
    assert payload["predictions"][0]["model"] == payload["models"]["predict"]


def test_replay_goes_through_real_reasoner_and_loop() -> None:
    result = replay()
    # The loop attached the parsed Nemotron insight to its own trace.
    assert result.steps[1].understand["provider"] == "nebius"
    assert result.steps[1].understand["intent"] == _recorded_intent(1)
    assert result.predictions and result.predictions[0]["provider"] == "nebius"


def test_no_network_guard_blocks_and_restores() -> None:
    original = socket.socket.connect
    with no_network(), pytest.raises(OfflineNetworkError):
        socket.create_connection(("example.com", 443), timeout=1)
    with no_network(), pytest.raises(OfflineNetworkError):
        socket.create_connection(("93.184.215.14", 443), timeout=1)
    assert socket.socket.connect is original


def test_no_network_guard_allows_loopback() -> None:
    """asyncio's self-pipe on Windows connects to 127.0.0.1; that must work."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        with no_network():
            client = socket.create_connection(listener.getsockname(), timeout=2)
            server, _ = listener.accept()
            client.close()
            server.close()
            a, b = socket.socketpair()
            a.close()
            b.close()
    finally:
        listener.close()


def test_loopback_detection() -> None:
    from ghostchimera.demo.replay import _is_loopback

    assert _is_loopback(("127.0.0.1", 1))
    assert _is_loopback(("::1", 1, 0, 0))
    assert _is_loopback(("localhost", 1))
    assert _is_loopback("/tmp/sock")
    assert not _is_loopback(("example.com", 443))
    assert not _is_loopback(("10.0.0.1", 80))


def test_replay_provider_unknown_event_raises() -> None:
    provider = ReplayProvider(load_session(), model="m", role="understand")
    with pytest.raises(LookupError):
        provider.chat("sys", "event_type: something.else")


def test_bad_session_file_fails_cleanly(tmp_path, capsys) -> None:
    bad = tmp_path / "s.json"
    bad.write_text(json.dumps({"format": "nope"}), encoding="utf-8")
    rc = cli._main(["demo", "--session", str(bad)])
    assert rc == 1
    assert "unsupported demo session format" in capsys.readouterr().err


def test_record_requires_key(offline, tmp_path, capsys) -> None:
    rc = cli._main(["demo", "--record", str(tmp_path / "out.json")])
    assert rc == 1
    assert "NEBIUS_API_KEY" in capsys.readouterr().err


def test_record_then_replay_roundtrip(offline, monkeypatch, tmp_path, capsys) -> None:
    from ghostchimera.stealth import nemotron_reasoning as nr

    session = load_session()
    live_understand = ReplayProvider(session, model=nr.NANO_MODEL, role="understand")
    live_predict = ReplayProvider(session, model=nr.SUPER_MODEL, role="predict")
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test-not-real")
    monkeypatch.setattr(nr.NemotronReasoner, "_default_provider", staticmethod(lambda: live_understand))
    # Mimic the real lookup: an explicitly attached reasoning provider wins.
    monkeypatch.setattr(
        nr.NemotronReasoner,
        "_reasoning_provider_instance",
        lambda self: self._reasoning_provider or live_predict,
    )

    out = tmp_path / "recorded.json"
    assert cli._main(["demo", "--record", str(out)]) == 0
    recorded = json.loads(out.read_text(encoding="utf-8"))
    assert recorded["provenance"] == "recorded"
    assert all(event["understand"] for event in recorded["events"])
    assert recorded["predict"]
    capsys.readouterr()

    assert cli._main(["demo", "--session", str(out)]) == 0
    assert "(recorded)" in capsys.readouterr().out


def test_replay_works_with_windows_style_socketpair(monkeypatch, offline) -> None:
    """Windows emulates socketpair() with a loopback connect (asyncio self-pipe).

    Reproduces the Windows CI failure on any OS: replay must still produce
    UNDERSTAND insights and must not attempt any non-loopback connection.
    """
    fallback = getattr(socket, "_fallback_socketpair", None)
    if fallback is None:
        pytest.skip("this Python has no socket._fallback_socketpair")
    monkeypatch.setattr(socket, "socketpair", fallback)
    result = replay()
    assert all(step.understand for step in result.steps)
    assert result.predictions
    assert offline == []
