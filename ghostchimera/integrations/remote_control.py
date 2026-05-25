"""Ghost-native remote control primitives.

This module absorbs the useful messaging-gateway patterns from OpenClaw and
Hermes-Agent without requiring either project at runtime.  It provides a small
local state store, pairing workflow, command parser, approval queue, and a
dashboard-controlled direct execution policy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

RemoteObjectiveRunner = Callable[[str], dict[str, Any]]
RemoteStatusProvider = Callable[[], dict[str, Any]]
RemoteSendTransport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]

SAFE_COMMANDS = {"/help", "/status", "/readiness", "/paths", "/jobs", "/stop"}
ACTION_COMMANDS = {"/run", "/approve", "/deny"}
DEFAULT_CHANNELS = ("telegram", "discord", "slack", "whatsapp", "signal", "sms", "email", "webhook")
SECRET_MARKERS = ("token", "secret", "api_key", "apikey", "password", "credential", "authorization", "webhook")
REMOTE_SECRET_FIELDS = ("bot_token", "api_token", "webhook_url", "signing_secret", "phone_number_id", "smtp_password")


@dataclass
class RemotePolicy:
    enabled: bool = True
    direct_execution_enabled: bool = False
    require_paired_peer: bool = True
    default_direct_execution_for_admins: bool = False
    allowed_commands: list[str] = field(default_factory=lambda: sorted(SAFE_COMMANDS | ACTION_COMMANDS))
    direct_execution_commands: list[str] = field(default_factory=lambda: ["/run", "/approve"])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RemotePeer:
    id: str
    channel: str
    peer_id: str
    display_name: str = ""
    role: str = "admin"
    status: str = "paired"
    allow_direct_execution: bool = False
    paired_at: float = field(default_factory=time.time)
    last_seen: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RemotePairing:
    id: str
    channel: str
    peer_id: str
    display_name: str = ""
    status: str = "pending"
    code_hash: str = ""
    code_preview: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RemoteApproval:
    id: str
    channel: str
    peer_id: str
    command: str
    objective: str
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    resolved_at: float = 0.0
    result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


@dataclass
class RemoteInboundMessage:
    channel: str
    peer_id: str
    text: str
    display_name: str = ""
    reply_target: str = ""
    raw_shape: str = "generic"

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


@dataclass
class RemoteOutboundReply:
    channel: str
    reply_target: str
    text: str
    adapter_status: str
    method: str = "POST"
    endpoint_hint: str = ""
    auth_required: bool = True
    body: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


def _now() -> float:
    return time.time()


def _stable_id(*parts: str) -> str:
    raw = "|".join(str(part).strip().lower() for part in parts if part is not None)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def _new_pairing_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"secret_fields_configured"}:
                redacted[str(key)] = _redact_value(item)
            elif any(marker in lowered for marker in SECRET_MARKERS):
                redacted[str(key)] = "[redacted]" if item else ""
            else:
                redacted[str(key)] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _state_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "remote_control_state.json"


def _timeline_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "remote_control_events.jsonl"


def _secrets_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "remote_control_secrets.json"


def _default_state() -> dict[str, Any]:
    return {
        "policy": RemotePolicy().to_dict(),
        "peers": {},
        "pairings": {},
        "approvals": {},
        "channels": {
            channel: {
                "id": channel,
                "enabled": channel == "webhook",
                "configured": False,
                "send_enabled": False,
                "default_reply_target": "",
                "secret_fields_configured": [],
                "adapter_status": "metadata_only" if channel != "webhook" else "ready",
                "notes": "Provider adapter is optional; inbound webhook simulation works without external services.",
            }
            for channel in DEFAULT_CHANNELS
        },
    }


def normalize_remote_payload(channel: str, payload: dict[str, Any]) -> RemoteInboundMessage:
    """Normalize common messaging provider webhook payloads into Ghost commands."""

    channel = channel.strip().lower() or "webhook"
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if channel == "telegram":
        return _normalize_telegram(payload)
    if channel == "discord":
        return _normalize_discord(payload)
    if channel == "slack":
        return _normalize_slack(payload)
    if channel == "whatsapp":
        return _normalize_whatsapp(payload)
    if channel == "signal":
        return _normalize_signal(payload)
    if channel in {"sms", "email", "webhook"}:
        return _normalize_generic(channel, payload)
    raise ValueError(f"Unsupported remote channel: {channel}")


def build_outbound_reply(channel: str, reply_target: str, text: str) -> RemoteOutboundReply:
    """Build a provider-specific outbound reply preview without sending it."""

    channel = channel.strip().lower() or "webhook"
    reply_target = str(reply_target or "").strip()
    text = _safe_reply_text(text)
    if channel == "telegram":
        return RemoteOutboundReply(
            channel="telegram",
            reply_target=reply_target,
            text=text,
            adapter_status="token_required",
            endpoint_hint="https://api.telegram.org/bot<TOKEN>/sendMessage",
            body={"chat_id": reply_target, "text": text},
        )
    if channel == "discord":
        return RemoteOutboundReply(
            channel="discord",
            reply_target=reply_target,
            text=text,
            adapter_status="bot_token_required",
            endpoint_hint=f"https://discord.com/api/v10/channels/{reply_target}/messages",
            body={"content": text},
        )
    if channel == "slack":
        return RemoteOutboundReply(
            channel="slack",
            reply_target=reply_target,
            text=text,
            adapter_status="bot_token_required",
            endpoint_hint="https://slack.com/api/chat.postMessage",
            body={"channel": reply_target, "text": text},
        )
    if channel == "whatsapp":
        return RemoteOutboundReply(
            channel="whatsapp",
            reply_target=reply_target,
            text=text,
            adapter_status="cloud_api_token_required",
            endpoint_hint="https://graph.facebook.com/vXX.X/<PHONE_NUMBER_ID>/messages",
            body={
                "messaging_product": "whatsapp",
                "to": reply_target,
                "type": "text",
                "text": {"body": text},
            },
        )
    if channel == "signal":
        return RemoteOutboundReply(
            channel="signal",
            reply_target=reply_target,
            text=text,
            adapter_status="signal_gateway_required",
            endpoint_hint="signal-cli compatible gateway send endpoint",
            body={"recipient": reply_target, "message": text},
        )
    if channel == "sms":
        return RemoteOutboundReply(
            channel="sms",
            reply_target=reply_target,
            text=text,
            adapter_status="sms_provider_required",
            endpoint_hint="configured SMS provider messages endpoint",
            body={"to": reply_target, "message": text},
        )
    if channel == "email":
        return RemoteOutboundReply(
            channel="email",
            reply_target=reply_target,
            text=text,
            adapter_status="smtp_or_email_api_required",
            endpoint_hint="configured email provider send endpoint",
            body={"to": reply_target, "subject": "Ghost Chimera", "text": text},
        )
    if channel == "webhook":
        return RemoteOutboundReply(
            channel="webhook",
            reply_target=reply_target,
            text=text,
            adapter_status="preview_only",
            endpoint_hint="operator-provided webhook URL",
            auth_required=False,
            body={"peer_id": reply_target, "text": text},
        )
    raise ValueError(f"Unsupported remote channel: {channel}")


def verify_remote_webhook_signature(
    store: RemoteControlStore,
    channel: str,
    headers: dict[str, Any],
    body: bytes | str,
) -> dict[str, Any]:
    """Verify an optional channel signing secret against the raw webhook body.

    Channels without a configured signing secret remain usable for local
    simulation and provider previews. Once a signing secret is saved, provider
    webhook ingestion fails closed until the request includes a matching HMAC
    SHA-256 signature.
    """

    channel = channel.strip().lower() or "webhook"
    secrets_data = store._load_secrets()
    channel_secrets = secrets_data.get(channel) if isinstance(secrets_data.get(channel), dict) else {}
    signing_secret = str(channel_secrets.get("signing_secret") or "").strip()
    if not signing_secret:
        return {"ok": True, "signature_status": "not_configured"}

    normalized_headers = {str(key).lower(): str(value).strip() for key, value in headers.items()}
    provided = (
        normalized_headers.get("x-ghost-signature")
        or normalized_headers.get("x-hub-signature-256")
        or normalized_headers.get("x-signature")
    )
    if not provided:
        return {"ok": False, "error": "Missing webhook signature.", "signature_status": "missing"}

    body_bytes = body.encode("utf-8") if isinstance(body, str) else body
    expected = hmac.new(signing_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    provided_digest = provided.split("=", 1)[1] if provided.startswith("sha256=") else provided
    if not hmac.compare_digest(expected, provided_digest):
        return {"ok": False, "error": "Webhook signature mismatch.", "signature_status": "mismatch"}
    return {"ok": True, "signature_status": "verified"}


def _normalize_telegram(payload: dict[str, Any]) -> RemoteInboundMessage:
    message = payload.get("message") if isinstance(payload.get("message"), dict) else payload
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    peer_id = str(chat.get("id") or sender.get("id") or "").strip()
    name = " ".join(
        part
        for part in [str(sender.get("first_name") or "").strip(), str(sender.get("last_name") or "").strip()]
        if part
    ) or str(sender.get("username") or "").strip()
    return RemoteInboundMessage(
        channel="telegram",
        peer_id=peer_id,
        text=str(message.get("text") or "").strip(),
        display_name=name,
        reply_target=peer_id,
        raw_shape="telegram.message",
    )


def _normalize_discord(payload: dict[str, Any]) -> RemoteInboundMessage:
    author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
    peer_id = str(payload.get("channel_id") or author.get("id") or "").strip()
    name = str(author.get("username") or author.get("global_name") or "").strip()
    return RemoteInboundMessage(
        channel="discord",
        peer_id=peer_id,
        text=str(payload.get("content") or payload.get("text") or "").strip(),
        display_name=name,
        reply_target=peer_id,
        raw_shape="discord.message",
    )


def _normalize_slack(payload: dict[str, Any]) -> RemoteInboundMessage:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    peer_id = str(event.get("channel") or event.get("user") or payload.get("user_id") or "").strip()
    name = str(event.get("user") or payload.get("user_name") or "").strip()
    return RemoteInboundMessage(
        channel="slack",
        peer_id=peer_id,
        text=str(event.get("text") or payload.get("text") or "").strip(),
        display_name=name,
        reply_target=peer_id,
        raw_shape="slack.event",
    )


def _normalize_whatsapp(payload: dict[str, Any]) -> RemoteInboundMessage:
    message: dict[str, Any] = {}
    contact: dict[str, Any] = {}
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        if isinstance(value, dict):
            messages = value.get("messages") if isinstance(value.get("messages"), list) else []
            contacts = value.get("contacts") if isinstance(value.get("contacts"), list) else []
            message = messages[0] if messages and isinstance(messages[0], dict) else {}
            contact = contacts[0] if contacts and isinstance(contacts[0], dict) else {}
    except (KeyError, IndexError, TypeError):
        message = payload
    text_payload = message.get("text") if isinstance(message.get("text"), dict) else {}
    profile = contact.get("profile") if isinstance(contact.get("profile"), dict) else {}
    peer_id = str(message.get("from") or contact.get("wa_id") or payload.get("from") or "").strip()
    return RemoteInboundMessage(
        channel="whatsapp",
        peer_id=peer_id,
        text=str(text_payload.get("body") or message.get("text") or payload.get("text") or "").strip(),
        display_name=str(profile.get("name") or "").strip(),
        reply_target=peer_id,
        raw_shape="whatsapp.cloud_api",
    )


def _normalize_signal(payload: dict[str, Any]) -> RemoteInboundMessage:
    envelope = payload.get("envelope") if isinstance(payload.get("envelope"), dict) else payload
    data_message = envelope.get("dataMessage") if isinstance(envelope.get("dataMessage"), dict) else envelope
    peer_id = str(envelope.get("source") or payload.get("source") or "").strip()
    return RemoteInboundMessage(
        channel="signal",
        peer_id=peer_id,
        text=str(data_message.get("message") or payload.get("text") or "").strip(),
        display_name=str(envelope.get("sourceName") or "").strip(),
        reply_target=peer_id,
        raw_shape="signal.envelope",
    )


def _normalize_generic(channel: str, payload: dict[str, Any]) -> RemoteInboundMessage:
    peer_id = str(
        payload.get("peer_id")
        or payload.get("sender")
        or payload.get("from")
        or payload.get("chat_id")
        or payload.get("channel_id")
        or ""
    ).strip()
    return RemoteInboundMessage(
        channel=channel,
        peer_id=peer_id,
        text=str(payload.get("text") or payload.get("message") or payload.get("body") or "").strip(),
        display_name=str(payload.get("display_name") or payload.get("name") or "").strip(),
        reply_target=str(payload.get("reply_target") or peer_id).strip(),
        raw_shape=f"{channel}.generic",
    )


def _safe_reply_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        cleaned = "Ghost Chimera received the command."
    return cleaned[:3800]


def _summarize_reply(command: str, payload: dict[str, Any]) -> str:
    if not payload.get("ok", True):
        return f"{command} failed: {str(payload.get('error') or 'unknown error')[:240]}"
    if command in {"/status", "/readiness"}:
        warning_count = len(payload.get("warnings") or []) if isinstance(payload.get("warnings"), list) else 0
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        if counts:
            return (
                f"Ghost readiness checked. Warnings: {warning_count}. "
                f"Sources: {counts.get('approved_sources', 0)}/{counts.get('learning_sources', 0)} approved."
            )
        return "Ghost Chimera is reachable."
    if command == "/paths":
        active = payload.get("active_path") if isinstance(payload.get("active_path"), dict) else {}
        profile = active.get("profile_id") or "default"
        profiles = payload.get("profiles") if isinstance(payload.get("profiles"), list) else []
        return f"Active Ghost Path: {profile}. Available paths: {len(profiles)}."
    if command == "/jobs":
        jobs = payload.get("available_jobs") or payload.get("jobs") or []
        history = payload.get("history") if isinstance(payload.get("history"), list) else []
        return f"Autonomy jobs available: {len(jobs) if isinstance(jobs, list) else 0}. Recent jobs: {len(history)}."
    return "Ghost Chimera processed the command."


def _resolve_send_endpoint(reply: RemoteOutboundReply, secrets_data: dict[str, Any]) -> tuple[str, dict[str, str]]:
    channel = reply.channel
    headers = {"Content-Type": "application/json", "User-Agent": "GhostChimeraRemote/0.4"}
    if channel == "telegram":
        token = str(secrets_data.get("bot_token") or secrets_data.get("api_token") or "").strip()
        if not token:
            raise ValueError("Telegram bot_token is required for sending.")
        return f"https://api.telegram.org/bot{token}/sendMessage", headers
    if channel == "discord":
        token = str(secrets_data.get("bot_token") or secrets_data.get("api_token") or "").strip()
        if not token:
            raise ValueError("Discord bot_token is required for sending.")
        headers["Authorization"] = f"Bot {token}"
        return f"https://discord.com/api/v10/channels/{reply.reply_target}/messages", headers
    if channel == "slack":
        token = str(secrets_data.get("bot_token") or secrets_data.get("api_token") or "").strip()
        if not token:
            raise ValueError("Slack bot_token is required for sending.")
        headers["Authorization"] = f"Bearer {token}"
        return "https://slack.com/api/chat.postMessage", headers
    if channel == "whatsapp":
        token = str(secrets_data.get("api_token") or secrets_data.get("bot_token") or "").strip()
        phone_number_id = str(secrets_data.get("phone_number_id") or "").strip()
        if not token or not phone_number_id:
            raise ValueError("WhatsApp api_token and phone_number_id are required for sending.")
        headers["Authorization"] = f"Bearer {token}"
        return f"https://graph.facebook.com/v20.0/{phone_number_id}/messages", headers
    endpoint = str(secrets_data.get("webhook_url") or "").strip()
    if not endpoint:
        raise ValueError(f"{channel} webhook_url is required for sending.")
    if not endpoint.startswith("https://"):
        raise ValueError("Outbound remote webhook URLs must use https://.")
    token = str(secrets_data.get("api_token") or secrets_data.get("bot_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return endpoint, headers


def _default_send_transport(endpoint: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    request = urllib_request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=15) as response:
            payload = response.read().decode("utf-8", errors="replace")[:2000]
            return {"ok": 200 <= int(response.status) < 300, "status": int(response.status), "body_preview": payload}
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")[:2000]
        return {"ok": False, "status": int(exc.code), "body_preview": payload, "error": str(exc.reason)}
    except URLError as exc:
        return {"ok": False, "error": str(exc.reason)}


class RemoteControlStore:
    """Local JSON-backed remote-control state and command handler."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir).expanduser()

    def _load(self) -> dict[str, Any]:
        path = _state_path(self.state_dir)
        if not path.exists():
            return _default_state()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _default_state()
        if not isinstance(data, dict):
            return _default_state()
        default = _default_state()
        for key, value in default.items():
            data.setdefault(key, value)
        if not isinstance(data.get("policy"), dict):
            data["policy"] = default["policy"]
        for map_key in ("peers", "pairings", "approvals", "channels"):
            if not isinstance(data.get(map_key), dict):
                data[map_key] = default[map_key]
        for channel, channel_default in default["channels"].items():
            existing = data["channels"].get(channel)
            if isinstance(existing, dict):
                data["channels"][channel] = {**channel_default, **existing}
            else:
                data["channels"][channel] = channel_default
        return data

    def _save(self, data: dict[str, Any]) -> None:
        path = _state_path(self.state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_redact_value(data), indent=2, sort_keys=True), encoding="utf-8")

    def _load_secrets(self) -> dict[str, Any]:
        path = _secrets_path(self.state_dir)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_secrets(self, data: dict[str, Any]) -> None:
        path = _secrets_path(self.state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _event(self, event_type: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            "id": _stable_id(event_type, str(_now()), json.dumps(detail or {}, sort_keys=True, default=str)),
            "timestamp": _now(),
            "event_type": event_type,
            "detail": _redact_value(detail or {}),
        }
        path = _timeline_path(self.state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        return event

    def timeline(self, *, limit: int = 50) -> list[dict[str, Any]]:
        path = _timeline_path(self.state_dir)
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 200)) :]:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                events.append(_redact_value(data))
        return events

    def status(self) -> dict[str, Any]:
        data = self._load()
        peers = list(data["peers"].values())
        pending_pairings = [item for item in data["pairings"].values() if item.get("status") == "pending"]
        pending_approvals = [item for item in data["approvals"].values() if item.get("status") == "pending"]
        return {
            "ok": True,
            "policy": _redact_value(data["policy"]),
            "channels": list(data["channels"].values()),
            "peers": _redact_value(peers),
            "pairings": _redact_value(pending_pairings),
            "approvals": _redact_value(pending_approvals),
            "counts": {
                "paired_peers": len([peer for peer in peers if peer.get("status") == "paired"]),
                "pending_pairings": len(pending_pairings),
                "pending_approvals": len(pending_approvals),
            },
            "secret_policy": {"secrets_are_write_only": True, "raw_secret_values_returned": False},
            "timeline": self.timeline(limit=20),
        }

    def configure_channel(self, channel: str, payload: dict[str, Any]) -> dict[str, Any]:
        channel = channel.strip().lower()
        if channel not in DEFAULT_CHANNELS:
            raise ValueError(f"Unsupported remote channel: {channel}")
        data = self._load()
        secrets_data = self._load_secrets()
        channel_secrets = dict(secrets_data.get(channel) or {})
        clear_secrets = bool(payload.get("clear_secrets"))

        if clear_secrets:
            channel_secrets = {}
        else:
            for field_name in REMOTE_SECRET_FIELDS:
                value = str(payload.get(field_name) or "").strip()
                if value:
                    if len(value) > 4000:
                        raise ValueError(f"{field_name} is too long")
                    channel_secrets[field_name] = value

        if channel_secrets:
            secrets_data[channel] = channel_secrets
        else:
            secrets_data.pop(channel, None)
        self._save_secrets(secrets_data)

        channel_state = dict(data["channels"].get(channel) or {"id": channel})
        configured_fields = sorted(key for key, value in channel_secrets.items() if value)
        default_reply_target = str(payload.get("default_reply_target", channel_state.get("default_reply_target", "")) or "").strip()
        if len(default_reply_target) > 500:
            raise ValueError("default_reply_target is too long")
        channel_state.update(
            {
                "id": channel,
                "enabled": bool(payload.get("enabled", channel_state.get("enabled", channel == "webhook"))),
                "configured": bool(configured_fields),
                "send_enabled": bool(payload.get("send_enabled", channel_state.get("send_enabled", False)))
                and bool(configured_fields),
                "default_reply_target": default_reply_target,
                "secret_fields_configured": configured_fields,
                "adapter_status": "send_enabled"
                if bool(payload.get("send_enabled", channel_state.get("send_enabled", False))) and configured_fields
                else ("configured" if configured_fields else ("ready" if channel == "webhook" else "metadata_only")),
                "notes": "Credentials are stored write-only in local Ghost state; raw values are never returned.",
            }
        )
        data["channels"][channel] = channel_state
        self._save(data)
        self._event(
            "remote_channel_configured",
            {
                "channel": channel,
                "configured": bool(configured_fields),
                "send_enabled": channel_state["send_enabled"],
                "secret_fields_configured": configured_fields,
            },
        )
        return {"ok": True, "channel": _redact_value(channel_state)}

    def send_reply(
        self,
        *,
        channel: str,
        reply_target: str,
        text: str,
        transport: RemoteSendTransport | None = None,
    ) -> dict[str, Any]:
        channel = channel.strip().lower()
        if channel not in DEFAULT_CHANNELS:
            return {"ok": False, "error": f"Unsupported remote channel: {channel}"}
        data = self._load()
        channel_state = data["channels"].get(channel)
        if not isinstance(channel_state, dict) or not channel_state.get("send_enabled"):
            return {"ok": False, "error": "Outbound sending is disabled for this channel.", "channel": channel}
        reply_target = str(reply_target or channel_state.get("default_reply_target") or "").strip()
        if not reply_target:
            return {"ok": False, "error": "reply_target is required and no default recipient is configured.", "channel": channel}
        secrets_data = self._load_secrets()
        channel_secrets = secrets_data.get(channel) if isinstance(secrets_data.get(channel), dict) else {}
        if not channel_secrets:
            return {"ok": False, "error": "No write-only credentials are configured for this channel.", "channel": channel}
        reply = build_outbound_reply(channel, reply_target, text)
        try:
            endpoint, headers = _resolve_send_endpoint(reply, channel_secrets)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "reply_preview": reply.to_dict()}
        sender = transport or _default_send_transport
        try:
            transport_result = sender(endpoint, headers, reply.body)
        except Exception as exc:  # noqa: BLE001 - adapters surface provider failures as data
            self._event("remote_reply_send_failed", {"channel": channel, "reply_target": reply_target, "error": str(exc)[:240]})
            return {"ok": False, "error": str(exc)[:500], "reply_preview": reply.to_dict()}
        self._event("remote_reply_sent", {"channel": channel, "reply_target": reply_target, "ok": transport_result.get("ok", True)})
        return {
            "ok": bool(transport_result.get("ok", True)),
            "sent": True,
            "channel": channel,
            "reply_preview": reply.to_dict(),
            "transport": _redact_value(transport_result),
            "raw_secret_values_returned": False,
        }

    def update_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._load()
        policy = RemotePolicy(**{**RemotePolicy().to_dict(), **data.get("policy", {})})
        for key in (
            "enabled",
            "direct_execution_enabled",
            "require_paired_peer",
            "default_direct_execution_for_admins",
        ):
            if key in payload:
                setattr(policy, key, bool(payload[key]))
        if isinstance(payload.get("allowed_commands"), list):
            allowed = [str(item).strip() for item in payload["allowed_commands"] if str(item).strip()]
            policy.allowed_commands = sorted(set(allowed))
        data["policy"] = policy.to_dict()
        self._save(data)
        self._event("remote_policy_updated", {"direct_execution_enabled": policy.direct_execution_enabled})
        return {"ok": True, "policy": policy.to_dict()}

    def create_pairing(
        self,
        *,
        channel: str,
        peer_id: str,
        display_name: str = "",
        expires_seconds: int = 900,
        code: str = "",
    ) -> dict[str, Any]:
        channel = channel.strip().lower() or "webhook"
        peer_id = peer_id.strip()
        if channel not in DEFAULT_CHANNELS:
            raise ValueError(f"Unsupported remote channel: {channel}")
        if not peer_id:
            raise ValueError("peer_id is required")
        data = self._load()
        code = code.strip() or _new_pairing_code()
        pairing = RemotePairing(
            id=_stable_id(channel, peer_id),
            channel=channel,
            peer_id=peer_id,
            display_name=display_name.strip(),
            code_hash=_hash_code(code),
            code_preview=code,
            expires_at=_now() + max(60, min(int(expires_seconds), 3600)),
        )
        data["pairings"][pairing.id] = pairing.to_dict()
        self._save(data)
        self._event("remote_pairing_created", {"channel": channel, "peer_id": peer_id, "pairing_id": pairing.id})
        payload = pairing.to_dict()
        payload["pairing_code"] = code
        return {"ok": True, "pairing": payload}

    def approve_pairing(self, *, pairing_id: str = "", channel: str = "", peer_id: str = "", code: str = "") -> dict[str, Any]:
        data = self._load()
        pairing: dict[str, Any] | None = None
        if pairing_id:
            candidate = data["pairings"].get(pairing_id)
            if isinstance(candidate, dict):
                pairing = candidate
        else:
            candidate = data["pairings"].get(_stable_id(channel, peer_id))
            if isinstance(candidate, dict):
                pairing = candidate
        if not pairing:
            return {"ok": False, "error": "Pairing request not found."}
        if float(pairing.get("expires_at") or 0.0) < _now():
            pairing["status"] = "expired"
            self._save(data)
            return {"ok": False, "error": "Pairing code expired."}
        if code and _hash_code(code) != pairing.get("code_hash"):
            return {"ok": False, "error": "Pairing code does not match."}
        policy = RemotePolicy(**{**RemotePolicy().to_dict(), **data.get("policy", {})})
        peer = RemotePeer(
            id=str(pairing["id"]),
            channel=str(pairing["channel"]),
            peer_id=str(pairing["peer_id"]),
            display_name=str(pairing.get("display_name") or ""),
            allow_direct_execution=policy.default_direct_execution_for_admins,
            last_seen=_now(),
        )
        pairing["status"] = "approved"
        data["pairings"][peer.id] = pairing
        data["peers"][peer.id] = peer.to_dict()
        self._save(data)
        self._event(
            "remote_peer_paired",
            {"channel": peer.channel, "peer_id": peer.peer_id, "allow_direct_execution": peer.allow_direct_execution},
        )
        return {"ok": True, "peer": peer.to_dict(), "pairing": _redact_value(pairing)}

    def set_peer_direct_execution(self, peer_id: str, allowed: bool) -> dict[str, Any]:
        data = self._load()
        peer = data["peers"].get(peer_id)
        if not isinstance(peer, dict):
            return {"ok": False, "error": "Remote peer not found."}
        peer["allow_direct_execution"] = bool(allowed)
        data["peers"][peer_id] = peer
        self._save(data)
        self._event("remote_peer_policy_updated", {"peer_id": peer_id, "allow_direct_execution": bool(allowed)})
        return {"ok": True, "peer": _redact_value(peer)}

    def revoke_peer(self, peer_id: str) -> dict[str, Any]:
        data = self._load()
        peer = data["peers"].get(peer_id)
        if not isinstance(peer, dict):
            return {"ok": False, "error": "Remote peer not found."}
        peer["status"] = "revoked"
        data["peers"][peer_id] = peer
        self._save(data)
        self._event("remote_peer_revoked", {"peer_id": peer_id})
        return {"ok": True, "peer": _redact_value(peer)}

    def handle_inbound(
        self,
        *,
        channel: str,
        peer_id: str,
        text: str,
        display_name: str = "",
        objective_runner: RemoteObjectiveRunner | None = None,
        status_provider: RemoteStatusProvider | None = None,
        paths_provider: RemoteStatusProvider | None = None,
        jobs_provider: RemoteStatusProvider | None = None,
    ) -> dict[str, Any]:
        channel = channel.strip().lower() or "webhook"
        peer_id = peer_id.strip()
        text = text.strip()
        if not peer_id:
            return {"ok": False, "error": "peer_id is required"}
        if not text:
            return {"ok": False, "error": "text is required"}
        data = self._load()
        policy = RemotePolicy(**{**RemotePolicy().to_dict(), **data.get("policy", {})})
        if not policy.enabled:
            return {"ok": False, "error": "Remote control is disabled."}
        peer_key = _stable_id(channel, peer_id)
        peer = data["peers"].get(peer_key)
        if not isinstance(peer, dict) or peer.get("status") != "paired":
            pairing = self.create_pairing(channel=channel, peer_id=peer_id, display_name=display_name)
            reply = build_outbound_reply(
                channel,
                peer_id,
                f"Pair this sender in Ghost Console using code {pairing['pairing']['pairing_code']}.",
            )
            return {
                "ok": False,
                "paired": False,
                "pairing_required": True,
                "message": reply.text,
                "pairing": pairing["pairing"],
                "reply_preview": reply.to_dict(),
            }
        peer["last_seen"] = _now()
        data["peers"][peer_key] = peer
        self._save(data)

        command, argument = _parse_command(text)
        if command not in policy.allowed_commands:
            self._event("remote_command_rejected", {"peer_id": peer_key, "command": command, "reason": "not_allowed"})
            return self._with_reply(
                {"ok": False, "paired": True, "error": f"Command {command} is not allowed.", "command": command},
                peer,
                f"Command {command} is not allowed.",
            )
        if command == "/help":
            message = "Allowed commands: " + ", ".join(policy.allowed_commands)
            return self._with_reply({"ok": True, "paired": True, "command": command, "message": message}, peer, message)
        if command in {"/status", "/readiness"}:
            payload = status_provider() if status_provider else {"ok": True, "status": "remote control online"}
            self._event("remote_status_requested", {"peer_id": peer_key, "command": command})
            return self._with_reply(
                {"ok": True, "paired": True, "command": command, "response": _redact_value(payload)},
                peer,
                _summarize_reply(command, payload),
            )
        if command == "/paths":
            payload = paths_provider() if paths_provider else {"ok": True, "paths": []}
            self._event("remote_paths_requested", {"peer_id": peer_key})
            return self._with_reply(
                {"ok": True, "paired": True, "command": command, "response": _redact_value(payload)},
                peer,
                _summarize_reply(command, payload),
            )
        if command == "/jobs":
            payload = jobs_provider() if jobs_provider else {"ok": True, "jobs": []}
            self._event("remote_jobs_requested", {"peer_id": peer_key})
            return self._with_reply(
                {"ok": True, "paired": True, "command": command, "response": _redact_value(payload)},
                peer,
                _summarize_reply(command, payload),
            )
        if command == "/stop":
            self._event("remote_stop_requested", {"peer_id": peer_key, "channel": channel})
            return self._with_reply(
                {"ok": True, "paired": True, "command": command, "message": "Stop request recorded."},
                peer,
                "Stop request recorded.",
            )
        if command == "/run":
            if not argument:
                return self._with_reply(
                    {"ok": False, "paired": True, "error": "Usage: /run <objective>", "command": command},
                    peer,
                    "Usage: /run <objective>",
                )
            return self._handle_run_command(
                data=data,
                policy=policy,
                peer=peer,
                command=command,
                objective=argument,
                objective_runner=objective_runner,
            )
        if command in {"/approve", "/deny"}:
            if not argument:
                return self._with_reply(
                    {"ok": False, "paired": True, "error": f"Usage: {command} <approval_id>", "command": command},
                    peer,
                    f"Usage: {command} <approval_id>",
                )
            return self.resolve_approval(
                argument.split()[0],
                approved=command == "/approve",
                objective_runner=objective_runner,
                resolver_peer_id=peer_key,
            )
        return self._with_reply(
            {"ok": False, "paired": True, "error": f"Unsupported command: {command}", "command": command},
            peer,
            f"Unsupported command: {command}",
        )

    def _with_reply(self, payload: dict[str, Any], peer: dict[str, Any], text: str) -> dict[str, Any]:
        reply = build_outbound_reply(str(peer.get("channel") or "webhook"), str(peer.get("peer_id") or ""), text)
        payload["reply_preview"] = reply.to_dict()
        return payload

    def _handle_run_command(
        self,
        *,
        data: dict[str, Any],
        policy: RemotePolicy,
        peer: dict[str, Any],
        command: str,
        objective: str,
        objective_runner: RemoteObjectiveRunner | None,
    ) -> dict[str, Any]:
        peer_allows_direct = bool(peer.get("allow_direct_execution"))
        can_execute = (
            policy.direct_execution_enabled
            and peer_allows_direct
            and command in set(policy.direct_execution_commands)
            and objective_runner is not None
        )
        if can_execute:
            result = objective_runner(objective)
            self._event(
                "remote_direct_execution",
                {"peer_id": peer.get("id"), "command": command, "objective_preview": objective[:160], "ok": result.get("ok")},
            )
            return self._with_reply(
                {
                    "ok": bool(result.get("ok", True)),
                    "paired": True,
                    "command": command,
                    "mode": "direct_execution",
                    "result": _redact_value(result),
                },
                peer,
                "Remote objective executed." if result.get("ok", True) else "Remote objective failed.",
            )
        approval = RemoteApproval(
            id=_stable_id(str(peer.get("id")), command, objective, str(_now())),
            channel=str(peer.get("channel") or ""),
            peer_id=str(peer.get("peer_id") or ""),
            command=command,
            objective=objective,
        )
        data["approvals"][approval.id] = approval.to_dict()
        self._save(data)
        self._event(
            "remote_approval_requested",
            {"approval_id": approval.id, "peer_id": peer.get("id"), "objective_preview": objective[:160]},
        )
        return self._with_reply(
            {
                "ok": True,
                "paired": True,
                "command": command,
                "mode": "approval_required",
                "approval": approval.to_dict(),
                "message": "Run request queued for dashboard approval.",
            },
            peer,
            f"Run request queued for dashboard approval. Approval id: {approval.id}",
        )

    def resolve_approval(
        self,
        approval_id: str,
        *,
        approved: bool,
        objective_runner: RemoteObjectiveRunner | None = None,
        resolver_peer_id: str = "",
    ) -> dict[str, Any]:
        data = self._load()
        approval = data["approvals"].get(approval_id)
        if not isinstance(approval, dict):
            return {"ok": False, "error": "Remote approval not found."}
        if approval.get("status") != "pending":
            return {"ok": False, "error": "Remote approval is no longer pending.", "approval": _redact_value(approval)}
        if not approved:
            approval["status"] = "denied"
            approval["resolved_at"] = _now()
            data["approvals"][approval_id] = approval
            self._save(data)
            self._event("remote_approval_denied", {"approval_id": approval_id, "resolver_peer_id": resolver_peer_id})
            return {"ok": True, "approval": _redact_value(approval), "message": "Approval denied."}
        result = {"ok": True, "skipped": True, "message": "Approved without runner."}
        if objective_runner is not None:
            result = objective_runner(str(approval.get("objective") or ""))
        approval["status"] = "executed" if result.get("ok", True) else "failed"
        approval["resolved_at"] = _now()
        approval["result"] = _redact_value(result)
        data["approvals"][approval_id] = approval
        self._save(data)
        self._event(
            "remote_approval_executed",
            {"approval_id": approval_id, "resolver_peer_id": resolver_peer_id, "ok": result.get("ok")},
        )
        return {"ok": bool(result.get("ok", True)), "approval": _redact_value(approval), "result": _redact_value(result)}


def _parse_command(text: str) -> tuple[str, str]:
    cleaned = text.strip()
    if not cleaned.startswith("/"):
        return "/run", cleaned
    parts = cleaned.split(maxsplit=1)
    command = parts[0].strip().lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    return command, argument
