"""F10: OAuth refresh tokens and remote-control bot tokens are owner-only.

Before the fix they were written with Path.write_text under a plain mkdir,
i.e. 0644 files in a 0755 dir under the default umask.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest import mock

import pytest

from ghostchimera.integrations import email_oauth
from ghostchimera.integrations.remote_control import RemoteControlStore
from ghostchimera.model_layer import provider_oauth_connectors

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")

TOKEN = {"access_token": "gmail-secret", "refresh_token": "refresh-secret", "expires_in": 3600}


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def loose_umask():  # type: ignore[no-untyped-def]
    old = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(old)


def test_gmail_browser_token_is_0600_in_0700_dir(tmp_path: Path, loose_umask: None) -> None:
    with mock.patch.dict(email_oauth.os.environ, {"GMAIL_OAUTH_CLIENT_ID": "gmail-client"}, clear=True):
        start = email_oauth.start_gmail_browser_oauth(tmp_path, "http://127.0.0.1:8766/cb")
    pending = list((tmp_path / "email_oauth").glob("*.json"))
    assert pending and all(_mode(p) == 0o600 for p in pending)
    with mock.patch.object(email_oauth, "_form_post", return_value=TOKEN):
        assert email_oauth.finish_gmail_browser_oauth(tmp_path, start["state"], "code")["ok"]
    token_file = tmp_path / "email_oauth" / "gmail.token.json"
    assert "refresh-secret" in token_file.read_text()
    assert _mode(token_file) == 0o600
    assert _mode(token_file.parent) == 0o700


def test_device_flow_token_is_0600(tmp_path: Path, loose_umask: None) -> None:
    pending_id = "gmail-123"
    oauth_dir = tmp_path / "email_oauth"
    oauth_dir.mkdir(mode=0o755)
    pending_file = oauth_dir / f"gmail-{pending_id}.pending.json"
    pending_file.write_text(
        json.dumps(
            {
                "provider": "gmail",
                "pending_id": pending_id,
                "client_id": "c",
                "device_code": "d",
                "created_at": email_oauth.time.time(),
                "expires_in": 900,
            }
        )
    )
    with mock.patch.object(email_oauth, "_form_post", return_value=TOKEN):
        assert email_oauth.poll_email_oauth("gmail", tmp_path, pending_id)["ok"]
    token_file = oauth_dir / "gmail.token.json"
    assert _mode(token_file) == 0o600
    assert _mode(oauth_dir) == 0o700


def test_remote_control_secrets_are_0600(tmp_path: Path, loose_umask: None) -> None:
    store = RemoteControlStore(tmp_path)
    store.configure_channel("telegram", {"bot_token": "telegram-secret-token", "send_enabled": True})
    secrets_file = tmp_path / "remote_control_secrets.json"
    assert "telegram-secret-token" in secrets_file.read_text()
    assert _mode(secrets_file) == 0o600
    assert _mode(tmp_path) == 0o700


def test_provider_oauth_pending_dir_is_private(tmp_path: Path, loose_umask: None) -> None:
    oauth_dir = provider_oauth_connectors._oauth_dir(tmp_path)
    assert _mode(oauth_dir) == 0o700
