from __future__ import annotations

import json
import ssl
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from ghostchimera.integrations import email_oauth


class EmailOAuthTests(unittest.TestCase):
    def test_status_redacts_token_presence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-email-oauth-") as tmp:
            token_path = Path(tmp) / "email_oauth" / "gmail.token.json"
            token_path.parent.mkdir(parents=True)
            token_path.write_text(
                json.dumps({"access_token": "gmail-secret", "refresh_token": "refresh-secret", "expires_at": 123.0}),
                encoding="utf-8",
            )

            status = email_oauth.email_oauth_status(tmp)

            serialized = json.dumps(status)
            self.assertTrue(status["ok"])
            self.assertNotIn("gmail-secret", serialized)
            self.assertNotIn("refresh-secret", serialized)
            gmail = next(item for item in status["providers"] if item["provider"] == "gmail")
            self.assertTrue(gmail["configured"])

    def test_start_requires_client_id_without_exposing_secret(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-email-oauth-") as tmp:
            with mock.patch.dict(email_oauth.os.environ, {}, clear=True):
                payload = email_oauth.start_email_oauth("gmail", tmp)

            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "needs_client_id")
            self.assertFalse(payload["policy"]["browser_cookies_read"])
            self.assertFalse(payload["policy"]["mail_client_stores_read"])

    def test_start_gmail_browser_oauth_builds_pkce_auth_url_without_exposing_verifier(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-email-oauth-") as tmp:
            with mock.patch.dict(email_oauth.os.environ, {"GMAIL_OAUTH_CLIENT_ID": "gmail-client"}, clear=True):
                payload = email_oauth.start_gmail_browser_oauth(
                    tmp,
                    "http://127.0.0.1:8766/api/console/email/oauth/browser/callback",
                )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["provider"], "gmail")
            self.assertEqual(payload["status"], "browser_authorization_pending")
            self.assertIn("https://accounts.google.com/o/oauth2/v2/auth?", payload["auth_url"])
            self.assertIn("code_challenge=", payload["auth_url"])
            self.assertNotIn("code_verifier", json.dumps(payload))
            pending_files = list((Path(tmp) / "email_oauth").glob("gmail-browser-*.pending.json"))
            self.assertEqual(len(pending_files), 1)
            pending = json.loads(pending_files[0].read_text(encoding="utf-8"))
            self.assertEqual(pending["client_id"], "gmail-client")
            self.assertIn("code_verifier", pending)

    def test_finish_gmail_browser_oauth_stores_token_write_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-email-oauth-") as tmp:
            with mock.patch.dict(email_oauth.os.environ, {"GMAIL_OAUTH_CLIENT_ID": "gmail-client"}, clear=True):
                start = email_oauth.start_gmail_browser_oauth(
                    tmp,
                    "http://127.0.0.1:8766/api/console/email/oauth/browser/callback",
                )
            with mock.patch.object(
                email_oauth,
                "_form_post",
                return_value={"access_token": "gmail-secret", "refresh_token": "refresh-secret", "expires_in": 3600},
            ):
                payload = email_oauth.finish_gmail_browser_oauth(tmp, start["state"], "auth-code")

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "connected")
            serialized = json.dumps(payload)
            self.assertNotIn("gmail-secret", serialized)
            self.assertNotIn("refresh-secret", serialized)
            token_file = Path(tmp) / "email_oauth" / "gmail.token.json"
            self.assertIn("gmail-secret", token_file.read_text(encoding="utf-8"))

    def test_finish_gmail_browser_oauth_includes_optional_client_secret_without_echoing_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-email-oauth-") as tmp:
            env = {
                "GMAIL_OAUTH_CLIENT_ID": "gmail-client",
                "GMAIL_OAUTH_CLIENT_SECRET": "gmail-client-secret",
            }
            with mock.patch.dict(email_oauth.os.environ, env, clear=True):
                start = email_oauth.start_gmail_browser_oauth(
                    tmp,
                    "http://127.0.0.1:8766/api/console/email/oauth/browser/callback",
                )
                with mock.patch.object(
                    email_oauth,
                    "_form_post",
                    return_value={"access_token": "gmail-secret", "expires_in": 3600},
                ) as post_mock:
                    payload = email_oauth.finish_gmail_browser_oauth(tmp, start["state"], "auth-code")

            self.assertTrue(payload["ok"])
            posted = post_mock.call_args.args[1]
            self.assertEqual(posted["client_secret"], "gmail-client-secret")
            self.assertNotIn("gmail-client-secret", json.dumps(payload))

    def test_finish_gmail_browser_oauth_rejects_unknown_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-email-oauth-") as tmp:
            payload = email_oauth.finish_gmail_browser_oauth(tmp, "missing-state", "auth-code")

            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "missing_pending_flow")

    def test_form_post_retries_certificate_errors_with_verified_certifi_context(self) -> None:
        class FakeResponse:
            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"ok": true}'

        calls: list[dict[str, object]] = []

        def fake_urlopen(request: object, *, timeout: float, context: object | None = None) -> FakeResponse:
            calls.append({"request": request, "timeout": timeout, "context": context})
            if len(calls) == 1:
                raise urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed"))
            return FakeResponse()

        with mock.patch.object(email_oauth.urllib.request, "urlopen", side_effect=fake_urlopen):
            payload = email_oauth._form_post("https://oauth2.googleapis.com/device/code", {"client_id": "client"})

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[0]["context"])
        self.assertIsInstance(calls[1]["context"], ssl.SSLContext)
        self.assertEqual(calls[1]["context"].verify_mode, ssl.CERT_REQUIRED)

    def test_form_post_uses_windows_store_after_certifi_certificate_failure(self) -> None:
        class FakeResponse:
            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"ok": true, "source": "windows"}'

        certifi_context = ssl.create_default_context()
        windows_context = ssl.create_default_context()
        calls: list[object | None] = []

        def fake_urlopen(request: object, *, timeout: float, context: object | None = None) -> FakeResponse:
            calls.append(context)
            if context is not windows_context:
                raise urllib.error.URLError(
                    ssl.SSLCertVerificationError("unable to get local issuer certificate")
                )
            return FakeResponse()

        with (
            mock.patch.object(email_oauth, "_certifi_ssl_context", return_value=certifi_context),
            mock.patch.object(email_oauth, "_windows_ssl_context", return_value=windows_context),
            mock.patch.object(email_oauth.urllib.request, "urlopen", side_effect=fake_urlopen),
        ):
            payload = email_oauth._form_post("https://oauth2.googleapis.com/device/code", {"client_id": "client"})

        self.assertEqual(payload["source"], "windows")
        self.assertEqual(calls, [None, certifi_context, windows_context])
        self.assertEqual(windows_context.verify_mode, ssl.CERT_REQUIRED)

    def test_form_post_uses_powershell_fallback_without_command_line_secrets(self) -> None:
        certifi_context = ssl.create_default_context()
        windows_context = ssl.create_default_context()

        def fake_urlopen(_request: object, *, timeout: float, context: object | None = None) -> object:
            raise urllib.error.URLError(ssl.SSLCertVerificationError("Basic Constraints of CA cert not marked critical"))

        completed = subprocess.CompletedProcess(
            args=["powershell"],
            returncode=0,
            stdout='{"ok": true, "source": "powershell"}',
            stderr="",
        )

        with (
            mock.patch.object(email_oauth, "_certifi_ssl_context", return_value=certifi_context),
            mock.patch.object(email_oauth, "_windows_ssl_context", return_value=windows_context),
            mock.patch.object(email_oauth.urllib.request, "urlopen", side_effect=fake_urlopen),
            mock.patch.object(email_oauth.subprocess, "run", return_value=completed) as run_mock,
            mock.patch.object(email_oauth.os, "name", "nt"),
        ):
            payload = email_oauth._form_post(
                "https://oauth2.googleapis.com/device/code",
                {"client_id": "client-secretish-value"},
            )

        self.assertEqual(payload["source"], "powershell")
        args = run_mock.call_args.args[0]
        self.assertNotIn("client-secretish-value", " ".join(args))
        self.assertIn("client-secretish-value", run_mock.call_args.kwargs["input"])

    def test_poll_stores_token_write_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-email-oauth-") as tmp:
            pending_id = "gmail-123"
            pending = {
                "provider": "gmail",
                "pending_id": pending_id,
                "client_id": "client-id",
                "device_code": "device-code",
                "created_at": email_oauth.time.time(),
                "expires_in": 900,
            }
            path = Path(tmp) / "email_oauth" / f"gmail-{pending_id}.pending.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(pending), encoding="utf-8")
            with mock.patch.object(
                email_oauth,
                "_form_post",
                return_value={"access_token": "gmail-secret", "refresh_token": "refresh-secret", "expires_in": 3600},
            ):
                payload = email_oauth.poll_email_oauth("gmail", tmp, pending_id)

            self.assertTrue(payload["ok"])
            serialized = json.dumps(payload)
            self.assertNotIn("gmail-secret", serialized)
            token_file = Path(tmp) / "email_oauth" / "gmail.token.json"
            self.assertIn("gmail-secret", token_file.read_text(encoding="utf-8"))

    def test_crawl_gmail_adds_memory_and_dataset(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-email-oauth-") as tmp:
            token_path = Path(tmp) / "email_oauth" / "gmail.token.json"
            token_path.parent.mkdir(parents=True)
            token_path.write_text(json.dumps({"access_token": "gmail-secret"}), encoding="utf-8")

            def fake_get(url: str, token: str) -> dict:
                self.assertEqual(token, "gmail-secret")
                if url.startswith(email_oauth.GMAIL_MESSAGES_ENDPOINT + "?"):
                    return {"messages": [{"id": "m1"}]}
                return {
                    "id": "m1",
                    "snippet": "body preview",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Hello"},
                            {"name": "From", "value": "sender@example.com"},
                            {"name": "Date", "value": "today"},
                        ]
                    },
                }

            with mock.patch.object(email_oauth, "_json_get", side_effect=fake_get):
                result = email_oauth.crawl_email_provider(
                    "gmail",
                    tmp,
                    memory_db=Path(tmp) / "memory.sqlite3",
                    max_messages=1,
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["ingested"], 1)
            self.assertEqual(result["dataset_records"], 1)
            self.assertNotIn("gmail-secret", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
