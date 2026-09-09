from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.cli import _main
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.integrations.remote_control import (
    RemoteControlStore,
    build_outbound_reply,
    normalize_remote_payload,
    verify_remote_webhook_signature,
    verify_whatsapp_webhook_challenge,
)


class RemoteControlStoreTests(unittest.TestCase):
    def test_outbound_reply_builder_formats_provider_payloads_without_tokens(self) -> None:
        telegram = build_outbound_reply("telegram", "42", "Ghost ready")
        discord = build_outbound_reply("discord", "channel-1", "Ghost ready")
        slack = build_outbound_reply("slack", "C123", "Ghost ready")
        whatsapp = build_outbound_reply("whatsapp", "15551234567", "Ghost ready")
        webhook = build_outbound_reply("webhook", "peer", "Ghost ready")

        self.assertEqual(telegram.body, {"chat_id": "42", "text": "Ghost ready"})
        self.assertIn("<TOKEN>", telegram.endpoint_hint)
        self.assertNotIn("secret", json.dumps(telegram.to_dict()).lower())
        self.assertEqual(discord.body, {"content": "Ghost ready"})
        self.assertEqual(slack.body, {"channel": "C123", "text": "Ghost ready"})
        self.assertEqual(whatsapp.body["text"]["body"], "Ghost ready")
        self.assertFalse(webhook.auth_required)

    def test_provider_payload_normalization_supports_common_mobile_channels(self) -> None:
        telegram = normalize_remote_payload(
            "telegram",
            {
                "message": {
                    "chat": {"id": 42},
                    "from": {"id": 7, "first_name": "Admin"},
                    "text": "/status",
                }
            },
        )
        discord = normalize_remote_payload(
            "discord",
            {"channel_id": "discord-channel", "author": {"id": "user-1", "username": "Admin"}, "content": "/jobs"},
        )
        slack = normalize_remote_payload(
            "slack",
            {"event": {"channel": "C123", "user": "U123", "text": "/paths"}},
        )
        whatsapp = normalize_remote_payload(
            "whatsapp",
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [{"from": "15551234567", "text": {"body": "/readiness"}}],
                                    "contacts": [{"wa_id": "15551234567", "profile": {"name": "Admin"}}],
                                }
                            }
                        ]
                    }
                ]
            },
        )
        signal = normalize_remote_payload(
            "signal",
            {"envelope": {"source": "+15551234567", "sourceName": "Admin", "dataMessage": {"message": "/stop"}}},
        )

        self.assertEqual((telegram.channel, telegram.peer_id, telegram.text), ("telegram", "42", "/status"))
        self.assertEqual((discord.channel, discord.peer_id, discord.text), ("discord", "discord-channel", "/jobs"))
        self.assertEqual((slack.channel, slack.peer_id, slack.text), ("slack", "C123", "/paths"))
        self.assertEqual((whatsapp.channel, whatsapp.peer_id, whatsapp.text), ("whatsapp", "15551234567", "/readiness"))
        self.assertEqual((signal.channel, signal.peer_id, signal.text), ("signal", "+15551234567", "/stop"))

    def test_channel_configuration_is_write_only_and_send_toggle_requires_credentials(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-config-") as tmp:
            store = RemoteControlStore(tmp)
            configured = store.configure_channel(
                "telegram",
                {
                    "bot_token": "telegram-secret-token",
                    "webhook_url": "https://example.test/hook",
                    "send_enabled": True,
                    "default_reply_target": "operator-chat",
                },
            )

            self.assertTrue(configured["ok"])
            self.assertTrue(configured["channel"]["configured"])
            self.assertTrue(configured["channel"]["send_enabled"])
            self.assertEqual(configured["channel"]["secret_fields_configured"], ["bot_token", "webhook_url"])
            self.assertNotIn("telegram-secret-token", json.dumps(configured))
            status = store.status()
            telegram = next(channel for channel in status["channels"] if channel["id"] == "telegram")
            self.assertTrue(telegram["configured"])
            self.assertTrue(telegram["send_enabled"])
            self.assertEqual(telegram["default_reply_target"], "operator-chat")
            self.assertNotIn("telegram-secret-token", json.dumps(status))

            cleared = store.configure_channel("telegram", {"clear_secrets": True, "send_enabled": True})
            self.assertFalse(cleared["channel"]["configured"])
            self.assertFalse(cleared["channel"]["send_enabled"])

    def test_send_reply_can_use_configured_default_recipient(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-default-recipient-") as tmp:
            store = RemoteControlStore(tmp)
            store.configure_channel(
                "telegram",
                {"bot_token": "telegram-secret-token", "send_enabled": True, "default_reply_target": "operator-chat"},
            )
            captured: dict[str, object] = {}

            def fake_transport(endpoint: str, headers: dict[str, str], body: dict[str, object]) -> dict[str, object]:
                captured["body"] = body
                return {"ok": True, "status": 200}

            sent = store.send_reply(channel="telegram", reply_target="", text="hello", transport=fake_transport)

            self.assertTrue(sent["ok"])
            self.assertEqual(captured["body"], {"chat_id": "operator-chat", "text": "hello"})
            self.assertEqual(sent["reply_preview"]["reply_target"], "operator-chat")

    def test_send_reply_is_gated_and_does_not_return_secrets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-send-") as tmp:
            store = RemoteControlStore(tmp)
            disabled = store.send_reply(channel="telegram", reply_target="42", text="hello")
            self.assertFalse(disabled["ok"])
            self.assertIn("disabled", disabled["error"])

            store.configure_channel("telegram", {"bot_token": "telegram-secret-token", "send_enabled": True})
            captured: dict[str, object] = {}

            def fake_transport(endpoint: str, headers: dict[str, str], body: dict[str, object]) -> dict[str, object]:
                captured["endpoint"] = endpoint
                captured["headers"] = headers
                captured["body"] = body
                return {"ok": True, "status": 200, "provider_token": "do-not-return"}

            sent = store.send_reply(
                channel="telegram",
                reply_target="42",
                text="hello",
                transport=fake_transport,
            )

            self.assertTrue(sent["ok"])
            self.assertTrue(sent["sent"])
            self.assertIn("telegram-secret-token", str(captured["endpoint"]))
            self.assertEqual(captured["body"], {"chat_id": "42", "text": "hello"})
            self.assertNotIn("telegram-secret-token", json.dumps(sent))
            self.assertEqual(sent["transport"]["provider_token"], "[redacted]")

    def test_webhook_signature_verification_requires_matching_channel_secret(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-signature-") as tmp:
            store = RemoteControlStore(tmp)
            body = b'{"peer_id":"admin","text":"/status"}'

            unsigned = verify_remote_webhook_signature(store, "webhook", {}, body)
            self.assertTrue(unsigned["ok"])
            self.assertEqual(unsigned["signature_status"], "not_configured")

            store.configure_channel("webhook", {"signing_secret": "local-signing-secret"})
            unsigned_after_config = verify_remote_webhook_signature(store, "webhook", {}, body)
            digest = hmac.new(b"local-signing-secret", body, hashlib.sha256).hexdigest()
            valid = verify_remote_webhook_signature(store, "webhook", {"x-ghost-signature": f"sha256={digest}"}, body)
            invalid = verify_remote_webhook_signature(store, "webhook", {"x-ghost-signature": "sha256=bad"}, body)

            self.assertFalse(unsigned_after_config["ok"])
            self.assertEqual(unsigned_after_config["error"], "Missing webhook signature.")
            self.assertTrue(valid["ok"])
            self.assertEqual(valid["signature_status"], "verified")
            self.assertFalse(invalid["ok"])
            self.assertEqual(invalid["error"], "Webhook signature mismatch.")
            self.assertNotIn("local-signing-secret", json.dumps(valid))
            self.assertNotIn("local-signing-secret", json.dumps(invalid))

    def test_whatsapp_webhook_verification_uses_write_only_verify_token(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-whatsapp-verify-") as tmp:
            store = RemoteControlStore(tmp)
            missing = verify_whatsapp_webhook_challenge(
                store,
                {"hub.mode": "subscribe", "hub.verify_token": "ghost-token", "hub.challenge": "12345"},
            )
            configured = store.configure_channel(
                "whatsapp",
                {
                    "api_token": "wa-secret-token",
                    "phone_number_id": "123456789",
                    "verify_token": "ghost-token",
                    "send_enabled": True,
                },
            )
            valid = verify_whatsapp_webhook_challenge(
                store,
                {"hub.mode": "subscribe", "hub.verify_token": "ghost-token", "hub.challenge": "12345"},
            )
            invalid = verify_whatsapp_webhook_challenge(
                store,
                {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"},
            )

            self.assertFalse(missing["ok"])
            self.assertTrue(configured["ok"])
            self.assertIn("verify_token", configured["channel"]["secret_fields_configured"])
            self.assertTrue(valid["ok"])
            self.assertEqual(valid["challenge"], "12345")
            self.assertFalse(invalid["ok"])
            self.assertNotIn("ghost-token", json.dumps(configured))
            self.assertNotIn("wa-secret-token", json.dumps(configured))

    def test_channel_health_reports_required_inbound_and_outbound_setup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-health-") as tmp:
            store = RemoteControlStore(tmp)

            initial = store.channel_health()
            whatsapp = next(channel for channel in initial["channels"] if channel["id"] == "whatsapp")
            webhook = next(channel for channel in initial["channels"] if channel["id"] == "webhook")

            self.assertFalse(whatsapp["inbound_ready"])
            self.assertFalse(whatsapp["outbound_ready"])
            self.assertIn("verify_token", whatsapp["missing_inbound_fields"])
            self.assertIn("api_token", whatsapp["missing_outbound_fields"])
            self.assertIn("phone_number_id", whatsapp["missing_outbound_fields"])
            self.assertTrue(webhook["inbound_ready"])

            store.configure_channel(
                "whatsapp",
                {
                    "api_token": "wa-secret-token",
                    "phone_number_id": "123456789",
                    "verify_token": "ghost-token",
                    "send_enabled": True,
                    "default_reply_target": "15551234567",
                },
            )
            configured = store.channel_health()
            whatsapp = next(channel for channel in configured["channels"] if channel["id"] == "whatsapp")

            self.assertTrue(whatsapp["inbound_ready"])
            self.assertTrue(whatsapp["outbound_ready"])
            self.assertTrue(whatsapp["delivery_target_ready"])
            self.assertEqual(whatsapp["missing_inbound_fields"], [])
            self.assertEqual(whatsapp["missing_outbound_fields"], [])
            self.assertEqual(whatsapp["webhook_path"], "/api/console/remote/webhook/whatsapp")
            self.assertFalse(whatsapp["raw_secret_values_returned"])
            self.assertNotIn("wa-secret-token", json.dumps(configured))
            self.assertNotIn("ghost-token", json.dumps(configured))

    def test_paired_sender_can_inspect_channels_and_policy_remotely(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-channel-command-") as tmp:
            store = RemoteControlStore(tmp)
            pairing = store.create_pairing(channel="telegram", peer_id="admin-chat", code="123456")
            store.approve_pairing(pairing_id=pairing["pairing"]["id"], code="123456")
            store.configure_channel("telegram", {"bot_token": "telegram-secret-token", "send_enabled": True})

            channels = store.handle_inbound(channel="telegram", peer_id="admin-chat", text="/channels")
            policy = store.handle_inbound(channel="telegram", peer_id="admin-chat", text="/policy")

            self.assertTrue(channels["ok"])
            self.assertEqual(channels["command"], "/channels")
            self.assertIn("channels", channels["response"])
            self.assertIn("Channels ready", channels["reply_preview"]["text"])
            self.assertTrue(policy["ok"])
            self.assertEqual(policy["command"], "/policy")
            self.assertIn("direct_execution_enabled", policy["response"]["policy"])
            self.assertNotIn("telegram-secret-token", json.dumps(channels))

    def test_remote_direct_command_is_admin_only_and_respects_global_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-direct-command-") as tmp:
            calls: list[str] = []
            store = RemoteControlStore(tmp)
            pairing = store.create_pairing(channel="webhook", peer_id="admin", code="111222")
            peer = store.approve_pairing(pairing_id=pairing["pairing"]["id"], code="111222")["peer"]

            blocked = store.handle_inbound(channel="webhook", peer_id="admin", text="/direct on")
            store.update_policy({"direct_execution_enabled": True})
            enabled = store.handle_inbound(channel="webhook", peer_id="admin", text="/direct on")
            executed = store.handle_inbound(
                channel="webhook",
                peer_id="admin",
                text="/run inspect readiness",
                objective_runner=lambda objective: calls.append(objective) or {"ok": True, "objective": objective},
            )
            disabled = store.handle_inbound(channel="webhook", peer_id="admin", text="/direct off")
            pending = store.handle_inbound(
                channel="webhook",
                peer_id="admin",
                text="/run inspect again",
                objective_runner=lambda objective: calls.append(objective) or {"ok": True, "objective": objective},
            )

            self.assertFalse(blocked["ok"])
            self.assertIn("dashboard", blocked["reply_preview"]["text"].lower())
            self.assertTrue(enabled["ok"])
            self.assertTrue(enabled["peer"]["allow_direct_execution"])
            self.assertEqual(executed["mode"], "direct_execution")
            self.assertEqual(calls, ["inspect readiness"])
            self.assertTrue(disabled["ok"])
            self.assertFalse(disabled["peer"]["allow_direct_execution"])
            self.assertEqual(pending["mode"], "approval_required")
            self.assertEqual(peer["role"], "admin")

    def test_provider_standard_telegram_and_slack_webhook_signatures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-provider-signatures-") as tmp:
            store = RemoteControlStore(tmp)
            body = b'{"event":{"channel":"C123","user":"U123","text":"/status"}}'
            store.configure_channel("telegram", {"verify_token": "telegram-secret-token"})
            store.configure_channel("slack", {"signing_secret": "slack-signing-secret"})

            telegram_missing = verify_remote_webhook_signature(store, "telegram", {}, body)
            telegram_valid = verify_remote_webhook_signature(
                store,
                "telegram",
                {"x-telegram-bot-api-secret-token": "telegram-secret-token"},
                body,
            )
            timestamp = str(int(time.time()))
            slack_base = f"v0:{timestamp}:{body.decode()}".encode()
            slack_digest = hmac.new(b"slack-signing-secret", slack_base, hashlib.sha256).hexdigest()
            slack_valid = verify_remote_webhook_signature(
                store,
                "slack",
                {"x-slack-request-timestamp": timestamp, "x-slack-signature": f"v0={slack_digest}"},
                body,
            )

            self.assertFalse(telegram_missing["ok"])
            self.assertEqual(telegram_missing["signature_status"], "missing_telegram_secret_token")
            self.assertTrue(telegram_valid["ok"])
            self.assertEqual(telegram_valid["signature_status"], "verified_telegram_secret_token")
            self.assertTrue(slack_valid["ok"])
            self.assertEqual(slack_valid["signature_status"], "verified_slack_signature")
            self.assertNotIn("telegram-secret-token", json.dumps(telegram_valid))
            self.assertNotIn("slack-signing-secret", json.dumps(slack_valid))

    def test_unknown_sender_gets_pairing_challenge_and_no_command_execution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-") as tmp:
            calls: list[str] = []
            store = RemoteControlStore(tmp)
            payload = store.handle_inbound(
                channel="telegram",
                peer_id="admin-chat",
                text="/run deploy production",
                objective_runner=lambda objective: calls.append(objective) or {"ok": True},
            )

            self.assertFalse(payload["ok"])
            self.assertTrue(payload["pairing_required"])
            self.assertIn("pairing_code", payload["pairing"])
            self.assertEqual(calls, [])
            self.assertEqual(store.status()["counts"]["pending_pairings"], 1)

    def test_paired_sender_status_command_returns_safe_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-") as tmp:
            store = RemoteControlStore(tmp)
            pairing = store.create_pairing(channel="telegram", peer_id="admin-chat", code="123456")
            approved = store.approve_pairing(pairing_id=pairing["pairing"]["id"], code="123456")
            self.assertTrue(approved["ok"])

            payload = store.handle_inbound(
                channel="telegram",
                peer_id="admin-chat",
                text="/status",
                status_provider=lambda: {"ok": True, "api_token": "secret-token", "status": "ready"},
            )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["response"]["api_token"], "[redacted]")
            self.assertEqual(payload["response"]["status"], "ready")
            self.assertEqual(payload["reply_preview"]["channel"], "telegram")
            self.assertEqual(payload["reply_preview"]["body"]["chat_id"], "admin-chat")
            self.assertNotIn("secret-token", json.dumps(payload["reply_preview"]))

    def test_run_command_requires_approval_until_direct_execution_is_enabled_per_peer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-") as tmp:
            calls: list[str] = []
            store = RemoteControlStore(tmp)
            pairing = store.create_pairing(channel="signal", peer_id="admin-phone", code="222333")
            peer = store.approve_pairing(pairing_id=pairing["pairing"]["id"], code="222333")["peer"]

            pending = store.handle_inbound(
                channel="signal",
                peer_id="admin-phone",
                text="/run summarize readiness",
                objective_runner=lambda objective: calls.append(objective) or {"ok": True},
            )

            self.assertTrue(pending["ok"])
            self.assertEqual(pending["mode"], "approval_required")
            self.assertEqual(calls, [])

            store.update_policy({"direct_execution_enabled": True})
            store.set_peer_direct_execution(peer["id"], True)
            executed = store.handle_inbound(
                channel="signal",
                peer_id="admin-phone",
                text="/run summarize readiness",
                objective_runner=lambda objective: calls.append(objective) or {"ok": True, "objective": objective},
            )

            self.assertTrue(executed["ok"])
            self.assertEqual(executed["mode"], "direct_execution")
            self.assertEqual(calls, ["summarize readiness"])
            self.assertIn("reply_preview", executed)

    def test_pending_approval_can_be_executed_from_dashboard(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-") as tmp:
            calls: list[str] = []
            store = RemoteControlStore(tmp)
            pairing = store.create_pairing(channel="discord", peer_id="admin", code="444555")
            store.approve_pairing(pairing_id=pairing["pairing"]["id"], code="444555")
            pending = store.handle_inbound(channel="discord", peer_id="admin", text="/run check tests")
            approval_id = pending["approval"]["id"]

            resolved = store.resolve_approval(
                approval_id,
                approved=True,
                objective_runner=lambda objective: calls.append(objective) or {"ok": True, "done": True},
            )

            self.assertTrue(resolved["ok"])
            self.assertEqual(calls, ["check tests"])
            self.assertEqual(resolved["approval"]["status"], "executed")


class RemoteControlConsoleRouteTests(unittest.TestCase):
    def test_console_registers_remote_routes_and_supports_direct_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-console-") as tmp:
            calls: list[str] = []
            server = GatewayServer()
            register_console_routes(
                server,
                state_dir=tmp,
                run_objective=lambda objective: calls.append(objective) or {"ok": True, "objective": objective},
            )

            for method, path in [
                ("GET", "/api/console/remote/status"),
                ("GET", "/api/console/remote/health"),
                ("POST", "/api/console/remote/policy"),
                ("POST", "/api/console/remote/pairing/create"),
                ("POST", "/api/console/remote/pairing/approve"),
                ("POST", "/api/console/remote/inbound"),
                ("POST", "/api/console/remote/channels/telegram"),
                ("POST", "/api/console/remote/send-test"),
                ("POST", "/api/console/remote/webhook/telegram"),
                ("GET", "/api/console/remote/webhook/whatsapp"),
            ]:
                self.assertIsNotNone(server.routes.find(method, path))

            pair_route = server.routes.find("POST", "/api/console/remote/pairing/create")
            approve_route = server.routes.find("POST", "/api/console/remote/pairing/approve")
            policy_route = server.routes.find("POST", "/api/console/remote/policy")
            health_route = server.routes.find("GET", "/api/console/remote/health")
            inbound_route = server.routes.find("POST", "/api/console/remote/inbound")
            channel_route = server.routes.find("POST", "/api/console/remote/channels/whatsapp")
            webhook_verify_route = server.routes.find("GET", "/api/console/remote/webhook/whatsapp")
            self.assertIsNotNone(pair_route)
            self.assertIsNotNone(approve_route)
            self.assertIsNotNone(policy_route)
            self.assertIsNotNone(health_route)
            self.assertIsNotNone(inbound_route)
            self.assertIsNotNone(channel_route)
            self.assertIsNotNone(webhook_verify_route)

            pairing = pair_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/remote/pairing/create",
                    "headers": {},
                    "body": json.dumps({"channel": "webhook", "peer_id": "phone", "display_name": "Admin"}),
                    "query": {},
                }
            )
            self.assertTrue(pairing["ok"])
            peer = approve_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/remote/pairing/approve",
                    "headers": {},
                    "body": json.dumps({"pairing_id": pairing["pairing"]["id"]}),
                    "query": {},
                }
            )["peer"]
            self.assertFalse(peer["allow_direct_execution"])

            policy_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/remote/policy",
                    "headers": {},
                    "body": json.dumps({"direct_execution_enabled": True}),
                    "query": {},
                }
            )
            peer_direct_route = server.routes.find("POST", f"/api/console/remote/peers/{peer['id']}/direct")
            self.assertIsNotNone(peer_direct_route)
            peer_direct_route.handler(
                {
                    "method": "POST",
                    "path": f"/api/console/remote/peers/{peer['id']}/direct",
                    "headers": {},
                    "body": json.dumps({"allow": True}),
                    "query": {},
                }
            )
            executed = inbound_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/remote/inbound",
                    "headers": {},
                    "body": json.dumps({"channel": "webhook", "peer_id": "phone", "text": "/run inspect repo"}),
                    "query": {},
                }
            )

            self.assertTrue(executed["ok"])
            self.assertEqual(executed["mode"], "direct_execution")
            self.assertEqual(calls, ["inspect repo"])

            channel_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/remote/channels/whatsapp",
                    "headers": {},
                    "body": json.dumps({"verify_token": "ghost-token", "api_token": "wa-token", "phone_number_id": "123"}),
                    "query": {},
                }
            )
            challenge = webhook_verify_route.handler(
                {
                    "method": "GET",
                    "path": "/api/console/remote/webhook/whatsapp",
                    "headers": {},
                    "body": "",
                    "query": {"hub.mode": "subscribe", "hub.verify_token": "ghost-token", "hub.challenge": "abc123"},
                }
            )
            self.assertEqual(challenge.body, "abc123")
            self.assertEqual(challenge.content_type, "text/plain")

            health = health_route.handler(
                {
                    "method": "GET",
                    "path": "/api/console/remote/health",
                    "headers": {},
                    "body": "",
                    "query": {},
                }
            )
            self.assertTrue(health["ok"])
            self.assertIn("ready_inbound_channels", health["counts"])
            self.assertNotIn("wa-token", json.dumps(health))

    def test_console_channel_config_route_never_returns_raw_secret(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-channel-route-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)
            route = server.routes.find("POST", "/api/console/remote/channels/slack")
            self.assertIsNotNone(route)

            payload = route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/remote/channels/slack",
                    "headers": {},
                    "body": json.dumps({"bot_token": "xoxb-secret-token", "signing_secret": "slack-signing", "send_enabled": True}),
                    "query": {},
                }
            )

            self.assertTrue(payload["ok"])
            self.assertTrue(payload["channel"]["configured"])
            self.assertTrue(payload["channel"]["send_enabled"])
            self.assertNotIn("xoxb-secret-token", json.dumps(payload))
            self.assertNotIn("slack-signing", json.dumps(payload))

    def test_console_provider_webhook_normalizes_and_keeps_pairing_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-webhook-") as tmp:
            calls: list[str] = []
            server = GatewayServer()
            register_console_routes(
                server,
                state_dir=tmp,
                run_objective=lambda objective: calls.append(objective) or {"ok": True, "objective": objective},
            )
            route = server.routes.find("POST", "/api/console/remote/webhook/telegram")
            self.assertIsNotNone(route)

            blocked = route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/remote/webhook/telegram",
                    "headers": {},
                    "body": json.dumps({"message": {"chat": {"id": 123}, "text": "/run check status"}}),
                    "query": {},
                }
            )

            self.assertFalse(blocked["ok"])
            self.assertTrue(blocked["pairing_required"])
            self.assertEqual(blocked["normalized"]["peer_id"], "123")
            self.assertEqual(blocked["reply_preview"]["channel"], "telegram")
            self.assertEqual(blocked["reply_preview"]["body"]["chat_id"], "123")
            self.assertEqual(calls, [])

    def test_console_provider_webhook_rejects_unsigned_payload_when_signing_secret_exists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-webhook-signature-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)
            config_route = server.routes.find("POST", "/api/console/remote/channels/telegram")
            route = server.routes.find("POST", "/api/console/remote/webhook/telegram")
            self.assertIsNotNone(config_route)
            self.assertIsNotNone(route)

            config_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/remote/channels/telegram",
                    "headers": {},
                    "body": json.dumps({"signing_secret": "telegram-signing-secret"}),
                    "query": {},
                }
            )
            body = json.dumps({"message": {"chat": {"id": 123}, "text": "/status"}})
            unsigned = route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/remote/webhook/telegram",
                    "headers": {},
                    "body": body,
                    "query": {},
                }
            )
            digest = hmac.new(b"telegram-signing-secret", body.encode("utf-8"), hashlib.sha256).hexdigest()
            signed = route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/remote/webhook/telegram",
                    "headers": {"x-ghost-signature": f"sha256={digest}"},
                    "body": body,
                    "query": {},
                }
            )

            self.assertFalse(unsigned["ok"])
            self.assertEqual(unsigned["error"], "Missing webhook signature.")
            self.assertTrue(signed["pairing_required"])
            self.assertEqual(signed["signature_status"], "verified")
            self.assertNotIn("telegram-signing-secret", json.dumps(unsigned))
            self.assertNotIn("telegram-signing-secret", json.dumps(signed))

    def test_cli_remote_simulate_uses_local_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-remote-cli-") as tmp:
            pair_code_result = _main(["remote", "pair-code", "--state-dir", tmp, "--channel", "webhook", "--peer", "cli-admin"])
            self.assertEqual(pair_code_result, 0)

            status_result = _main(["remote", "status", "--state-dir", tmp])
            self.assertEqual(status_result, 0)

            simulate_result = _main(
                ["remote", "simulate", "--state-dir", tmp, "--channel", "webhook", "--peer", "new-admin", "--text", "/status"]
            )
            self.assertEqual(simulate_result, 1)
            self.assertTrue((Path(tmp) / "remote_control_state.json").exists())


if __name__ == "__main__":
    unittest.main()
