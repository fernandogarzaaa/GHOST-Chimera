"""Setup wizard connections section: staged IDs, gh reuse, port pin, gate."""

from __future__ import annotations

import builtins

import pytest

from ghostchimera.connectors.auth_engine import CustomAuthEngine
from ghostchimera.control_plane import setup_wizard


@pytest.fixture()
def _inputs(monkeypatch):
    answers: list = []

    def feed(*values):
        answers.extend(values)
        return None

    def fake_input(prompt=""):
        assert answers, f"no scripted answer for prompt: {prompt!r}"
        return answers.pop(0)

    monkeypatch.setattr(builtins, "input", fake_input)
    return feed


def test_connections_decline_all(tmp_path, monkeypatch, _inputs) -> None:
    monkeypatch.setattr(setup_wizard, "ensure_state_dir", lambda: tmp_path)
    monkeypatch.setattr("ghostchimera.connectors.gh_cli.gh_status", lambda: {"available": False, "reason": "no gh"})
    # github? google? slack? pin? gate?
    _inputs("n", "n", "n", "n", "n")
    config: dict = {}
    setup_wizard._setup_connections(config)
    assert config["provider_oauth"] == {}
    assert config["auth"]["require_write_approval"] is False
    assert "http_port" not in config["console"]


def test_connections_full_flow(tmp_path, monkeypatch, _inputs) -> None:
    monkeypatch.setattr(setup_wizard, "ensure_state_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "ghostchimera.connectors.gh_cli.gh_status",
        lambda: {"available": True, "user": "shim", "scopes": ["repo"], "reason": ""},
    )
    imported: list = []
    monkeypatch.setattr(
        CustomAuthEngine,
        "import_gh_cli",
        lambda self, entity: imported.append(entity) or {"ok": True, "gh_user": "shim"},
    )
    # import gh? y | github paste? y | id | google? n | slack? n | pin? y | port | gate? y
    _inputs("y", "y", "Iv1.testid", "n", "n", "y", "8766", "y")
    config: dict = {}
    setup_wizard._setup_connections(config)
    assert imported == ["console-user"]
    assert config["provider_oauth"]["github"]["client_id"] == "Iv1.testid"
    assert "google" not in config["provider_oauth"]
    assert config["console"]["http_port"] == 8766
    assert config["auth"]["require_write_approval"] is True


def test_connections_bad_port_kept_unpinned(tmp_path, monkeypatch, _inputs) -> None:
    monkeypatch.setattr(setup_wizard, "ensure_state_dir", lambda: tmp_path)
    monkeypatch.setattr("ghostchimera.connectors.gh_cli.gh_status", lambda: {"available": False, "reason": "no gh"})
    _inputs("n", "n", "n", "y", "notaport", "n")
    config: dict = {}
    setup_wizard._setup_connections(config)
    assert "http_port" not in config["console"]
