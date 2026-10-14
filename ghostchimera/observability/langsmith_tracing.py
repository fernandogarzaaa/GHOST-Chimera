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

Tracing never blocks the traced call: run create/close POSTs are queued to a
single background sender thread (bounded queue, dropped on overflow, 2 s
timeout per POST; ``LANGSMITH_TIMEOUT_S`` overrides), so a slow or unreachable
LangSmith endpoint adds no latency to a model call.

Tracing never raises and never logs or transmits API keys: instrumentation
points wrap all network calls in try/except, and every run's inputs,
outputs, metadata and error text pass through
:func:`ghostchimera.redaction.redact_for_egress` (secrets and PII) before
they are sent.
"""

from __future__ import annotations

import json
import os
import queue
import ssl
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib import request as urllib_request

from ..http_identity import ensure_user_agent

DEFAULT_ENDPOINT = "https://api.smith.langchain.com"
DEFAULT_PROJECT = "ghost-chimera-hackathon"


# Run fields that can carry user/event data. Structural fields (id, name,
# run_type, timestamps, tags) are left alone.
_SCRUBBED_FIELDS = ("inputs", "outputs", "error", "metadata", "extra")


def _scrub_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact secrets and PII from run data before it leaves for LangSmith."""
    from ..redaction import redact_for_egress

    scrubbed = dict(payload)
    for field in _SCRUBBED_FIELDS:
        if field in scrubbed:
            scrubbed[field] = redact_for_egress(scrubbed[field])
    return scrubbed


_QUEUE_MAX = 256
_DEFAULT_TIMEOUT_S = 2.0


class _BackgroundSender:
    """One daemon thread that performs trace POSTs in FIFO order (create before close)."""

    def __init__(self) -> None:
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=_QUEUE_MAX)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.dropped = 0

    def submit(self, job: Any) -> bool:
        self._ensure_thread()
        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until queued posts are sent (tests / shutdown)."""
        done = threading.Event()
        if not self.submit(done.set):
            return False
        return done.wait(timeout)

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="ghost-langsmith", daemon=True)
                self._thread.start()

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                job()
            except Exception:
                pass  # observability only
            finally:
                self._queue.task_done()


_SENDER = _BackgroundSender()


def flush_traces(timeout: float = 5.0) -> bool:
    """Block until queued LangSmith posts have been attempted."""
    return _SENDER.flush(timeout)


def _timeout_s() -> float:
    try:
        return max(0.1, float(os.environ.get("LANGSMITH_TIMEOUT_S", "") or _DEFAULT_TIMEOUT_S))
    except ValueError:
        return _DEFAULT_TIMEOUT_S


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
        try:
            data = json.dumps(_scrub_payload(payload), default=str).encode("utf-8")
            req = urllib_request.Request(
                f"{self.config.endpoint}{path}", data=data, headers=self._headers(), method=method
            )
            opener = urllib_request.urlopen
        except Exception:
            return
        timeout = _timeout_s()

        def send() -> None:
            try:
                with opener(ensure_user_agent(req), timeout=timeout, context=ssl.create_default_context()):
                    pass
            except Exception:
                # Tracing is observability only; never let it break the caller.
                return

        # Off the caller's thread: a slow or unreachable LangSmith endpoint
        # must not add latency to the traced model call.
        _SENDER.submit(send)

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
