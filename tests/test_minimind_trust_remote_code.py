"""trust_remote_code is opt-in for the MiniMind Transformers runtime."""

from __future__ import annotations

import sys
import types

import pytest

from ghostchimera.model_layer import minimind_runtime as mr


class _Model:
    def eval(self):
        return self

    def to(self, device):
        return self


@pytest.fixture
def fake_hf(monkeypatch: pytest.MonkeyPatch):
    """Stub torch/transformers and record the trust_remote_code they receive."""
    calls: list[tuple[str, bool]] = []
    state = {"needs_custom_code": False}

    def loader(kind):
        def from_pretrained(path, trust_remote_code=False):
            calls.append((kind, trust_remote_code))
            if state["needs_custom_code"] and not trust_remote_code:
                raise ValueError("requires you to execute the configuration file; set trust_remote_code=True")
            return _Model()

        return types.SimpleNamespace(from_pretrained=from_pretrained)

    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    transformers = types.ModuleType("transformers")
    transformers.AutoTokenizer = loader("tokenizer")
    transformers.AutoModelForCausalLM = loader("model")
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.delenv(mr.TRUST_REMOTE_CODE_ENV_VAR, raising=False)
    return calls, state


def test_default_does_not_trust_remote_code(fake_hf, tmp_path) -> None:
    calls, _ = fake_hf
    runtime = mr.MiniMindTransformersRuntime(tmp_path)
    assert runtime.trust_remote_code is False
    assert calls == [("tokenizer", False), ("model", False)]


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_env_opt_in(fake_hf, tmp_path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    calls, _ = fake_hf
    monkeypatch.setenv(mr.TRUST_REMOTE_CODE_ENV_VAR, value)
    mr.MiniMindTransformersRuntime(tmp_path)
    assert calls == [("tokenizer", True), ("model", True)]


def test_explicit_argument_wins_over_env(fake_hf, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls, _ = fake_hf
    monkeypatch.setenv(mr.TRUST_REMOTE_CODE_ENV_VAR, "1")
    mr.MiniMindTransformersRuntime(tmp_path, trust_remote_code=False)
    assert calls == [("tokenizer", False), ("model", False)]


@pytest.mark.parametrize("value", ["", "0", "false", "maybe"])
def test_other_env_values_stay_off(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(mr.TRUST_REMOTE_CODE_ENV_VAR, value)
    assert mr.minimind_trust_remote_code() is False


def test_model_needing_custom_code_gets_an_actionable_error(fake_hf, tmp_path) -> None:
    _, state = fake_hf
    state["needs_custom_code"] = True
    with pytest.raises(RuntimeError, match=mr.TRUST_REMOTE_CODE_ENV_VAR):
        mr.MiniMindTransformersRuntime(tmp_path)
