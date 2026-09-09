"""Phase 6 + OAuth + store tests: offline, deterministic, no secrets."""

from __future__ import annotations

import json
import os
import stat

import pytest

from ghostchimera.connectors import (
    OAUTH_PRESETS,
    GitHubEventConnector,
    TokenVault,
    get_preset,
    normalize_github_webhook,
    oauth_status,
)
from ghostchimera.connectors.oauth import (
    build_authorize_url,
    exchange_code,
    pkce_pair,
    refresh_access_token,
)
from ghostchimera.stealth import StealthLoop, StealthStore, new_event


# -- OAuth framework -------------------------------------------------------
def test_presets_cover_requested_providers() -> None:
    for provider in ("slack", "notion", "linkedin", "github", "google"):
        preset = get_preset(provider)
        assert preset.authorize_url.startswith("https://")
        assert preset.token_url.startswith("https://")
    with pytest.raises(ValueError):
        get_preset("myspace")


def test_pkce_s256_construction() -> None:
    import base64
    import hashlib

    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    _, challenge = pkce_pair(verifier=verifier)
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected
    assert "=" not in challenge  # unpadded url-safe, per RFC 7636
    v2, c2 = pkce_pair()
    assert len(v2) >= 43 and c2  # random verifier meets length rules


def test_authorize_url_per_provider() -> None:
    url = build_authorize_url(get_preset("slack"), client_id="cid", redirect_uri="http://localhost/cb",
                              state="s", challenge="c")
    assert url.startswith("https://slack.com/oauth/v2/authorize?")
    assert "code_challenge=c" in url and "state=s" in url
    url2 = build_authorize_url(get_preset("notion"), client_id="cid", redirect_uri="http://localhost/cb",
                               state="s", challenge="c")
    assert "owner=user" in url2


def test_token_exchange_and_refresh_with_fake_transport(monkeypatch) -> None:
    import ghostchimera.connectors.oauth as oauth_mod

    calls: list[str] = []

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=30.0):
        calls.append(req.full_url)
        if "refresh" in (req.data or b"").decode():
            return FakeResp({"access_token": "new-at", "expires_in": 3600})
        return FakeResp({"access_token": "at", "refresh_token": "rt", "expires_in": 3600})

    monkeypatch.setattr(oauth_mod.urllib.request, "urlopen", fake_urlopen)
    token = exchange_code(get_preset("slack"), client_id="c", client_secret="s",
                          code="code", redirect_uri="http://localhost/cb", verifier="v")
    assert token["access_token"] == "at" and token["refresh_token"] == "rt"
    assert token["expires_at"] > token["created_at"]
    refreshed = refresh_access_token(get_preset("slack"), client_id="c", client_secret="s",
                                     refresh_token="rt")
    assert refreshed["access_token"] == "new-at"
    assert refreshed["refresh_token"] == "rt"  # preserved when not rotated
    assert len(calls) == 2


def test_vault_round_trip_redaction_and_perms(tmp_path) -> None:
    vault = TokenVault(tmp_path)
    vault.save("slack", {"access_token": "xoxb-SECRET", "refresh_token": "r",
                         "expires_at": 9999999999.0})
    status = vault.status("slack")
    assert status["connected"] is True
    assert "xoxb-SECRET" not in json.dumps(status)  # never leak raw tokens
    assert vault.valid_token("slack") is not None
    path = tmp_path / "connector_oauth" / "slack.token.json"
    assert path.exists()
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert vault.revoke("slack") is True
    assert vault.status("slack")["connected"] is False
    assert oauth_status(tmp_path)["notion"]["connected"] is False


def test_expired_token_needs_refresh(tmp_path) -> None:
    vault = TokenVault(tmp_path)
    vault.save("github", {"access_token": "old", "expires_at": 1.0})
    assert vault.valid_token("github") is None
    assert vault.status("github")["expired"] is True


# -- GitHub connector --------------------------------------------------------
def _fake_github(path: str):
    if "/issues" in path:
        return [{"number": 7, "title": "Fix login", "action": "opened",
                 "user": {"login": "octocat"}, "updated_at": "2026-01-01"}]
    if "/pulls" in path:
        return [{"number": 8, "title": "Add feature", "action": "opened",
                 "user": {"login": "octocat"}, "merged": False}]
    if "/commits" in path:
        return [{"sha": "abc123def456", "commit": {"author": {"name": "octocat"},
                 "message": "fix: login"}}]
    return []


def test_github_poll_normalizes_and_dedups() -> None:
    connector = GitHubEventConnector("o/r", fetcher=_fake_github)
    assert connector.connect() is True
    seen: list = []
    assert connector.poll(seen.append) == 3
    types = {e.event_type for e in seen}
    assert {"github.issue_created", "github.pull_request_opened", "github.commit"} <= types
    assert all(e.source == "github" and e.confidence >= 0.9 for e in seen)
    # Second poll: same fake data -> all duplicates, zero delivered.
    assert connector.poll(seen.append) == 0
    assert len(seen) == 3


def test_github_poll_survives_endpoint_failure() -> None:
    def flaky(path: str):
        raise ConnectionError("api.github.com unavailable")

    connector = GitHubEventConnector("o/r", fetcher=flaky)
    connector.connect()
    assert connector.poll(lambda e: None) == 0
    assert connector.status == "connected"  # degraded, not dead


def test_github_webhook_mapping() -> None:
    push = normalize_github_webhook("push", "d1", {"after": "abc123", "ref": "refs/heads/main",
                                                   "sender": {"login": "octocat"},
                                                   "repository": {"full_name": "o/r"},
                                                   "commits": [{"message": "fix"}]})
    assert push is not None and push.event_type == "github.commit"
    assert push.event_id == "gh-webhook-d1"  # idempotent on delivery id
    issue = normalize_github_webhook("issues", "d2", {"action": "opened",
                                                     "sender": {"login": "octocat"},
                                                     "repository": {"full_name": "o/r"},
                                                     "issue": {"number": 1, "title": "t"}})
    assert issue is not None and issue.event_type == "github.issue_created"
    merged = normalize_github_webhook("pull_request", "d3", {"action": "closed",
                                                             "sender": {"login": "octocat"},
                                                             "repository": {"full_name": "o/r"},
                                                             "pull_request": {"number": 2, "title": "t",
                                                                              "merged": True}})
    assert merged is not None and merged.event_type == "github.pull_request_merged"
    assert normalize_github_webhook("ping", "d4", {}) is None


def test_connector_feeds_stealth_loop() -> None:
    loop = StealthLoop()
    try:
        connector = GitHubEventConnector("o/r", fetcher=_fake_github)
        assert connector.poll(loop.emit) == 3
        assert loop.bus.processed == 3
        assert loop.world.active_facts("octocat")
    finally:
        loop.close()


# -- StealthStore --------------------------------------------------------------
def test_store_journals_events_idempotently(tmp_path) -> None:
    store = StealthStore(tmp_path / "ghost.sqlite3")
    try:
        event = new_event("email.received", source="gmail", actor="alex", confidence=0.9)
        store.record_event(event)
        store.record_event(event)  # replay -> ignored by PK
        assert store.count_events() == 1
        recent = store.recent_events(event_type="email.received")
        assert len(recent) == 1 and recent[0]["actor"] == "alex"
        assert recent[0]["confidence"] == 0.9
    finally:
        store.close()


def test_store_tracks_useful_intervention_rate(tmp_path) -> None:
    store = StealthStore(tmp_path / "ghost.sqlite3")
    try:
        assert store.useful_intervention_rate() == 0.0
        store.record_outcome("i1", "proposal_prep", "useful")
        store.record_outcome("i2", "proposal_prep", "ignored")
        store.record_outcome("i3", "proposal_prep", "successful")
        assert store.useful_intervention_rate("proposal_prep") == pytest.approx(2 / 3)
        assert store.useful_intervention_rate("other") == 0.0
    finally:
        store.close()


def test_store_workflows_round_trip_and_loop_wiring(tmp_path) -> None:
    from ghostchimera.stealth import AutonomyLevel, GhostPolicy, InterventionOutcome

    store = StealthStore(tmp_path / "ghost.sqlite3")
    policy = GhostPolicy.conservative_default()
    policy.autonomy = AutonomyLevel.INJECT
    loop = StealthLoop(policy=policy, store=store)
    try:
        for _ in range(4):
            loop.emit(new_event("email.received", source="gmail", actor="alex",
                                payload={"relevance": 0.95, "confidence": 0.93, "benefit": 0.9},
                                confidence=0.93))
        assert store.count_events() == 4
        assert loop.sync_workflows() >= 1
        assert store.load_workflows()
        iid = next(iter(loop.interventions))
        import time
        from ghostchimera.stealth.intervention import InterventionState

        for _ in range(100):
            if loop.interventions[iid].state == InterventionState.READY:
                break
            time.sleep(0.05)
        loop.inject(iid, host="test")
        loop.observe_outcome(iid, InterventionOutcome.USEFUL)
        assert store.useful_intervention_rate() == 1.0
    finally:
        loop.close()
        store.close()
