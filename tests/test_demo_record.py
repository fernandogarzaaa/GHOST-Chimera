"""`ghost demo --record` fails loudly, checks its path first, records the whole-session PREDICT,
and prints progress (audit2 newcomer P1-2, P1-3, P2-4, P2-5; poweruser F23)."""

from __future__ import annotations

import json

import pytest

from ghostchimera.control_plane import cli
from ghostchimera.demo.replay import ReplayProvider, load_session
from ghostchimera.stealth import nemotron_reasoning as nr


class _CountingPredict:
    """PREDICT stand-in whose reply says how much history it saw."""

    available = True
    model = nr.SUPER_MODEL
    api_key = ""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        # The session's last event is agent.tool_called; the first in-loop
        # PREDICT only ever saw agent.session_started.
        label = "full_history" if "agent.tool_called" in user else "first_event_only"
        return json.dumps([{"action": label, "probability": 0.6, "rationale": "r"}])


class _Down:
    available = True
    model = nr.NANO_MODEL
    api_key = ""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        raise RuntimeError("nebius API returned HTTP 404: model 'nvidia/does-not-exist' not found on nebius")


def _wire(monkeypatch, understand, predict) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test-not-real")
    monkeypatch.setattr(nr.NemotronReasoner, "_default_provider", staticmethod(lambda: understand))
    monkeypatch.setattr(
        nr.NemotronReasoner,
        "_reasoning_provider_instance",
        lambda self: self._reasoning_provider or predict,
    )


def test_record_saves_whole_session_prediction_and_prints_progress(monkeypatch, tmp_path, capsys) -> None:
    session = load_session()
    predict = _CountingPredict()
    _wire(monkeypatch, ReplayProvider(session, model=nr.NANO_MODEL, role="understand"), predict)
    out = tmp_path / "rec.json"
    assert cli._main(["demo", "--record", str(out)]) == 0
    err = capsys.readouterr().err
    recorded = json.loads(out.read_text(encoding="utf-8"))
    n = len(session["events"])
    # The saved PREDICT is the one made over the full history, not the
    # rate-limited first in-loop call (which only saw event 1).
    assert json.loads(recorded["predict"])[0]["action"] == "full_history"
    assert f"[1/{n}]" in err and f"[{n}/{n}]" in err
    assert "PREDICT (whole session)" in err
    assert "UTC" in recorded["provenance_note"]


def test_record_fails_nonzero_and_writes_nothing_when_live_calls_fail(monkeypatch, tmp_path, capsys) -> None:
    _wire(monkeypatch, _Down(), _CountingPredict())
    out = tmp_path / "bad.json"
    rc = cli._main(["demo", "--record", str(out)])
    err = capsys.readouterr().err
    assert rc == 1
    assert not out.exists()
    assert "live UNDERSTAND failed" in err and "404" in err


def test_record_checks_output_directory_before_any_call(monkeypatch, tmp_path, capsys) -> None:
    down = _Down()
    _wire(monkeypatch, down, _CountingPredict())
    rc = cli._main(["demo", "--record", str(tmp_path / "missing" / "x.json")])
    assert rc == 1
    assert down.calls == 0
    assert "does not exist" in capsys.readouterr().err


@pytest.mark.parametrize("target", ["dir"])
def test_record_rejects_directory_target(monkeypatch, tmp_path, capsys, target) -> None:
    down = _Down()
    _wire(monkeypatch, down, _CountingPredict())
    assert cli._main(["demo", "--record", str(tmp_path)]) == 1
    assert down.calls == 0
