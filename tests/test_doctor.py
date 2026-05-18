from ghostchimera.control_plane.doctor import _provider_status


def test_provider_status_prefers_env_vultr_configuration(monkeypatch):
    monkeypatch.setenv("GHOSTCHIMERA_MODEL_PROVIDER", "vultr")
    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "vk_test_12345")
    monkeypatch.setenv("VULTR_INFERENCE_MODEL", "llama-3.1-70b")
    monkeypatch.setenv("VULTR_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1/chat/completions")

    label, ok, hint = _provider_status({})

    assert label == "Provider: vultr (env)"
    assert ok is True
    assert hint == ""


def test_provider_status_reports_missing_env_provider_config(monkeypatch):
    monkeypatch.setenv("GHOSTCHIMERA_MODEL_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

    label, ok, hint = _provider_status({})

    assert label == "Provider: openai (env)"
    assert ok is False
    assert "OPENAI_API_KEY is not set" in hint
