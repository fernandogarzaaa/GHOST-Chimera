"""Optional LangSmith tracing for GHOST-Chimera cloud integration paths.

This module is deliberately stdlib-only: it speaks to the LangSmith ingest
API directly (``https://api.smith.langchain.com``) with ``urllib`` instead of
depending on the ``langsmith`` Python SDK. That keeps the tracing path
dependency-free and optional.

Environment:
    LANGSMITH_API_KEY   Tracing API key. When unset, tracing is fully
                        disabled and every call here is a no-op (zero
                        behavior change to the instrumented code paths).
    LANGSMITH_PROJECT   Project name runs are filed under.
                        Default: "ghost-chimera-hackathon".
    LANGSMITH_TRACING   Set to "0" (or "false"/"no") to disable even when a
                        key is present. Any other value leaves the default
                        on-with-key behavior in place.
    LANGSMITH_ENDPOINT  Override for the LangSmith API base URL
                        (e.g. self-hosted). Default: https://api.smith.langchain.com

Tracing never raises and never logs or transmits API keys: instrumentation
points wrap all network calls in try/except, and run payloads carry only
event names, models, queries, and result counts.
"""

from __future__ import annotations

import json
import os
import ssl
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib import request as urllib_request

DEFAULT_ENDPOINT = "https://api.smith.langchain.com"
DEFAULT_PROJECT = "ghost-chimera-hackathon"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class LangSmithConfig:
    api_key: str
    project: str = DEFAULT_PROJECT
    endpoint: str = DEFAULT_ENDPOINT
    enabled: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LangSmithConfig | None:
        source = env if env is not None else os.environ
        api_key = (source.get("LANGSMITH_API_KEY") or "").strip()
        if not api_key:
            return None
        toggle = (source.get("LANGSMITH_TRACING") or "1").strip().lower()
        enabled = toggle not in ("0", "false", "no", "off")
        project = (source.get("LANGSMITH_PROJECT") or DEFAULT_PROJECT).strip() or DEFAULT_PROJECT
        endpoint = (source.get("LANGSMITH_ENDPOINT") or DEFAULT_ENDPOINT).strip().rstrip("/")
        return cls(api_key=api_key, project=project, endpoint=endpoint, enabled=enabled)


class LangSmithTracer:
    """Minimal LangSmith run client over the public ingest REST API.

    POST /api/v1/runs          -> create a run (returns a run handle)
    PATCH /api/v1/runs/{id}    -> close the run with outputs or an error

    Every network operation is best-effort: failures are swallowed so a
    tracing outage can never break the traced code path.
    """

    def __init__(self, config: LangSmithConfig | None = None) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config is not None and self.config.enabled

    # -- low-level transport -------------------------------------------------
    def _headers(self) -> dict[str, str]:
        # The API key travels only in the header; it is never logged or echoed.
        return {
            "x-api-key": self.config.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _post_json(self, path: str, payload: dict[str, Any], method: str = "POST") -> None:
        if not self.enabled:
            return
        data = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(f"{self.config.endpoint}{path}", data=data, headers=self._headers(), method=method)
        try:
            with urllib_request.urlopen(req, timeout=10.0, context=ssl.create_default_context()):
                pass
        except Exception:
            # Tracing is observability only; never let it break the caller.
            return

    # -- run lifecycle -------------------------------------------------------
    def start_run(
        self,
        name: str,
        *,
        run_type: str = "llm",
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Open a run. Returns an opaque run handle, or None when disabled."""
        if not self.enabled:
            return None
        run_id = str(uuid.uuid4())
        self._post_json(
            "/api/v1/runs",
            {
                "id": run_id,
                "name": name,
                "run_type": run_type,
                "inputs": inputs or {},
                "session_name": self.config.project,
                "start_time": _utc_now(),
                "metadata": metadata or {},
                "tags": tags or [],
            },
        )
        return {"id": run_id, "name": name}

    def end_run(
        self,
        run: dict[str, Any] | None,
        *,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Close a run with outputs (success) or an error string (failure)."""
        if not self.enabled or not run:
            return
        payload: dict[str, Any] = {"end_time": _utc_now()}
        if error is not None:
            payload["error"] = error[:2000]
        else:
            payload["outputs"] = outputs or {}
        self._post_json(f"/api/v1/runs/{run['id']}", payload, method="PATCH")

    @contextmanager
    def trace(
        self,
        name: str,
        *,
        run_type: str = "llm",
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[dict[str, Any] | None]:
        """Context manager: open a run, yield it, close with outputs or error."""
        run = self.start_run(name, run_type=run_type, inputs=inputs, metadata=metadata, tags=tags)
        try:
            yield run
        except Exception as exc:  # noqa: BLE001 - tracing must not mask caller errors
            self.end_run(run, error=f"{type(exc).__name__}: {exc}")
            raise
        else:
            self.end_run(run, outputs={})


def get_default_tracer(env: Mapping[str, str] | None = None) -> LangSmithTracer:
    """Build a tracer from the environment. Cheap; call sites use it directly."""
    return LangSmithTracer(LangSmithConfig.from_env(env))
