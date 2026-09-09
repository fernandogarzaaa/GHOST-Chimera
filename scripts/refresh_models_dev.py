"""Sync Ghost's provider snapshot from models.dev (the open model database OpenCode builds on).

Usage:
    python scripts/refresh_models_dev.py [--input api.json] [--out docs/model_provider_catalog.modelsdev.json]
                                         [--max-models 25] [--provider openai,anthropic]

Without --input, downloads https://models.dev/api.json (stdlib urllib).
Output is secret-free and deterministic: provider id/name/env, model id,
context/output limits, tool_call, modalities, per-1M costs. Accepts a local
--input file for offline runs and tests.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://models.dev/api.json"
DEFAULT_OUT = REPO_ROOT / "docs" / "model_provider_catalog.modelsdev.json"


def _load(source: str | None) -> dict[str, Any]:
    if source:
        return json.loads(Path(source).read_text(encoding="utf-8"))
    req = urllib.request.Request(DEFAULT_URL, headers={"User-Agent": "Ghost-Chimera/0.4"})
    with urllib.request.urlopen(req, timeout=60.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _safe_model(model_id: str, model: dict[str, Any]) -> dict[str, Any]:
    limit = model.get("limit") or {}
    cost = model.get("cost") or {}
    modalities = model.get("modalities") or {}
    return {
        "model_id": model_id,
        "name": str(model.get("name", model_id)),
        "context": int(limit.get("context") or 0),
        "output": int(limit.get("output") or 0),
        "tool_call": bool(model.get("tool_call")),
        "reasoning": bool(model.get("reasoning")),
        "input_modalities": list(modalities.get("input") or []),
        "output_modalities": list(modalities.get("output") or []),
        "cost_input_per_1m": cost.get("input"),
        "cost_output_per_1m": cost.get("output"),
        "release_date": str(model.get("release_date") or ""),
    }


def build_snapshot(data: dict[str, Any], *, providers: list[str] | None,
                   max_models: int) -> dict[str, Any]:
    snapshot_providers: dict[str, Any] = {}
    for provider_id, entry in sorted(data.items()):
        if providers and provider_id not in providers:
            continue
        if not isinstance(entry, dict):
            continue
        models = entry.get("models") or {}
        safe = [_safe_model(mid, m) for mid, m in models.items() if isinstance(m, dict)]
        safe.sort(key=lambda m: (-m["context"], m["model_id"]))
        snapshot_providers[provider_id] = {
            "name": str(entry.get("name", provider_id)),
            "env": list(entry.get("env") or []),
            "doc": str(entry.get("doc", "")),
            "model_count": len(safe),
            "models": safe[:max_models],
        }
    return {
        "schema_version": 1,
        "source": "models.dev",
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "providers": snapshot_providers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="", help="Local models.dev api.json (offline mode)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Snapshot output path")
    parser.add_argument("--max-models", type=int, default=25, help="Models kept per provider")
    parser.add_argument("--provider", default="",
                        help="Comma-separated provider ids to include (default: all)")
    args = parser.parse_args(argv)
    try:
        data = _load(args.input or None)
    except Exception as exc:
        print(f"ERROR: could not load models.dev data: {exc}", file=sys.stderr)
        return 1
    providers = [p.strip() for p in args.provider.split(",") if p.strip()] or None
    snapshot = build_snapshot(data, providers=providers, max_models=args.max_models)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    total_models = sum(p["model_count"] for p in snapshot["providers"].values())
    print(f"Wrote {out} ({len(snapshot['providers'])} providers, {total_models} models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
