"""Free router + sensitivity guard. Fake providers only, no network."""

from __future__ import annotations

from datetime import UTC

import pytest

from ghostchimera.model_layer.free_router import FreeRouter
from ghostchimera.model_layer.sensitivity import is_sensitive


class _FakeProvider:
    def __init__(self, name, behavior):
        self._name = name
        self._behavior = behavior
        self.calls = 0

    def chat(self, system, user):
        self.calls += 1
        mode = self._behavior
        if mode == "ok":
            return f"[{self._name}] reply"
        if mode.startswith("http"):
            raise RuntimeError(f"{self._name} API returned HTTP {mode[4:]}")
        raise RuntimeError(f"{self._name} exploded: {mode}")


def _router(tmp_path, monkeypatch, behaviors, **kw):
    instances: dict[str, _FakeProvider] = {}

    def fake_get_provider(name, profile=None):
        inst = _FakeProvider(name, behaviors.get(name, "ok"))
        instances[name] = inst
        return inst

    import ghostchimera.model_layer.providers as providers_mod

    monkeypatch.setattr(providers_mod, "get_provider", fake_get_provider)
    monkeypatch.setattr("time.sleep", lambda s: None)
    router = FreeRouter(state_path=tmp_path / "free_usage.json", **kw)
    return router, instances


def _keys(monkeypatch, **env):
    for key in ("GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "CF_API_TOKEN", "CF_ACCOUNT_ID"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


# -- sensitivity ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("my api_key: sk-live-abc123", True),
        ("password: hunter2", True),
        ("-----BEGIN RSA PRIVATE KEY-----", True),
        ("ssn 123-45-6789 here", True),
        ("your code is 482916", True),
        ("reset here: https://x.com/reset?token=abc", True),
        ("reach me at jane.doe@example.com tomorrow", True),
        ("call +1 (555) 123-4567 after noon", True),
        ("my diagnosis was updated yesterday", True),
        ("confidential: do not forward this memo", True),
        ("summarize yesterday's standup notes", False),
        ("write a haiku about submarines", False),
        ("", False),
    ],
)
def test_sensitivity_flags(text, expected) -> None:
    assert is_sensitive(text) is expected


def test_sensitivity_multiple_inputs() -> None:
    assert is_sensitive("hello", "my token: abc") is True
    assert is_sensitive("hello", "world") is False


# -- routing ------------------------------------------------------------------------------
def test_first_working_tier_wins(tmp_path, monkeypatch) -> None:
    _keys(monkeypatch, GOOGLE_API_KEY="g", GROQ_API_KEY="q")
    router, _ = _router(tmp_path, monkeypatch, {})
    out = router.chat("sys", "hello")
    assert out["ok"] is True and out["tier"] == "gemini-flash-lite"
    assert router.used_today("gemini-flash-lite") == 1


def test_failover_on_429(tmp_path, monkeypatch) -> None:
    _keys(monkeypatch, GOOGLE_API_KEY="g", GROQ_API_KEY="q")
    router, instances = _router(tmp_path, monkeypatch, {"gemini-openai": "http429", "groq": "ok"})
    out = router.chat("sys", "hello", tiers=["gemini-flash-lite", "groq-oss-20b"])
    assert out["tier"] == "groq-oss-20b"
    assert "[groq] reply" in out["text"]


def test_all_down_reports_diagnostics_without_secrets(tmp_path, monkeypatch) -> None:
    _keys(monkeypatch, GOOGLE_API_KEY="g")
    router, _ = _router(tmp_path, monkeypatch, {"gemini-openai": "http500"})
    with pytest.raises(RuntimeError, match="All free tiers unavailable") as excinfo:
        router.chat("sys", "hello", tiers=["gemini-flash-lite"])
    assert "g-" not in str(excinfo.value)


def test_missing_keys_are_skipped_with_reason(tmp_path, monkeypatch) -> None:
    _keys(monkeypatch)  # nothing set: only keyless pollinations remains
    router, _ = _router(tmp_path, monkeypatch, {"pollinations": "ok"})
    out = router.chat("sys", "hello")
    assert out["tier"] == "pollinations"


def test_quota_cap_skips_before_calling(tmp_path, monkeypatch) -> None:
    _keys(monkeypatch, GOOGLE_API_KEY="g", GROQ_API_KEY="q")
    router, instances = _router(tmp_path, monkeypatch, {"groq": "ok"})
    from datetime import datetime

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    router._usage = {today: {"groq-oss-20b": 1000, "groq-qwen-27b": 1000}}
    router._save()
    with pytest.raises(RuntimeError, match="daily quota reached"):
        router.chat("sys", "hello", tiers=["groq-oss-20b"])


def test_sensitive_content_skips_training_tiers(tmp_path, monkeypatch) -> None:
    _keys(monkeypatch, GOOGLE_API_KEY="g", GROQ_API_KEY="q", OPENROUTER_API_KEY="o")
    router, _ = _router(tmp_path, monkeypatch, {"groq": "ok"})
    out = router.chat("sys", "my password: hunter2")
    assert out["sensitive_routed"] is True
    assert out["tier"] in ("groq-oss-20b", "groq-qwen-27b", "cloudflare")


def test_sensitive_with_only_logging_tiers_fails_closed(tmp_path, monkeypatch) -> None:
    _keys(monkeypatch, GOOGLE_API_KEY="g")
    router, _ = _router(tmp_path, monkeypatch, {})
    with pytest.raises(RuntimeError, match="All free tiers unavailable"):
        router.chat("sys", "my password: hunter2", tiers=["gemini-flash-lite"])


def test_usage_persists_across_instances(tmp_path, monkeypatch) -> None:
    _keys(monkeypatch, GOOGLE_API_KEY="g")
    router, _ = _router(tmp_path, monkeypatch, {"gemini-openai": "ok"})
    router.chat("sys", "hi")
    router2 = FreeRouter(state_path=tmp_path / "free_usage.json")
    assert router2.used_today("gemini-flash-lite") == 1
    gauges = router2.quota_status()
    lite = next(g for g in gauges if g["tier"] == "gemini-flash-lite")
    assert lite["used_today"] == 1 and lite["requests_per_day"] == 1500
    assert lite["trains_on_data"] is True


def test_quota_file_corruption_recovers(tmp_path, monkeypatch) -> None:
    (tmp_path / "free_usage.json").write_text("not json{{", encoding="utf-8")
    router = FreeRouter(state_path=tmp_path / "free_usage.json")
    assert router.used_today("gemini-flash-lite") == 0


def test_catalog_has_free_entries() -> None:
    from ghostchimera.model_layer.model_catalog import get_catalog_entry

    for provider, model in [
        ("gemini-openai", "gemini-2.5-flash-lite"),
        ("groq", "openai/gpt-oss-20b"),
        ("openrouter", "openrouter/free"),
        ("cloudflare", "@cf/meta/llama-3.1-8b-instruct"),
        ("pollinations", "openai"),
    ]:
        entry = get_catalog_entry(provider, model)
        assert entry is not None, (provider, model)
        assert entry.estimate_cost_usd(1000, 500) == 0.0


def test_new_providers_registered() -> None:
    from ghostchimera.model_layer.providers import get_provider

    for name in ("gemini-openai", "pollinations", "cloudflare"):
        assert get_provider(name) is not None


def test_free_provider_resolves_and_maps_models() -> None:
    from ghostchimera.model_layer.free_router import FreeProvider

    auto = FreeProvider()
    assert auto._tier_filter() is None
    assert auto.validate_config() == []
    lite = FreeProvider()
    lite.model = "gemini-2.5-flash-lite"
    assert lite._tier_filter() == ["gemini-flash-lite"]
    bogus = FreeProvider()
    bogus.model = "does-not-exist-xyz"
    assert bogus._tier_filter() == []
    assert bogus.validate_config() != []


def test_free_provider_chats_through_router(tmp_path, monkeypatch) -> None:
    _keys(monkeypatch, GROQ_API_KEY="q")
    from ghostchimera.model_layer.free_router import FreeProvider

    router, _ = _router(tmp_path, monkeypatch, {"groq": "ok"})
    provider = FreeProvider()
    provider._router = router
    provider.model = "openai/gpt-oss-20b"
    assert "reply" in provider.chat("sys", "hi")


def test_pollinations_refuses_sensitive_directly() -> None:
    from ghostchimera.model_layer.openai_compatible_providers import PollinationsProvider

    provider = PollinationsProvider()
    with pytest.raises(RuntimeError, match="refuses sensitive"):
        provider.chat("sys", "my password: hunter2")


def test_quota_reservations_hold_under_threads(tmp_path, monkeypatch) -> None:
    import threading

    _keys(monkeypatch, GROQ_API_KEY="q")
    router, _ = _router(tmp_path, monkeypatch, {"groq": "ok"})
    # Shrink the pool so contention is guaranteed: 3 slots, 10 racers.
    router.tiers = (
        {
            "tier": "tiny",
            "provider": "groq",
            "model": "m",
            "key_env": "GROQ_API_KEY",
            "trains_on_data": False,
            "requests_per_day": 3,
            "note": "",
        },
    )
    results: list = []

    def attempt():
        try:
            router.chat("sys", "hi", tiers=["tiny"])
            results.append("ok")
        except RuntimeError:
            results.append("denied")

    threads = [threading.Thread(target=attempt) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("ok") == 3
    assert router.used_today("tiny") == 3
