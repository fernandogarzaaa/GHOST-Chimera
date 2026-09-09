"""Agent-output pipeline + unified webhooks + secret-leak guard tests."""

from __future__ import annotations

import json
from pathlib import Path

from ghostchimera.stealth import (
    AutonomyLevel,
    GhostPolicy,
    InterventionOutcome,
    InterventionState,
    StealthLoop,
)


def _auto_output(summary="Client asks to reschedule.", conf=0.95) -> str:
    return json.dumps({
        "event_summary": summary, "confidence_score": conf,
        "action_type": "AUTONOMOUS_EXECUTE",
        "actions": [{"provider": "slack", "endpoint": "/chat.postMessage",
                     "payload": {"channel": "#ops", "text": "Done."}}]})


def _draft_output() -> str:
    return json.dumps({
        "event_summary": "Angry escalation, needs human.", "confidence_score": 0.6,
        "action_type": "DRAFT_FOR_APPROVAL",
        "actions": [{"provider": "google-mail", "endpoint": "/users/me/messages/send",
                     "payload": {"to": "c@example.com", "body": "Draft reply"}}]})


def test_handle_agent_output_downgrades_execute_to_ask_at_l1() -> None:
    loop = StealthLoop(policy=GhostPolicy(autonomy=AutonomyLevel.PREPARE))
    try:
        result = loop.handle_agent_output(_auto_output())
        assert result["ok"] is True and result["decision"] == "ask"
        intervention = loop.interventions[result["intervention_id"]]
        assert intervention.state == InterventionState.QUEUED
        assert intervention.provenance.get("needs_approval") is True
    finally:
        loop.close()


def test_handle_agent_output_prepares_draft() -> None:
    loop = StealthLoop(policy=GhostPolicy(autonomy=AutonomyLevel.PREPARE))
    try:
        result = loop.handle_agent_output(_draft_output())
        assert result["decision"] == "prepare"
        intervention = loop.interventions[result["intervention_id"]]
        assert intervention.state == InterventionState.READY
        assert intervention.context["draft"][0]["provider"] == "google-mail"
    finally:
        loop.close()


def test_handle_agent_output_executes_at_l3_with_executor() -> None:
    loop = StealthLoop(policy=GhostPolicy(autonomy=AutonomyLevel.ACT))
    calls: list = []

    def fake_executor(action: dict, connection_id: str) -> dict:
        calls.append((action["provider"], connection_id))
        return {"ok": True, "ts": "1"}

    try:
        result = loop.handle_agent_output(_auto_output(), connection_map={"slack": "va_1"},
                                          executor=fake_executor)
        assert result["decision"] == "act"
        assert calls == [("slack", "va_1")]
        intervention = loop.interventions[result["intervention_id"]]
        assert intervention.state == InterventionState.OUTCOME
        assert intervention.outcome == InterventionOutcome.SUCCESSFUL
    finally:
        loop.close()


def test_handle_agent_output_executor_failure_marks_failed() -> None:
    loop = StealthLoop(policy=GhostPolicy(autonomy=AutonomyLevel.ACT))

    def boom(action: dict, connection_id: str) -> dict:
        raise RuntimeError("slack unavailable")

    try:
        result = loop.handle_agent_output(_auto_output(), executor=boom)
        assert result["decision"] == "act"
        assert result["executed"][0]["ok"] is False
        intervention = loop.interventions[result["intervention_id"]]
        assert intervention.outcome == InterventionOutcome.FAILED
    finally:
        loop.close()


def test_handle_agent_output_rejects_malformed() -> None:
    loop = StealthLoop()
    try:
        assert loop.handle_agent_output("not json")["ok"] is False
        idle = json.dumps({"event_summary": "nothing", "confidence_score": 0.1,
                           "action_type": "NO_ACTION_NEEDED"})
        result = loop.handle_agent_output(idle)
        assert result == {"ok": True, "decision": "none", "intervention_id": ""}
        assert loop.interventions == {}
    finally:
        loop.close()


def test_unified_webhooks_feed_loop() -> None:
    from ghostchimera.connectors import normalize_webhook

    loop = StealthLoop()
    try:
        delivered = 0
        for source, did, va, payload in [
            ("slack", "d1", "va-1", {"event": {"type": "message", "user": "U1",
                                               "text": "help", "channel": "C1", "ts": "1"}}),
            ("gmail", "d2", "va-1", {"id": "m1", "payload": {"headers": [
                {"name": "From", "value": "c@example.com"},
                {"name": "Subject", "value": "Hi"}]}}),
            ("slack", "d0", "va-1", {"type": "url_verification"}),
        ]:
            event = normalize_webhook(source, did, va, payload)
            if event is not None and loop.emit(event):
                delivered += 1
        assert delivered == 2  # ping acked, not learned
        assert loop.bus.processed == 2
    finally:
        loop.close()


def test_no_live_secrets_in_repo() -> None:
    """Regression guard: real provider keys must never land in the tree.

    Matches realistic key shapes only (docs use `sk-ant-...` placeholders
    and tests use short fixtures like `xoxb-SECRET`, both excluded by the
    minimum-length classes below).
    """
    import re

    key_shapes = (
        re.compile(r"sk-or-v1-[A-Za-z0-9]{16,}"),  # OpenRouter (real: 64 hex)
        re.compile(r"sk-ant-(?![.x]*['\"\s]|test)[A-Za-z0-9\-_]{8,}"),  # Anthropic
        re.compile(r"xox[bpas]-[A-Za-z0-9\-]{20,}"),  # Slack
        re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),  # GitHub
        re.compile(r"sk-(?!ant-|or-v1-)[A-Za-z0-9]{20,}"),  # OpenAI legacy
    )
    # Fixture markers: synthetic DPI/test keys always carry one of these.
    # Sequential runs need BOTH an alpha and a digit triple (e.g. abc..123);
    # a lone triple in a 60+ char random key is plausible, both is not.
    synthetic = re.compile(r"abcdef|123456|SECRET|secret-|test|xxx|\.\.\.|placeholder|EXAMPLE",
                           re.IGNORECASE)
    seq_alpha = re.compile(r"abc|bcd|cde|def|xyz|stu", re.IGNORECASE)
    seq_digit = re.compile(r"123|234|345|456|789|901")
    repo = Path(__file__).resolve().parents[1]
    hits: list[str] = []
    skip_dirs = {".git", "__pycache__", ".pytest_cache", "node_modules"}
    skip_files = {"test_agent_actions.py"}  # this module holds pattern literals, not keys
    for path in repo.rglob("*"):
        if not path.is_file() or path.name in skip_files:
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix not in {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".js",
                               ".html", ".css", ".txt", ".example"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError):
            continue
        for shape in key_shapes:
            for match in shape.finditer(text):
                candidate = match.group(0)
                if synthetic.search(candidate):
                    continue
                if seq_alpha.search(candidate) and seq_digit.search(candidate):
                    continue  # sequential fixture stems, not a random key
                hits.append(f"{path.name}:{candidate[:16]}…")
    assert hits == [], f"possible live secrets in repo: {hits[:5]}"
