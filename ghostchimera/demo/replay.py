"""Offline replay of a Nemotron-enhanced Stealth Loop session (``ghost demo``).

The demo drives the real :class:`~ghostchimera.stealth.StealthLoop` and the
real :class:`~ghostchimera.stealth.nemotron_reasoning.NemotronReasoner`, but
swaps the Nebius Token Factory HTTP provider for a *replay* provider that
answers from a session fixture shipped inside the package. No API keys are
read and every outbound (non-loopback) socket connection is refused while it runs, so it
works on a plane.

``ghost demo --record out.json`` does the opposite: with ``NEBIUS_API_KEY``
set it sends the same events to live Nemotron models and saves their raw
replies as a new session file that ``ghost demo --session out.json`` replays.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import re
import socket
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, TextIO

SESSION_FORMAT = "ghostchimera.demo.session/v1"
DEFAULT_SESSION = "nemotron_session.json"

_EVENT_TYPE_RE = re.compile(r"^event_type:\s*(\S+)", re.MULTILINE)


class OfflineNetworkError(OSError):
    """Raised if anything tries to open a network connection during replay."""


# ---------------------------------------------------------------------------
# Session loading
# ---------------------------------------------------------------------------


def load_session(path: str | Path | None = None) -> dict[str, Any]:
    """Load a session file, or the fixture bundled with the package."""
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files("ghostchimera.demo").joinpath("fixtures", DEFAULT_SESSION).read_text(encoding="utf-8")
    data = json.loads(text)
    if data.get("format") != SESSION_FORMAT:
        raise ValueError(f"unsupported demo session format: {data.get('format')!r}")
    if not isinstance(data.get("events"), list) or not data["events"]:
        raise ValueError("demo session has no events")
    return data


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class ReplayProvider:
    """Stands in for the Nebius provider and answers from recorded replies."""

    api_key = ""

    def __init__(self, session: dict[str, Any], *, model: str, role: str) -> None:
        self.available = True
        self.model = model
        self._role = role
        self._understand = {str(e["event_type"]).lower(): e.get("understand") for e in session["events"]}
        self._predict = session.get("predict")
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        if self._role == "predict":
            if not self._predict:
                raise LookupError("session has no recorded PREDICT reply")
            return str(self._predict)
        match = _EVENT_TYPE_RE.search(user)
        reply = self._understand.get(match.group(1).lower()) if match else None
        if not reply:
            raise LookupError("no recorded UNDERSTAND reply for this event")
        return str(reply)


class RecordingProvider:
    """Wraps a live provider and keeps every raw reply for the session file."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.replies: list[str] = []
        self.by_event_type: dict[str, str] = {}
        self.errors: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def chat(self, system: str, user: str, **options: Any) -> str:
        from ..stealth.nemotron_reasoning import call_provider

        # Forward per-call options (thinking off, max_tokens, timeout) so a
        # recording exercises the same request shape as the live loop.
        try:
            reply = call_provider(self._inner, system, user, **options)
        except Exception as exc:
            self.errors.append(f"{type(exc).__name__}: {exc}")
            raise
        self.replies.append(reply)
        match = _EVENT_TYPE_RE.search(user)
        if match:
            self.by_event_type.setdefault(match.group(1).lower(), reply)
        return reply


# ---------------------------------------------------------------------------
# Network guard
# ---------------------------------------------------------------------------


def _is_loopback(address: Any) -> bool:
    """True for local-only endpoints (loopback IPs, ``localhost``, AF_UNIX paths)."""
    if isinstance(address, (str, bytes)):
        return True  # AF_UNIX socket path: never leaves the machine
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host).split("%", 1)[0]  # strip an IPv6 zone id
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@contextlib.contextmanager
def no_network() -> Iterator[None]:
    """Refuse every outbound (non-loopback) socket connection for the block.

    Loopback stays open on purpose: on Windows ``socket.socketpair()`` (used by
    asyncio's self-pipe) is emulated with a connect to 127.0.0.1, and blocking
    that would break the loop without protecting anything.
    """
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection

    def _refuse() -> OfflineNetworkError:
        return OfflineNetworkError("ghost demo runs offline; network access is disabled")

    def _connect(self: socket.socket, address: Any) -> Any:
        if not _is_loopback(address):
            raise _refuse()
        return original_connect(self, address)

    def _connect_ex(self: socket.socket, address: Any) -> Any:
        if not _is_loopback(address):
            raise _refuse()
        return original_connect_ex(self, address)

    def _create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_loopback(address):
            raise _refuse()
        return original_create_connection(address, *args, **kwargs)

    socket.socket.connect = _connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _connect_ex  # type: ignore[method-assign]
    socket.create_connection = _create_connection  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]
        socket.create_connection = original_create_connection  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Running a session through the real loop
# ---------------------------------------------------------------------------


@dataclass
class DemoStep:
    event_type: str
    source: str
    decision: str
    understand: dict[str, Any] | None
    local_predictions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DemoResult:
    title: str
    provenance: str
    provenance_note: str
    models: dict[str, str]
    steps: list[DemoStep]
    predictions: list[dict[str, Any]] | None
    predict_source: str
    elapsed_s: float
    seeded_workflows: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "provenance": self.provenance,
            "provenance_note": self.provenance_note,
            "models": dict(self.models),
            "steps": [step.__dict__ for step in self.steps],
            "predictions": self.predictions,
            "predict_source": self.predict_source,
            "elapsed_s": round(self.elapsed_s, 3),
            "seeded_workflows": list(self.seeded_workflows),
        }


def _run_through_loop(
    session: dict[str, Any], reasoner: Any, progress: Any | None = None
) -> tuple[list[DemoStep], Any, list[str], list[str]]:
    from ..stealth import StealthLoop, new_event
    from ..stealth.loop import _compact_event_descriptor

    # Sync cloud mode: replay must be deterministic and record must capture
    # every reply in order.
    loop = StealthLoop(reasoner=reasoner, own_runtime=False, cloud_mode="sync")
    # The demo shows a loop that has already learned how this user works (the
    # product's claim), not a blank one: pre-register the session's learned
    # workflows so MATCH WORKFLOW fires and decisions vary by situation.
    seeded: list[str] = []
    for spec in session.get("seed_workflows") or []:
        name = str(spec.get("name") or "seeded")
        pattern = [str(part) for part in spec.get("pattern") or []]
        if len(pattern) >= 2:
            loop.learner.register_explicit(name, pattern, [str(part) for part in spec.get("expected_next") or []])
            seeded.append(name)
    steps: list[DemoStep] = []
    history: list[str] = []
    session_id = str(session.get("session_id") or "demo-session")
    try:
        for spec in session["events"]:
            event = new_event(
                str(spec["event_type"]),
                source=str(spec.get("source") or "demo"),
                payload=dict(spec.get("payload") or {}),
                session_id=session_id,
            )
            # Enriched descriptors (not bare type names) so PREDICT can name
            # the entities its predictions must reference.
            history.append(_compact_event_descriptor(event))
            started = time.perf_counter()
            loop.emit(event)
            result = loop.last_result
            if progress is not None:
                trace = result.trace if result is not None else {}
                progress(len(history), len(session["events"]), event.event_type, time.perf_counter() - started, trace)
            trace = result.trace if result is not None else {}
            steps.append(
                DemoStep(
                    event_type=event.event_type,
                    source=event.source,
                    decision=str(getattr(getattr(result, "decision", None), "value", "none")),
                    understand=trace.get("nemotron") if isinstance(trace, dict) else None,
                    local_predictions=list(getattr(result, "predictions", []) or []),
                )
            )
        last = loop.last_result
    finally:
        loop.close()
    return steps, last, history, seeded


def _predict_step(reasoner: Any, last: Any, history: list[str], steps: list[DemoStep]) -> tuple[Any, str]:
    trace = getattr(last, "trace", None) or {}
    in_loop = trace.get("nemotron_predictions") if isinstance(trace, dict) else None
    if in_loop:
        return in_loop, "stealth-loop"
    workflow = next((s.understand.get("suggested_workflow", "") for s in reversed(steps) if s.understand), "")
    return reasoner.predict_next("\n".join(history), hypothesis=str(workflow or "")), "reasoner"


def replay(session_path: str | Path | None = None) -> DemoResult:
    """Replay a session offline through the real Stealth Loop."""
    from ..stealth.nemotron_reasoning import NANO_MODEL, SUPER_MODEL, NemotronReasoner

    session = load_session(session_path)
    models = {"understand": NANO_MODEL, "predict": SUPER_MODEL, **dict(session.get("models") or {})}
    started = time.perf_counter()
    with no_network():
        reasoner = NemotronReasoner(
            provider=ReplayProvider(session, model=models["understand"], role="understand"),
            reasoning_provider=ReplayProvider(session, model=models["predict"], role="predict"),
            reasoning_model=models["predict"],
        )
        steps, last, history, seeded = _run_through_loop(session, reasoner)
        predictions, predict_source = _predict_step(reasoner, last, history, steps)
    return DemoResult(
        title=str(session.get("title") or "Ghost Chimera demo"),
        provenance=str(session.get("provenance") or "unknown"),
        provenance_note=str(session.get("provenance_note") or ""),
        models=models,
        steps=steps,
        predictions=predictions,
        predict_source=predict_source,
        elapsed_s=time.perf_counter() - started,
        seeded_workflows=seeded,
    )


def _check_output_path(output: str | Path) -> Path:
    """Fail before any paid call if the recording cannot be written."""
    out = Path(output).expanduser()
    if out.exists() and out.is_dir():
        raise OSError(f"--record path {out} is a directory; give a file name such as session.json")
    parent = out.parent if str(out.parent) else Path(".")
    if not parent.exists():
        raise OSError(f"--record directory {parent} does not exist")
    if not os.access(parent, os.W_OK):
        raise OSError(f"--record directory {parent} is not writable")
    return out


def _stderr_progress(index: int, total: int, event_type: str, elapsed: float, trace: dict[str, Any]) -> None:
    status = "ok" if isinstance(trace, dict) and trace.get("nemotron") else "no reply"
    print(f"  [{index}/{total}] UNDERSTAND {event_type}  {elapsed:.1f}s  {status}", file=sys.stderr, flush=True)


def record(
    output: str | Path,
    session_path: str | Path | None = None,
    *,
    progress: Any | None = None,
) -> Path:
    """Run the session's events against live Nemotron and save the replies.

    Raises ``RuntimeError`` (and writes nothing) when any live call failed,
    so a recording never silently replays as "no cloud insight".
    """
    from ..stealth.nemotron_reasoning import SUPER_MODEL, NemotronReasoner

    if not os.environ.get("NEBIUS_API_KEY", "").strip():
        raise RuntimeError("recording needs NEBIUS_API_KEY (Nemotron on Nebius Token Factory)")
    out = _check_output_path(output)
    template = load_session(session_path)
    live = NemotronReasoner()
    if not live.available:
        raise RuntimeError("NEBIUS_API_KEY is set but the Nebius provider is unavailable")
    understand = RecordingProvider(live.provider)
    reasoning_inner = live._reasoning_provider_instance()
    if reasoning_inner is None:
        raise RuntimeError("could not create the Nemotron 3 Super reasoning provider")
    predict = RecordingProvider(reasoning_inner)
    reasoner = NemotronReasoner(provider=understand, reasoning_provider=predict, reasoning_model=SUPER_MODEL)

    steps, _last, history, _seeded = _run_through_loop(template, reasoner, progress)
    missing = [
        str(spec["event_type"])
        for spec in template["events"]
        if not understand.by_event_type.get(str(spec["event_type"]).lower())
    ]
    if missing:
        detail = understand.errors[-1] if understand.errors else "the reply was not usable JSON"
        raise RuntimeError(
            f"live UNDERSTAND failed for {len(missing)}/{len(template['events'])} events "
            f"({', '.join(missing)}): {detail}. Nothing was written."
        )
    # PREDICT for the whole session. The in-loop PREDICT is rate-limited per
    # stream, so it only ever saw the first event; replay serves this reply as
    # the session's final prediction, so it must cover the full history.
    workflow = next(
        (s.understand.get("suggested_workflow", "") for s in reversed(steps) if s.understand),
        "",
    )
    started = time.perf_counter()
    replies_before = len(predict.replies)
    final = reasoner.predict_next("\n".join(history), hypothesis=str(workflow or ""))
    if progress is not None:
        print(
            f"  PREDICT (whole session)  {time.perf_counter() - started:.1f}s  {'ok' if final else 'no reply'}",
            file=sys.stderr,
            flush=True,
        )
    if not final or len(predict.replies) <= replies_before:
        detail = predict.errors[-1] if predict.errors else "the reply was not usable JSON"
        raise RuntimeError(f"live PREDICT failed: {detail}. Nothing was written.")
    recorded_events = [
        {**spec, "understand": understand.by_event_type.get(str(spec["event_type"]).lower())}
        for spec in template["events"]
    ]
    session = {
        **template,
        "provenance": "recorded",
        "provenance_note": (
            f"Recorded live from Nebius Token Factory on {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} "
            "with `ghost demo --record`."
        ),
        "models": {
            "understand": str(getattr(understand, "model", "")),
            "predict": SUPER_MODEL,
        },
        "events": recorded_events,
        "predict": predict.replies[-1],
    }
    out.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_text(result: DemoResult, stream: TextIO | None = None) -> None:
    out = stream or sys.stdout

    def say(line: str = "") -> None:
        print(line, file=out)

    say(f"Ghost Chimera demo: {result.title}")
    say(f"Replaying a Nemotron session ({result.provenance}) offline: no API keys, network disabled.")
    say(f"  UNDERSTAND: {result.models['understand']}")
    say(f"  PREDICT:    {result.models['predict']}")
    if result.seeded_workflows:
        say(f"  LEARNED:    {', '.join(result.seeded_workflows)} (workflows this loop already knows)")
    say()
    for index, step in enumerate(result.steps, 1):
        say(f"[{index}] {step.event_type}  (from {step.source})")
        insight = step.understand
        if insight:
            flags = ", ".join(insight.get("risk_flags") or []) or "none"
            say(
                f"    UNDERSTAND -> intent={insight.get('intent')}  confidence={insight.get('confidence')}  "
                f"workflow={insight.get('suggested_workflow') or '-'}  risk={flags}"
            )
            if insight.get("rationale"):
                say(f"                  {insight['rationale']}")
        else:
            say("    UNDERSTAND -> (no cloud insight; local loop only)")
        say(f"    DECIDE     -> {step.decision}")
    say()
    where = "inside the Stealth Loop" if result.predict_source == "stealth-loop" else "via NemotronReasoner"
    say(f"PREDICT (Nemotron 3 Super, {where}): most likely next actions")
    if result.predictions:
        for pred in result.predictions:
            say(f"  {float(pred.get('probability', 0.0)):.0%}  {pred.get('action')}  - {pred.get('rationale', '')}")
    else:
        say("  (no prediction in this session)")
    say()
    if result.provenance_note:
        say(f"Note: {result.provenance_note}")
    say(
        "Run it live: export NEBIUS_API_KEY=...  (https://console.nebius.com), then `ghost demo --record session.json`."
    )


def run_demo_cli(*, session: str = "", as_json: bool = False, record_to: str = "", stream: TextIO | None = None) -> int:
    out = stream or sys.stdout
    try:
        if record_to:
            print(
                "Recording a live Nemotron session (UNDERSTAND per event, then PREDICT)...",
                file=sys.stderr,
                flush=True,
            )
            path = record(record_to, session or None, progress=_stderr_progress)
            print(f"Recorded live Nemotron session to {path}. Replay it with: ghost demo --session {path}", file=out)
            return 0
        result = replay(session or None)
    except (OSError, ValueError, RuntimeError, LookupError) as exc:
        print(f"ghost demo: {exc}", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True), file=out)
    else:
        render_text(result, out)
    return 0


__all__ = [
    "DemoResult",
    "DemoStep",
    "OfflineNetworkError",
    "RecordingProvider",
    "ReplayProvider",
    "load_session",
    "no_network",
    "record",
    "render_text",
    "replay",
    "run_demo_cli",
]
