"""Tests for llama.cpp runtime tuning knobs (KV cache, speculative, budgets)."""

from __future__ import annotations

import pytest

from ghostchimera.model_layer.llamacpp_runtime import LlamaCppRuntime


def _runtime(**kwargs) -> LlamaCppRuntime:
    return LlamaCppRuntime(model_path="/tmp/model.gguf", profile_name="tiny", **kwargs)


def test_default_kwargs_unchanged():
    rt = _runtime()
    kwargs = rt.build_load_kwargs()
    assert kwargs["model_path"].endswith("model.gguf")
    assert kwargs["n_gpu_layers"] == 0
    assert kwargs["verbose"] is False
    # No tuning knobs leak in by default.
    assert "type_k" not in kwargs
    assert "type_v" not in kwargs


def test_kv_cache_quantization_sets_ggml_types():
    rt = _runtime(kv_cache_type="q8_0")
    kwargs = rt.build_load_kwargs()
    assert kwargs["type_k"] == 8
    assert kwargs["type_v"] == 8


def test_invalid_kv_cache_type_rejected():
    with pytest.raises(ValueError):
        _runtime(kv_cache_type="q2_nonsense")


def test_n_ctx_override():
    rt = _runtime(n_ctx_override=2048)
    assert rt.build_load_kwargs()["n_ctx"] == 2048


def test_speculative_disabled_by_default():
    rt = _runtime()
    assert rt.speculative_lookahead == 0
    assert rt._make_draft_model() is None


def test_speculative_lookahead_configurable():
    rt = _runtime(speculative_lookahead=10)
    assert rt.speculative_lookahead == 10


def test_kv_cache_type_normalized_case_insensitive():
    rt = _runtime(kv_cache_type="Q8_0")
    assert rt.kv_cache_type == "q8_0"


def test_reasoning_profile_applies_tuning_defaults():
    rt = LlamaCppRuntime(model_path="/tmp/model.gguf", profile_name="reasoning")
    # Profile recommendations flow through when not explicitly overridden.
    assert rt.kv_cache_type == "q8_0"
    assert rt.default_temperature == 0.6
    assert rt.build_load_kwargs()["type_k"] == 8


def test_explicit_args_override_profile_defaults():
    rt = LlamaCppRuntime(
        model_path="/tmp/model.gguf",
        profile_name="reasoning",
        kv_cache_type="f16",
        default_temperature=0.0,
    )
    assert rt.kv_cache_type == "f16"
    assert rt.default_temperature == 0.0
