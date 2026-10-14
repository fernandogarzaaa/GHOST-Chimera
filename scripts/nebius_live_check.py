#!/usr/bin/env python3
"""Live check of every configured Nebius Token Factory / Nemotron model.

Sends one small chat completion per model through the same request shape
``NebiusProvider`` uses (User-Agent, max_tokens, Bearer auth) and the same
answer extraction (``<think>`` stripped, ``reasoning_content`` ignored),
then writes ``docs/NEBIUS_LIVE_CHECK.md``.

Requires ``NEBIUS_API_KEY`` in the environment. The key is only ever sent in
the Authorization header; it is never printed or written to the report.

    python scripts/nebius_live_check.py [--output docs/NEBIUS_LIVE_CHECK.md]
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ghostchimera.http_identity import USER_AGENT, ensure_user_agent  # noqa: E402
from ghostchimera.model_layer.openai_compatible_providers import NebiusProvider  # noqa: E402
from ghostchimera.model_layer.reasoning_output import extract_answer  # noqa: E402
from ghostchimera.stealth.nemotron_reasoning import NANO_MODEL, SUPER_MODEL  # noqa: E402

# Every Nebius model ID the codebase configures: the NebiusProvider default and
# docstring list, the model catalog, and the Stealth Loop reasoner.
CONFIGURED_MODELS = [
    NANO_MODEL,
    SUPER_MODEL,
    "nvidia/Nemotron-3-Ultra-550b-a55b",
    "nvidia/Nemotron-3_5-Lightning",
]
MODELS_URL = "https://api.tokenfactory.nebius.com/v1/models"
PROMPT_SYSTEM = "You are a terse assistant."
PROMPT_USER = "Reply with exactly the word: pong"


def _list_models(headers: dict[str, str]) -> tuple[int, list[str], str]:
    req = ensure_user_agent(urllib.request.Request(MODELS_URL, headers=headers, method="GET"))
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, sorted(str(m.get("id")) for m in data.get("data", [])), ""
    except urllib.error.HTTPError as exc:
        return exc.code, [], exc.reason or ""
    except Exception as exc:  # noqa: BLE001
        return 0, [], f"{type(exc).__name__}: {exc}"


def _check(model: str) -> dict:
    provider = NebiusProvider()
    provider.model = model
    body = {
        "model": model,
        "messages": [{"role": "system", "content": PROMPT_SYSTEM}, {"role": "user", "content": PROMPT_USER}],
        "temperature": 0.0,
        "max_tokens": provider.max_tokens,
    }
    req = ensure_user_agent(
        urllib.request.Request(
            provider._base_url, data=json.dumps(body).encode(), headers=provider._build_headers(), method="POST"
        )
    )
    row = {"model": model, "status": 0, "latency_s": None, "ok": False, "excerpt": "", "note": ""}
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120, context=ssl.create_default_context()) as resp:
            row["status"] = resp.status
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        row["status"] = exc.code
        row["latency_s"] = round(time.monotonic() - started, 2)
        detail = exc.read().decode("utf-8", "replace")[:160].replace("\n", " ")
        row["note"] = f"HTTP error: {detail}"
        return row
    except Exception as exc:  # noqa: BLE001
        row["latency_s"] = round(time.monotonic() - started, 2)
        row["note"] = f"{type(exc).__name__}: {exc}"[:160]
        return row
    row["latency_s"] = round(time.monotonic() - started, 2)
    message = ((payload.get("choices") or [{}])[0] or {}).get("message") or {}
    content = message.get("content") or ""
    notes = []
    if "<think>" in str(content).lower():
        notes.append("inline <think> stripped")
    if message.get("reasoning_content") or message.get("reasoning"):
        notes.append("reasoning_content ignored")
    usage = payload.get("usage") or {}
    if usage.get("completion_tokens") is not None:
        notes.append(f"completion_tokens={usage.get('completion_tokens')}")
    try:
        answer = extract_answer(payload, "nebius")
        row["ok"] = True
        row["excerpt"] = answer[:80].replace("\n", " ").replace("|", "\\|")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"{type(exc).__name__}: {exc}"[:160])
    row["note"] = "; ".join(notes)
    return row


def render(rows: list[dict], listing: tuple[int, list[str], str], when: str) -> str:
    status, ids, err = listing
    lines = [
        "# Nebius Token Factory live check",
        "",
        f"Run: {when} by `scripts/nebius_live_check.py` (re-run it to refresh this file).",
        "",
        f"- Endpoint: `{NebiusProvider._DEFAULT_BASE_URL}`",
        f"- Request: one chat completion per model, `max_tokens={NebiusProvider().max_tokens}`, "
        f'`temperature=0`, `User-Agent: {USER_AGENT}`, prompt "{PROMPT_USER}".',
        "- Answer extraction: `ghostchimera.model_layer.reasoning_output.extract_answer` "
        "(`<think>` stripped, `reasoning_content` ignored, empty answer = failure).",
        f"- `GET /v1/models`: HTTP {status}" + (f" ({err})" if err else f", {len(ids)} models listed"),
        "",
        "| Model ID | Listed in /v1/models | HTTP | Latency (s) | Non-empty answer | Excerpt | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        listed = "yes" if r["model"] in ids else ("no" if ids else "unknown")
        lines.append(
            f"| `{r['model']}` | {listed} | {r['status'] or '-'} | {r['latency_s'] if r['latency_s'] is not None else '-'} "
            f"| {'yes' if r['ok'] else 'no'} | {r['excerpt'] or '-'} | {r['note'] or '-'} |"
        )
    nemotron = [i for i in ids if "nemotron" in i.lower()]
    if nemotron:
        lines += ["", "Nemotron models currently listed by Token Factory:", ""]
        lines += [f"- `{i}`" for i in nemotron]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", default=str(ROOT / "docs" / "NEBIUS_LIVE_CHECK.md"))
    args = parser.parse_args(argv)
    if not os.environ.get("NEBIUS_API_KEY"):
        print("NEBIUS_API_KEY is not set; nothing to check.", file=sys.stderr)
        return 2
    provider = NebiusProvider()
    listing = _list_models(provider._build_headers())
    rows = [_check(m) for m in CONFIGURED_MODELS]
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    Path(args.output).write_text(render(rows, listing, when), encoding="utf-8")
    for r in rows:
        print(f"{r['model']}: HTTP {r['status']} {r['latency_s']}s ok={r['ok']} {r['excerpt']!r} {r['note']}")
    return 0 if all(r["ok"] for r in rows if r["model"] in (NANO_MODEL, SUPER_MODEL)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
