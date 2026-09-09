"""Model discovery and compatibility filtering for the Ghost Console."""

from __future__ import annotations

import json
import os
import ssl
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .providers import TEXT_PROVIDERS

FetchJson = Callable[[str, dict[str, str], float], dict[str, Any] | list[Any]]

CACHE_FILE_NAME = "model_discovery_cache.json"
CACHE_VERSION = 1
DEFAULT_SOURCES = ("openrouter", "local")
SUPPORTED_SOURCES = {"openrouter", "vultr", "huggingface", "local"}
SELECTABLE_COMPATIBILITY = {"ready", "needs_key"}


@dataclass(frozen=True)
class DiscoveredModel:
    """Normalized model metadata used by the console and tests."""

    source: str
    provider: str
    model_id: str
    display_name: str
    description: str = ""
    modalities: list[str] = field(default_factory=list)
    context_length: int = 0
    pricing: dict[str, Any] = field(default_factory=dict)
    supported_parameters: list[str] = field(default_factory=list)
    compatibility_status: str = "unsupported"
    auth_required: bool = True
    recommended_use_cases: list[str] = field(default_factory=list)
    last_refreshed: float = 0.0
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    cost_class: str = "unknown"
    capability_badges: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cache_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / CACHE_FILE_NAME


def load_model_discovery_cache(state_dir: str | Path) -> dict[str, Any]:
    path = cache_path(state_dir)
    if not path.exists():
        return _empty_cache()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_cache()
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return _empty_cache()
    data.setdefault("models", {})
    data.setdefault("sources", {})
    return data


def save_model_discovery_cache(state_dir: str | Path, cache: dict[str, Any]) -> Path:
    path = cache_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    return path


def get_model_discovery(
    *,
    config: dict[str, Any],
    state_dir: str | Path,
    sources: Iterable[str] | None = None,
    capabilities: Iterable[str] | None = None,
    compatibility: Iterable[str] | None = None,
    query: str = "",
) -> dict[str, Any]:
    """Return cached discovered models with optional UI filters."""

    cache = load_model_discovery_cache(state_dir)
    selected_sources = _normalize_sources(sources, default=SUPPORTED_SOURCES)
    capability_filter = {item.strip().lower() for item in (capabilities or []) if str(item).strip()}
    compatibility_filter = {item.strip().lower() for item in (compatibility or []) if str(item).strip()}
    query_text = query.strip().lower()
    models: list[dict[str, Any]] = []

    for source, items in cache.get("models", {}).items():
        if source not in selected_sources or not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if compatibility_filter and str(item.get("compatibility_status", "")).lower() not in compatibility_filter:
                continue
            badges = {str(badge).lower() for badge in item.get("capability_badges", [])}
            modalities = {str(mod).lower() for mod in item.get("modalities", [])}
            if capability_filter and not capability_filter.issubset(badges | modalities):
                continue
            haystack = " ".join(
                [
                    str(item.get("provider") or ""),
                    str(item.get("model_id") or ""),
                    str(item.get("display_name") or ""),
                    str(item.get("description") or ""),
                ]
            ).lower()
            if query_text and query_text not in haystack:
                continue
            models.append(item)

    models.sort(key=_model_sort_key)
    return {
        "ok": True,
        "cache_path": str(cache_path(state_dir)),
        "sources": cache.get("sources", {}),
        "alerts": cache.get("alerts", []),
        "models": models,
        "model_count": len(models),
        "provider_catalog": _provider_catalog(),
        "selected_provider": _model_config(config).get("provider", ""),
        "selected_model": _model_config(config).get("model", ""),
        "policy": {
            "strategy": "compatible_catalog",
            "activation": "review_then_activate",
            "secrets_are_write_only": True,
        },
    }


def _provider_catalog() -> dict[str, Any]:
    providers = sorted(TEXT_PROVIDERS)
    oauth_capable = {"codex_cli", "openrouter", "huggingface", "gemini"}
    local_private = {"ollama", "lmstudio", "llamacpp", "minimind"}
    return {
        "count": len(providers),
        "providers": providers,
        "oauth_or_device_capable": sorted(provider for provider in providers if provider in oauth_capable),
        "local_private": sorted(provider for provider in providers if provider in local_private),
        "discovery_sources": sorted(SUPPORTED_SOURCES),
        "default_sources": list(DEFAULT_SOURCES),
    }


def refresh_model_discovery(
    *,
    config: dict[str, Any],
    state_dir: str | Path,
    sources: Iterable[str] | None = None,
    fetch_json: FetchJson | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Refresh selected model sources and persist successful results."""

    fetch = fetch_json or _default_fetch_json
    timestamp = float(now if now is not None else time.time())
    selected_sources = _normalize_sources(sources, default=DEFAULT_SOURCES)
    cache = load_model_discovery_cache(state_dir)
    cache.setdefault("models", {})
    cache.setdefault("sources", {})
    cache.setdefault("alerts", [])
    refresh_alerts: list[dict[str, Any]] = []

    for source in selected_sources:
        try:
            models = _discover_source(source, config=config, fetch_json=fetch, timestamp=timestamp)
        except Exception as exc:  # pragma: no cover - exact network exceptions vary
            previous = cache["sources"].get(source, {}) if isinstance(cache["sources"], dict) else {}
            cache["sources"][source] = {
                "ok": False,
                "source": source,
                "error": _safe_error(exc),
                "count": previous.get("count", 0),
                "last_refreshed": previous.get("last_refreshed", 0.0),
            }
            continue
        new_models = [model.to_dict() for model in models]
        refresh_alerts.extend(_detect_model_alerts(source, cache.get("models", {}).get(source, []), new_models, timestamp))
        cache["models"][source] = new_models
        cache["sources"][source] = {
            "ok": True,
            "source": source,
            "error": "",
            "count": len(models),
            "last_refreshed": timestamp,
        }

    cache["alerts"] = refresh_alerts[:50]
    save_model_discovery_cache(state_dir, cache)
    return get_model_discovery(config=config, state_dir=state_dir, sources=selected_sources)


def select_discovered_model(
    *,
    config: dict[str, Any],
    state_dir: str | Path,
    provider: str,
    model_id: str,
    source: str = "",
) -> dict[str, Any]:
    """Return a config copy updated with a selected compatible model."""

    provider = provider.strip().lower()
    model_id = model_id.strip()
    source = source.strip().lower()
    if len(provider) > 80 or len(model_id) > 300 or len(source) > 80:
        return {"ok": False, "error": "Selection is too long."}
    if provider not in TEXT_PROVIDERS:
        return {"ok": False, "error": "Ghost Chimera does not have a provider for this model yet."}

    cache = load_model_discovery_cache(state_dir)
    match = _find_cached_model(cache, provider=provider, model_id=model_id, source=source)
    if not match:
        return {"ok": False, "error": "Model is not in the discovery cache. Refresh discovery first."}
    if match.get("compatibility_status") not in SELECTABLE_COMPATIBILITY:
        return {"ok": False, "error": "This model is a candidate only and cannot be activated yet."}

    next_config = dict(config)
    model = dict(_model_config(next_config))
    model["provider"] = provider
    model["model"] = model_id
    default_base_url = _default_base_url_for_provider(provider)
    if default_base_url:
        model["base_url"] = default_base_url
    elif provider in {"ollama", "lmstudio"}:
        model["base_url"] = match.get("raw_metadata", {}).get("base_url", "")
    next_config["model"] = model
    return {
        "ok": True,
        "config": next_config,
        "selected_model": match,
        "requires_api_key": match.get("compatibility_status") == "needs_key",
    }


def normalize_openrouter_models(payload: dict[str, Any], *, has_api_key: bool, timestamp: float) -> list[DiscoveredModel]:
    models = payload.get("data", [])
    if not isinstance(models, list):
        raise ValueError("OpenRouter response missing data list")
    return [_openrouter_model(item, has_api_key=has_api_key, timestamp=timestamp) for item in models if isinstance(item, dict)]


def normalize_vultr_models(payload: dict[str, Any], *, timestamp: float) -> list[DiscoveredModel]:
    models = payload.get("data") or payload.get("models") or []
    if not isinstance(models, list):
        raise ValueError("Vultr response missing models list")
    return [_vultr_model(item, timestamp=timestamp) for item in models if isinstance(item, dict)]


def normalize_huggingface_models(payload: dict[str, Any] | list[Any], *, has_api_key: bool, timestamp: float) -> list[DiscoveredModel]:
    models = payload if isinstance(payload, list) else payload.get("models", [])
    if not isinstance(models, list):
        raise ValueError("Hugging Face response missing models list")
    return [
        _huggingface_model(item, has_api_key=has_api_key, timestamp=timestamp)
        for item in models
        if isinstance(item, dict)
    ]


def normalize_local_models(payload: dict[str, Any], *, provider: str, base_url: str, timestamp: float) -> list[DiscoveredModel]:
    models = payload.get("data") or payload.get("models") or []
    if not isinstance(models, list):
        raise ValueError("Local model response missing models list")
    normalized: list[DiscoveredModel] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or item.get("name") or "").strip()
        if not model_id:
            continue
        normalized.append(
            DiscoveredModel(
                source="local",
                provider=provider,
                model_id=model_id,
                display_name=model_id,
                description=f"Local {provider} model.",
                modalities=["text"],
                context_length=0,
                pricing={"prompt": 0, "completion": 0},
                supported_parameters=["temperature", "max_tokens"],
                compatibility_status="ready",
                auth_required=False,
                recommended_use_cases=["virtual-assistant", "privacy-sensitive"],
                last_refreshed=timestamp,
                raw_metadata={"base_url": base_url},
                cost_class="local",
                capability_badges=["text", "local", "private"],
            )
        )
    return normalized


def _discover_source(source: str, *, config: dict[str, Any], fetch_json: FetchJson, timestamp: float) -> list[DiscoveredModel]:
    if source == "openrouter":
        api_key = _configured_secret(config, "openrouter")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        payload = fetch_json("https://openrouter.ai/api/v1/models", headers, 10.0)
        return normalize_openrouter_models(_ensure_dict(payload), has_api_key=bool(api_key), timestamp=timestamp)
    if source == "vultr":
        api_key = _configured_secret(config, "vultr")
        if not api_key:
            raise ValueError("Vultr inference API key is not configured.")
        payload = fetch_json("https://api.vultrinference.com/v1/models", {"Authorization": f"Bearer {api_key}"}, 10.0)
        return normalize_vultr_models(_ensure_dict(payload), timestamp=timestamp)
    if source == "huggingface":
        api_key = _configured_secret(config, "huggingface")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        params = urllib_parse.urlencode({"filter": "text-generation", "sort": "downloads", "direction": "-1", "limit": "50"})
        payload = fetch_json(f"https://huggingface.co/api/models?{params}", headers, 10.0)
        return normalize_huggingface_models(payload, has_api_key=bool(api_key), timestamp=timestamp)
    if source == "local":
        return _discover_local(fetch_json=fetch_json, timestamp=timestamp)
    raise ValueError(f"Unsupported discovery source: {source}")


def _discover_local(*, fetch_json: FetchJson, timestamp: float) -> list[DiscoveredModel]:
    discovered: list[DiscoveredModel] = []
    endpoints = [
        ("ollama", "http://localhost:11434", "http://localhost:11434/v1/models"),
        ("lmstudio", "http://localhost:1234", "http://localhost:1234/v1/models"),
    ]
    errors: list[str] = []
    for provider, base_url, models_url in endpoints:
        try:
            payload = fetch_json(models_url, {}, 2.0)
            discovered.extend(normalize_local_models(_ensure_dict(payload), provider=provider, base_url=base_url, timestamp=timestamp))
        except Exception as exc:  # pragma: no cover - depends on local services
            errors.append(_safe_error(exc))
    if not discovered and errors:
        raise ValueError("; ".join(errors))
    return discovered


def _openrouter_model(item: dict[str, Any], *, has_api_key: bool, timestamp: float) -> DiscoveredModel:
    model_id = str(item.get("id") or item.get("canonical_slug") or "").strip()
    architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
    input_modalities = _listify(architecture.get("input_modalities"))
    output_modalities = _listify(architecture.get("output_modalities"))
    modalities = sorted({*(input_modalities or ["text"]), *output_modalities})
    pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
    supported = _listify(item.get("supported_parameters"))
    badges = _capability_badges(model_id, item.get("name", model_id), modalities, supported, int(item.get("context_length") or 0), pricing)
    return DiscoveredModel(
        source="openrouter",
        provider="openrouter",
        model_id=model_id,
        display_name=str(item.get("name") or model_id),
        description=str(item.get("description") or ""),
        modalities=modalities,
        context_length=int(item.get("context_length") or 0),
        pricing=pricing,
        supported_parameters=supported,
        compatibility_status="ready" if has_api_key else "needs_key",
        auth_required=True,
        recommended_use_cases=_recommended_use_cases(model_id, str(item.get("name") or model_id), badges),
        last_refreshed=timestamp,
        raw_metadata=_safe_raw(item),
        cost_class=_cost_class(pricing),
        capability_badges=badges,
    )


def _vultr_model(item: dict[str, Any], *, timestamp: float) -> DiscoveredModel:
    model_id = str(item.get("id") or item.get("name") or "").strip()
    features = _listify(item.get("features"))
    badges = _capability_badges(model_id, model_id, ["text"], features, 0, item)
    return DiscoveredModel(
        source="vultr",
        provider="vultr",
        model_id=model_id,
        display_name=str(item.get("name") or model_id),
        description=str(item.get("description") or "Vultr Serverless Inference model."),
        modalities=["text"],
        context_length=int(item.get("context_length") or item.get("context_window") or 0),
        pricing={key: item[key] for key in ("price", "prompt", "completion") if key in item},
        supported_parameters=features,
        compatibility_status="ready",
        auth_required=True,
        recommended_use_cases=_recommended_use_cases(model_id, model_id, badges),
        last_refreshed=timestamp,
        raw_metadata=_safe_raw(item),
        cost_class=_cost_class(item),
        capability_badges=badges,
    )


def _huggingface_model(item: dict[str, Any], *, has_api_key: bool, timestamp: float) -> DiscoveredModel:
    model_id = str(item.get("modelId") or item.get("id") or "").strip()
    tags = _listify(item.get("tags"))
    badges = _capability_badges(model_id, model_id, tags, tags, 0, {})
    status = "candidate_only"
    if has_api_key and any(tag in tags for tag in ("text-generation", "conversational")):
        status = "candidate_only"
    return DiscoveredModel(
        source="huggingface",
        provider="huggingface",
        model_id=model_id,
        display_name=model_id,
        description=str(item.get("description") or "Hugging Face Hub model candidate."),
        modalities=["text"] if "text-generation" in tags else [],
        context_length=0,
        pricing={},
        supported_parameters=tags,
        compatibility_status=status,
        auth_required=True,
        recommended_use_cases=_recommended_use_cases(model_id, model_id, badges),
        last_refreshed=timestamp,
        raw_metadata={"tags": tags, "downloads": item.get("downloads"), "likes": item.get("likes")},
        cost_class="unknown",
        capability_badges=sorted(set(badges + ["open-weight"])),
    )


def _default_fetch_json(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any] | list[Any]:
    req = urllib_request.Request(url, headers={"Accept": "application/json", **headers}, method="GET")
    context = _discovery_ssl_context()
    with urllib_request.urlopen(req, timeout=timeout, context=context) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _discovery_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict_flag and hasattr(context, "verify_flags"):
        context.verify_flags &= ~strict_flag
    return context


def _normalize_sources(sources: Iterable[str] | None, *, default: Iterable[str]) -> set[str]:
    selected = {str(source).strip().lower() for source in (sources or default) if str(source).strip()}
    invalid = selected - SUPPORTED_SOURCES
    if invalid:
        raise ValueError(f"Unsupported discovery source: {', '.join(sorted(invalid))}")
    return selected or set(default)


def _empty_cache() -> dict[str, Any]:
    return {"version": CACHE_VERSION, "models": {}, "sources": {}, "alerts": []}


def _model_config(config: dict[str, Any]) -> dict[str, Any]:
    model = config.get("model", {})
    return model if isinstance(model, dict) else {}


def _configured_secret(config: dict[str, Any], provider: str) -> str:
    model = _model_config(config)
    if model.get("provider") == provider and model.get("api_key"):
        return str(model["api_key"])
    if provider == "openrouter":
        return os.environ.get("OPENROUTER_API_KEY", "")
    if provider == "vultr":
        return os.environ.get("VULTR_INFERENCE_API_KEY", "")
    if provider == "huggingface":
        return os.environ.get("HF_TOKEN", "") or os.environ.get("HUGGINGFACE_API_KEY", "")
    return ""


def _find_cached_model(cache: dict[str, Any], *, provider: str, model_id: str, source: str = "") -> dict[str, Any] | None:
    for cached_source, items in cache.get("models", {}).items():
        if source and cached_source != source:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("provider") == provider and item.get("model_id") == model_id:
                return item
    return None


def _default_base_url_for_provider(provider: str) -> str:
    if provider == "openrouter":
        return "https://openrouter.ai/api/v1/chat/completions"
    if provider == "vultr":
        return "https://api.vultrinference.com/v1/chat/completions"
    if provider == "huggingface":
        return "https://api-inference.huggingface.co/v1/chat/completions"
    return ""


def _ensure_dict(payload: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Expected JSON object")
    return payload


def _listify(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip().lower()]
    return []


def _capability_badges(
    model_id: str,
    name: str,
    modalities: list[str],
    supported_parameters: list[str],
    context_length: int,
    pricing: dict[str, Any],
) -> list[str]:
    text = f"{model_id} {name}".lower()
    badges = set(modalities or ["text"])
    params = {param.lower() for param in supported_parameters}
    if "tools" in params or "tool_choice" in params or "function_calling" in params or "tool" in text:
        badges.add("tool-calling")
    if "image" in badges or "vision" in text or "vl" in text:
        badges.add("vision")
    if any(marker in text for marker in ("reason", "r1", "deepseek", "o1", "o3")):
        badges.add("reasoning")
    if context_length >= 100_000:
        badges.add("long-context")
    if any(marker in text for marker in ("llama", "mistral", "mixtral", "qwen", "gemma", "deepseek")):
        badges.add("open-weight")
    if _cost_class(pricing) in {"free", "low"}:
        badges.add("low-cost")
    return sorted(badges)


def _recommended_use_cases(model_id: str, name: str, badges: list[str]) -> list[str]:
    text = f"{model_id} {name}".lower()
    use_cases = set()
    if "reasoning" in badges or "code" in text or "coder" in text:
        use_cases.update({"ai-engineer", "analyst", "self-evolution"})
    if "long-context" in badges:
        use_cases.update({"manager", "analyst"})
    if "low-cost" in badges:
        use_cases.update({"virtual-assistant", "marketing-specialist"})
    if "vision" in badges:
        use_cases.update({"analyst", "multimodal-review"})
    if not use_cases:
        use_cases.update({"virtual-assistant", "manager"})
    return sorted(use_cases)


def _cost_class(pricing: dict[str, Any]) -> str:
    if not pricing:
        return "unknown"
    values: list[float] = []
    for key in ("prompt", "completion", "input", "output", "price"):
        raw = pricing.get(key)
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not values:
        return "unknown"
    if max(values) == 0:
        return "free"
    if max(values) <= 0.00001:
        return "low"
    if max(values) <= 0.0001:
        return "medium"
    return "high"


def _model_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    status_order = {"ready": 0, "needs_key": 1, "candidate_only": 2, "unsupported": 3}
    cost_order = {"free": 0, "local": 0, "low": 1, "medium": 2, "unknown": 3, "high": 4}
    return (
        status_order.get(str(item.get("compatibility_status")), 9),
        str(cost_order.get(str(item.get("cost_class")), 9)),
        str(item.get("display_name") or item.get("model_id") or ""),
    )


def _detect_model_alerts(
    source: str, previous_models: Any, new_models: list[dict[str, Any]], timestamp: float
) -> list[dict[str, Any]]:
    if not isinstance(previous_models, list) or not previous_models:
        return []
    previous_by_id = {
        str(item.get("model_id")): item for item in previous_models if isinstance(item, dict) and item.get("model_id")
    }
    next_by_id = {str(item.get("model_id")): item for item in new_models if item.get("model_id")}
    alerts: list[dict[str, Any]] = []
    for model_id, old in previous_by_id.items():
        if model_id not in next_by_id:
            alerts.append({"source": source, "model_id": model_id, "kind": "removed", "timestamp": timestamp})
            continue
        new = next_by_id[model_id]
        if old.get("pricing") != new.get("pricing"):
            alerts.append({"source": source, "model_id": model_id, "kind": "pricing_changed", "timestamp": timestamp})
        old_badges = set(old.get("capability_badges", []) or [])
        new_badges = set(new.get("capability_badges", []) or [])
        gained = sorted(new_badges - old_badges)
        if gained:
            alerts.append(
                {"source": source, "model_id": model_id, "kind": "capabilities_added", "added": gained, "timestamp": timestamp}
            )
    for model_id in sorted(set(next_by_id) - set(previous_by_id)):
        alerts.append({"source": source, "model_id": model_id, "kind": "added", "timestamp": timestamp})
    return alerts[:50]


def _safe_raw(item: dict[str, Any]) -> dict[str, Any]:
    forbidden = {"api_key", "token", "authorization", "secret", "password"}
    safe: dict[str, Any] = {}
    for key, value in item.items():
        if any(marker in str(key).lower() for marker in forbidden):
            continue
        if isinstance(value, str | int | float | bool) or value is None:
            safe[key] = value
        elif isinstance(value, list):
            safe[key] = value[:20]
        elif isinstance(value, dict):
            safe[key] = {
                subkey: subvalue
                for subkey, subvalue in value.items()
                if not any(marker in str(subkey).lower() for marker in forbidden)
            }
    return safe


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, urllib_error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib_error.URLError):
        return "Network error while refreshing model catalog."
    text = str(exc)
    for key in ("OPENROUTER_API_KEY", "VULTR_INFERENCE_API_KEY", "HF_TOKEN"):
        text = text.replace(os.environ.get(key, ""), "[redacted]") if os.environ.get(key) else text
    return text[:500]
