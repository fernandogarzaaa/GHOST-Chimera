"""Refresh a safe model-provider catalog snapshot for maintenance PRs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ghostchimera.model_layer.model_discovery import (  # noqa: E402
    load_model_discovery_cache,
    refresh_model_discovery,
)

DEFAULT_SOURCES = ("openrouter", "huggingface", "vultr")
DEFAULT_MAX_MODELS_PER_SOURCE = 75


def _source_list(raw: str) -> list[str]:
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _model_rank(model: dict[str, Any]) -> tuple[int, int, str]:
    status = str(model.get("compatibility_status") or "")
    status_rank = {"ready": 0, "needs_key": 1, "candidate_only": 2, "unsupported": 3}.get(status, 4)
    return (status_rank, -int(model.get("context_length") or 0), str(model.get("model_id") or ""))


def _safe_model(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": str(model.get("source") or ""),
        "provider": str(model.get("provider") or ""),
        "model_id": str(model.get("model_id") or ""),
        "display_name": str(model.get("display_name") or ""),
        "modalities": list(model.get("modalities") or []),
        "context_length": int(model.get("context_length") or 0),
        "compatibility_status": str(model.get("compatibility_status") or ""),
        "auth_required": bool(model.get("auth_required")),
        "cost_class": str(model.get("cost_class") or ""),
        "capability_badges": list(model.get("capability_badges") or []),
        "recommended_use_cases": list(model.get("recommended_use_cases") or []),
    }


def build_snapshot(
    cache: dict[str, Any], *, sources: list[str], generated_at: float, max_models_per_source: int
) -> dict[str, Any]:
    """Build a deterministic, secret-free provider catalog snapshot."""

    source_payload: dict[str, Any] = {}
    selected_models: list[dict[str, Any]] = []
    models_by_source = cache.get("models") if isinstance(cache.get("models"), dict) else {}
    source_status = cache.get("sources") if isinstance(cache.get("sources"), dict) else {}
    for source in sources:
        models = models_by_source.get(source, [])
        safe_models = [_safe_model(model) for model in models if isinstance(model, dict)]
        safe_models.sort(key=_model_rank)
        status = source_status.get(source, {}) if isinstance(source_status.get(source), dict) else {}
        source_payload[source] = {
            "ok": bool(status.get("ok")),
            "count": int(status.get("count") or len(safe_models)),
            "error": str(status.get("error") or ""),
            "last_refreshed": float(status.get("last_refreshed") or 0.0),
            "included_count": min(len(safe_models), max_models_per_source),
        }
        selected_models.extend(safe_models[:max_models_per_source])

    selected_models.sort(key=lambda item: (item["source"], _model_rank(item)))
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(generated_at)),
        "sources": source_payload,
        "model_count": len(selected_models),
        "models": selected_models,
        "policy": {
            "purpose": "daily_provider_catalog_snapshot",
            "activation": "review_then_activate",
            "secrets_included": False,
            "automatic_model_switching": False,
        },
    }


def render_markdown(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Model Provider Catalog",
        "",
        f"Generated: `{snapshot['generated_at_iso']}`",
        "",
        "This file is refreshed by the daily maintenance workflow. It is advisory only: Ghost Chimera never switches active models without operator approval.",
        "",
        "## Sources",
        "",
        "| Source | OK | Count | Included | Last Refresh | Error |",
        "|---|---:|---:|---:|---|---|",
    ]
    for source, status in sorted(snapshot["sources"].items()):
        refreshed = (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(status.get("last_refreshed") or 0)))
            if status.get("last_refreshed")
            else ""
        )
        error = str(status.get("error") or "").replace("|", "\\|")
        lines.append(
            f"| `{source}` | {status.get('ok')} | {status.get('count')} | {status.get('included_count')} | `{refreshed}` | {error} |"
        )
    lines.extend(["", "## Included Models", ""])
    current_source = ""
    for model in snapshot["models"]:
        source = str(model.get("source") or "")
        if source != current_source:
            current_source = source
            lines.extend(["", f"### {source}", "", "| Model | Status | Context | Cost | Badges | Use Cases |", "|---|---|---:|---|---|---|"])
        badges = ", ".join(str(item) for item in model.get("capability_badges") or [])
        use_cases = ", ".join(str(item) for item in model.get("recommended_use_cases") or [])
        lines.append(
            f"| `{model.get('model_id')}` | {model.get('compatibility_status')} | {model.get('context_length')} | {model.get('cost_class')} | {badges} | {use_cases} |"
        )
    lines.append("")
    return "\n".join(lines)


def run_refresh(*, sources: list[str], state_dir: Path, max_models_per_source: int) -> dict[str, Any]:
    config = {"model": {"provider": "", "model": ""}}
    refresh_model_discovery(config=config, state_dir=state_dir, sources=sources)
    cache = load_model_discovery_cache(state_dir)
    return build_snapshot(
        cache,
        sources=sources,
        generated_at=time.time(),
        max_models_per_source=max_models_per_source,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES), help="Comma-separated discovery sources.")
    parser.add_argument("--state-dir", default="", help="Working state directory for discovery cache.")
    parser.add_argument("--output-json", default="docs/model_provider_catalog.json")
    parser.add_argument("--output-markdown", default="docs/model_provider_catalog.md")
    parser.add_argument("--max-models-per-source", type=int, default=DEFAULT_MAX_MODELS_PER_SOURCE)
    args = parser.parse_args()

    sources = _source_list(args.sources)
    state_dir = Path(args.state_dir).expanduser() if args.state_dir else Path(tempfile.gettempdir()) / "ghostchimera-provider-refresh"
    max_models = max(1, min(int(args.max_models_per_source), 500))
    snapshot = run_refresh(sources=sources, state_dir=state_dir, max_models_per_source=max_models)

    output_json = Path(args.output_json)
    output_md = Path(args.output_markdown)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(snapshot), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "sources": snapshot["sources"],
                "model_count": snapshot["model_count"],
                "output_json": str(output_json),
                "output_markdown": str(output_md),
                "secrets_used": {
                    "openrouter": bool(os.environ.get("OPENROUTER_API_KEY")),
                    "huggingface": bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY")),
                    "vultr": bool(os.environ.get("VULTR_INFERENCE_API_KEY")),
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
