"""Lobster Trap DPI Integration for Ghost Chimera.

Lobster Trap (MIT, https://github.com/veeainc/lobstertrap) is a deep prompt
inspection (DPI) proxy that sits between an agent and any OpenAI-compatible
LLM backend.  It enforces YAML policy rules on every prompt and response and
emits structured metadata about intent, risk scoring, PII, injection patterns,
credential exposure, and exfiltration attempts.

This module provides two operating modes:

1. **Built-in DPI engine** (``BuiltinDPIEngine``) — works with zero external
   dependencies.  Runs the same pattern-based extraction logic that Lobster
   Trap uses internally, producing the same ``DPIResult`` shape.  Suitable for
   development, testing, and deployments where the proxy is not running.

2. **Proxy delegation** — when ``LobsterTrapConfig.proxy_url`` is set and
   reachable, ``LobsterTrapInspector`` forwards LLM calls to the proxy and
   parses ``_lobstertrap`` metadata from the response.  This gives the full
   Lobster Trap experience including YAML-based policy enforcement,
   bidirectional intent inspection, and production-grade dashboards.

Configuration (environment variables)::

    GHOSTCHIMERA_LOBSTERTRAP_ENABLED=1
    GHOSTCHIMERA_LOBSTERTRAP_URL=http://localhost:4000/v1/chat/completions
    GHOSTCHIMERA_LOBSTERTRAP_FAIL_OPEN=1   # allow through if proxy unreachable
    GHOSTCHIMERA_LOBSTERTRAP_TIMEOUT=5     # proxy request timeout seconds

Usage::

    from ghostchimera.safety_layer.lobster_trap import LobsterTrapInspector

    inspector = LobsterTrapInspector.from_env()
    result = inspector.inspect_prompt("explain quantum computing", session_id="s1")
    if not result.allowed:
        raise PermissionError(f"Prompt blocked: {result.threats}")
"""

from __future__ import annotations

import json
import os
import re
import ssl
import time
from dataclasses import dataclass, field
from typing import Any
from urllib import request as urllib_request
from urllib.error import URLError

from ..logging_config import get_logger

logger = get_logger("lobster_trap")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LobsterTrapConfig:
    """Runtime configuration for the Lobster Trap integration.

    All fields can be overridden via environment variables — see
    :meth:`from_env` for the mapping.
    """

    enabled: bool = False
    """Enable DPI inspection on every LLM call."""

    proxy_url: str = "http://localhost:4000/v1/chat/completions"
    """URL of a running Lobster Trap proxy (OpenAI-compatible endpoint)."""

    fail_open: bool = True
    """When the proxy is unreachable, allow the call through (True) or block it (False)."""

    timeout_seconds: int = 5
    """Proxy request timeout in seconds."""

    use_builtin_engine: bool = True
    """Always run the built-in pattern-based engine, even when proxy is enabled.

    The proxy result takes precedence when available; the builtin engine is the
    fallback and the standalone mode when no proxy is configured.
    """

    declared_intent_header: str = "ghostchimera-agent"
    """Value placed in the ``_lobstertrap.requester`` field of proxy requests."""

    @classmethod
    def from_env(cls) -> LobsterTrapConfig:
        return cls(
            enabled=_truthy(os.environ.get("GHOSTCHIMERA_LOBSTERTRAP_ENABLED")),
            proxy_url=os.environ.get(
                "GHOSTCHIMERA_LOBSTERTRAP_URL",
                "http://localhost:4000/v1/chat/completions",
            ),
            fail_open=_truthy(os.environ.get("GHOSTCHIMERA_LOBSTERTRAP_FAIL_OPEN", "1")),
            timeout_seconds=int(os.environ.get("GHOSTCHIMERA_LOBSTERTRAP_TIMEOUT", "5")),
            use_builtin_engine=True,
        )


# ---------------------------------------------------------------------------
# DPI result shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DPIResult:
    """Structured output from deep prompt inspection.

    Mirrors the ``_lobstertrap`` metadata block returned by the Lobster Trap
    proxy so that application code can use a single shape regardless of whether
    the proxy is running.
    """

    allowed: bool = True
    """Whether the content is permitted by policy."""

    risk_score: float = 0.0
    """Composite risk score in [0.0, 1.0]."""

    intent_category: str = "general"
    """High-level intent bucket (e.g. ``answer_question``, ``code_gen``,
    ``data_exfiltration``, ``role_escalation``)."""

    declared_intent: str | None = None
    """Intent declared by the caller in the request metadata."""

    detected_intent: str | None = None
    """Intent inferred from prompt content by the DPI engine."""

    intent_mismatch: bool = False
    """True when declared and detected intents differ materially."""

    injection_detected: bool = False
    """True when a prompt-injection pattern is detected."""

    pii_detected: bool = False
    """True when personally identifiable information is present."""

    exfiltration_detected: bool = False
    """True when data exfiltration patterns are detected."""

    credential_detected: bool = False
    """True when API keys, tokens, or other secrets are present."""

    threats: list[str] = field(default_factory=list)
    """Human-readable threat descriptions."""

    action: str = "ALLOW"
    """Policy action: ALLOW | DENY | LOG | HUMAN_REVIEW | QUARANTINE | RATE_LIMIT."""

    rule_matched: str | None = None
    """Name of the first YAML rule that matched, if any."""

    engine: str = "builtin"
    """Which engine produced this result: ``builtin`` or ``proxy``."""

    latency_ms: int = 0
    """Inspection latency in milliseconds."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "risk_score": round(self.risk_score, 4),
            "intent_category": self.intent_category,
            "declared_intent": self.declared_intent,
            "detected_intent": self.detected_intent,
            "intent_mismatch": self.intent_mismatch,
            "injection_detected": self.injection_detected,
            "pii_detected": self.pii_detected,
            "exfiltration_detected": self.exfiltration_detected,
            "credential_detected": self.credential_detected,
            "threats": list(self.threats),
            "action": self.action,
            "rule_matched": self.rule_matched,
            "engine": self.engine,
            "latency_ms": self.latency_ms,
        }


# ---------------------------------------------------------------------------
# Built-in DPI engine
# ---------------------------------------------------------------------------

# Prompt injection patterns — ordered by risk (highest first)
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|context)", "ignore_previous_instructions"),
    (r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|context)", "disregard_instructions"),
    (r"you\s+are\s+now\s+(a|an|the)\s+\w", "role_override"),
    (r"new\s+(system\s+)?prompt\s*:", "new_system_prompt"),
    (r"(override|bypass|circumvent)\s+(your\s+)?(safety|guardrail|policy|filter|rule)", "safety_bypass"),
    (r"act\s+as\s+(if\s+you\s+are|a|an|the)\s+\w", "act_as_persona"),
    (r"forget\s+(everything|all)\s+(you\s+)?(know|were\s+told|learned)", "forget_instructions"),
    (r"jailbreak", "jailbreak"),
    (r"DAN\s*(mode|prompt|\b)", "dan_jailbreak"),
    (r"developer\s+mode\s*(enabled|on|activated)", "developer_mode"),
    (r"(print|reveal|show|tell\s+me|output)\s+(your\s+)?(system\s+prompt|instructions?|directives?|rules?)", "system_prompt_leak"),
    (r"</?(system|assistant|user|human|ai)>", "role_tag_injection"),
    (r"\[INST\]|\[/INST\]", "llama_instruction_injection"),
    (r"<\|im_start\|>|<\|im_end\|>", "chatml_injection"),
]

# PII patterns
_PII_PATTERNS: list[tuple[str, str]] = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "ssn"),
    (r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b", "credit_card"),
    (r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "email"),
    (r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", "phone_us"),
    (r"\bpassport\s+(number\s+)?[A-Z]{1,2}\d{6,9}\b", "passport"),
    (r"\b(date\s+of\s+birth|dob|born\s+on)\s*:?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", "dob"),
    (r"\b(patient\s+id|medical\s+record|mrn)\s*:?\s*\w{4,}", "medical_id"),
]

# Credential / secret patterns
_CREDENTIAL_PATTERNS: list[tuple[str, str]] = [
    (r"\bsk-[A-Za-z0-9]{20,}\b", "openai_api_key"),
    (r"\bsk-ant-[A-Za-z0-9]{20,}\b", "anthropic_api_key"),
    (r"\bghp_[A-Za-z0-9]{20,}\b", "github_pat"),
    (r"\bAIza[A-Za-z0-9\-_]{35}\b", "google_api_key"),
    (r"\b(AKIA|ASIA|AROA)[A-Z0-9]{16}\b", "aws_access_key"),
    (r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}", "bearer_token"),
    (r"password\s*[=:]\s*[\"']?\S{6,}", "plaintext_password"),
    (r"(?:secret|api_?key|access_?token)\s*[=:]\s*[\"']?\S{8,}", "generic_secret"),
]

# Exfiltration patterns
_EXFILTRATION_PATTERNS: list[tuple[str, str]] = [
    (r"(send|post|upload|transfer|exfil(trate)?|leak)\s+.*(to\s+)?(http|ftp|ssh|sftp|s3)", "data_upload"),
    (r"(dump|extract|export)\s+(all\s+)?(user(s)?|customer(s)?|employee(s)?|record(s)?|database)", "bulk_dump"),
    (r"curl\s+.*(-d|-T|--data|--upload-file)\s+\S+\s+https?://", "curl_exfil"),
    (r"wget\s+--post[- ]data\s+", "wget_exfil"),
    (r"base64\s+(encode|decode|--decode)\s+.*\|\s*(curl|wget|nc)", "b64_exfil"),
]

# Intent detection — coarse heuristics
_INTENT_PATTERNS: list[tuple[str, str]] = [
    (r"(write|generate|create)\s+(code|script|program|function)", "code_generation"),
    (r"(summarize|summarise|summary of)", "summarization"),
    (r"(translate|translation\s+of)", "translation"),
    (r"(search|find|look\s+up|retrieve)\s+", "information_retrieval"),
    (r"(delete|drop|truncate|wipe|destroy)\s+(table|database|file|directory)", "destructive_operation"),
    (r"(hack|exploit|attack|bypass|crack)\s+", "adversarial"),
    (r"(steal|exfiltrate|leak|dump)\s+(data|credentials?|secrets?)", "data_exfiltration"),
    (r"(escalate|elevate)\s+(privilege|permission|access|role)", "privilege_escalation"),
    (r"(impersonate|pretend\s+to\s+be|pose\s+as)\s+", "impersonation"),
]


def _compile(patterns: list[tuple[str, str]]) -> list[tuple[re.Pattern[str], str]]:
    return [(re.compile(pat, re.IGNORECASE | re.DOTALL), label) for pat, label in patterns]


_RE_INJECTION = _compile(_INJECTION_PATTERNS)
_RE_PII = _compile(_PII_PATTERNS)
_RE_CREDS = _compile(_CREDENTIAL_PATTERNS)
_RE_EXFIL = _compile(_EXFILTRATION_PATTERNS)
_RE_INTENT = _compile(_INTENT_PATTERNS)


class BuiltinDPIEngine:
    """Rule-based deep prompt inspection engine.

    Analyses text content for injection attempts, PII, credential exposure,
    and exfiltration patterns without requiring any external service.  Produces
    the same :class:`DPIResult` shape as the Lobster Trap proxy.
    """

    def inspect(
        self,
        text: str,
        *,
        declared_intent: str | None = None,
        session_id: str = "",
    ) -> DPIResult:
        """Inspect *text* and return a :class:`DPIResult`."""
        t0 = time.monotonic()

        threats: list[str] = []
        risk_score = 0.0

        # --- injection ---
        injection_detected = False
        for pattern, label in _RE_INJECTION:
            if pattern.search(text):
                injection_detected = True
                threats.append(f"prompt_injection:{label}")
                risk_score = max(risk_score, 0.85)

        # --- PII ---
        pii_detected = False
        for pattern, label in _RE_PII:
            if pattern.search(text):
                pii_detected = True
                threats.append(f"pii:{label}")
                risk_score = max(risk_score, 0.65)

        # --- credentials ---
        credential_detected = False
        for pattern, label in _RE_CREDS:
            if pattern.search(text):
                credential_detected = True
                threats.append(f"credential:{label}")
                risk_score = max(risk_score, 0.90)

        # --- exfiltration ---
        exfiltration_detected = False
        for pattern, label in _RE_EXFIL:
            if pattern.search(text):
                exfiltration_detected = True
                threats.append(f"exfiltration:{label}")
                risk_score = max(risk_score, 0.95)

        # --- intent detection ---
        detected_intent: str | None = None
        for pattern, label in _RE_INTENT:
            if pattern.search(text):
                detected_intent = label
                break
        if detected_intent is None:
            detected_intent = "general"

        intent_mismatch = bool(
            declared_intent
            and detected_intent
            and declared_intent.lower() != detected_intent.lower()
            and detected_intent in {"adversarial", "data_exfiltration", "privilege_escalation", "destructive_operation"}
        )
        if intent_mismatch:
            threats.append(f"intent_mismatch:declared={declared_intent},detected={detected_intent}")
            risk_score = max(risk_score, 0.75)

        # Determine policy action
        action = "ALLOW"
        rule_matched: str | None = None
        if exfiltration_detected or credential_detected:
            action = "DENY"
            rule_matched = "builtin:high-risk-content"
        elif injection_detected:
            action = "DENY"
            rule_matched = "builtin:prompt-injection"
        elif intent_mismatch:
            action = "HUMAN_REVIEW"
            rule_matched = "builtin:intent-mismatch"
        elif pii_detected:
            action = "LOG"
            rule_matched = "builtin:pii-detected"
        elif risk_score >= 0.5:
            action = "LOG"
            rule_matched = "builtin:elevated-risk"

        allowed = action not in {"DENY", "QUARANTINE"}
        latency_ms = int((time.monotonic() - t0) * 1000)

        return DPIResult(
            allowed=allowed,
            risk_score=risk_score,
            intent_category=detected_intent or "general",
            declared_intent=declared_intent,
            detected_intent=detected_intent,
            intent_mismatch=intent_mismatch,
            injection_detected=injection_detected,
            pii_detected=pii_detected,
            exfiltration_detected=exfiltration_detected,
            credential_detected=credential_detected,
            threats=threats,
            action=action,
            rule_matched=rule_matched,
            engine="builtin",
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# Lobster Trap proxy client
# ---------------------------------------------------------------------------


class LobsterTrapClient:
    """HTTP client that proxies chat calls through a running Lobster Trap instance.

    The proxy is an OpenAI-compatible endpoint that accepts the same request
    body with an optional ``_lobstertrap`` metadata block, enforces YAML
    policy rules, and injects ``_lobstertrap`` into the response.
    """

    def __init__(self, config: LobsterTrapConfig) -> None:
        self.config = config

    def inspect_via_proxy(
        self,
        messages: list[dict[str, str]],
        *,
        model: str = "gpt-3.5-turbo",
        declared_intent: str | None = None,
        session_id: str = "",
    ) -> DPIResult | None:
        """Forward *messages* to the proxy and parse the DPI metadata.

        Returns ``None`` when the proxy is unreachable and ``fail_open`` is
        enabled (the caller should fall through to the builtin engine).
        """
        t0 = time.monotonic()
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "_lobstertrap": {
                "requester": self.config.declared_intent_header,
                "session_id": session_id,
            },
        }
        if declared_intent:
            body["_lobstertrap"]["declared_intent"] = declared_intent

        payload = json.dumps(body).encode("utf-8")
        req = urllib_request.Request(
            self.config.proxy_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            ctx = ssl.create_default_context()
            with urllib_request.urlopen(req, context=ctx, timeout=self.config.timeout_seconds) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, TimeoutError) as exc:
            logger.debug("Lobster Trap proxy unreachable (%s); fail_open=%s", exc, self.config.fail_open)
            if self.config.fail_open:
                return None
            latency_ms = int((time.monotonic() - t0) * 1000)
            return DPIResult(
                allowed=False,
                risk_score=1.0,
                threats=["proxy_unreachable"],
                action="DENY",
                rule_matched="builtin:proxy-unavailable",
                engine="proxy",
                latency_ms=latency_ms,
            )

        latency_ms = int((time.monotonic() - t0) * 1000)
        lt_meta: dict[str, Any] = raw.get("_lobstertrap") or {}

        # If the proxy returned a standard error response with no choices, that
        # indicates the request was blocked (DENY / QUARANTINE).
        if not raw.get("choices") and not lt_meta:
            return DPIResult(
                allowed=False,
                risk_score=1.0,
                threats=["proxy_blocked"],
                action="DENY",
                rule_matched="proxy:policy",
                engine="proxy",
                latency_ms=latency_ms,
            )

        allowed = lt_meta.get("allowed", True)
        action = lt_meta.get("action", "ALLOW")
        return DPIResult(
            allowed=bool(allowed),
            risk_score=float(lt_meta.get("risk_score", 0.0)),
            intent_category=str(lt_meta.get("intent_category", "general")),
            declared_intent=declared_intent,
            detected_intent=lt_meta.get("detected_intent"),
            intent_mismatch=bool(lt_meta.get("intent_mismatch", False)),
            injection_detected=bool(lt_meta.get("injection_detected", False)),
            pii_detected=bool(lt_meta.get("pii_detected", False)),
            exfiltration_detected=bool(lt_meta.get("exfiltration_detected", False)),
            credential_detected=bool(lt_meta.get("credential_detected", False)),
            threats=list(lt_meta.get("threats", [])),
            action=action,
            rule_matched=lt_meta.get("rule_matched"),
            engine="proxy",
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# Main inspector facade
# ---------------------------------------------------------------------------


class LobsterTrapInspector:
    """Unified DPI inspector for Ghost Chimera.

    Selects the best available engine:

    * When a running Lobster Trap proxy is reachable and
      ``LobsterTrapConfig.proxy_url`` is set, delegates to the proxy.
    * Otherwise falls back to the :class:`BuiltinDPIEngine`.

    Integrates with :class:`~ghostchimera.safety_layer.security_monitor.SecurityMonitor`
    to persist security events for the governance dashboard.
    """

    def __init__(self, config: LobsterTrapConfig | None = None) -> None:
        self.config = config or LobsterTrapConfig()
        self._engine = BuiltinDPIEngine()
        self._proxy: LobsterTrapClient | None = (
            LobsterTrapClient(self.config) if self.config.proxy_url else None
        )

    @classmethod
    def from_env(cls) -> LobsterTrapInspector:
        return cls(config=LobsterTrapConfig.from_env())

    def inspect_prompt(
        self,
        text: str,
        *,
        declared_intent: str | None = None,
        session_id: str = "",
        messages: list[dict[str, str]] | None = None,
        model: str = "gpt-3.5-turbo",
    ) -> DPIResult:
        """Inspect *text* (or *messages*) and return a :class:`DPIResult`.

        When the proxy is configured and ``enabled`` is True, the call is
        forwarded to the proxy; the builtin engine is always run as a fast
        pre-check.

        Parameters
        ----------
        text:
            Plain text to inspect (the user/system message content).
        declared_intent:
            Intent the calling agent claims to have.
        session_id:
            Correlation ID for this conversation/session.
        messages:
            Full OpenAI-style message list (used when forwarding to the proxy).
        model:
            Model name passed to the proxy request.
        """
        if not self.config.enabled:
            return DPIResult(allowed=True, engine="builtin", action="ALLOW")

        # Always run the built-in engine as a fast pre-flight
        builtin_result = self._engine.inspect(
            text, declared_intent=declared_intent, session_id=session_id
        )

        # If the builtin engine already blocks, skip the proxy round-trip
        if not builtin_result.allowed:
            self._emit_security_event(builtin_result, session_id=session_id, text=text)
            return builtin_result

        # Optionally delegate to proxy for richer policy enforcement
        if self._proxy and messages:
            proxy_result = self._proxy.inspect_via_proxy(
                messages,
                model=model,
                declared_intent=declared_intent,
                session_id=session_id,
            )
            if proxy_result is not None:
                # Merge: take the stricter of the two results
                merged = _merge_results(builtin_result, proxy_result)
                self._emit_security_event(merged, session_id=session_id, text=text)
                return merged

        if builtin_result.risk_score > 0:
            self._emit_security_event(builtin_result, session_id=session_id, text=text)
        return builtin_result

    def _emit_security_event(self, result: DPIResult, *, session_id: str, text: str) -> None:
        """Forward the DPI result to the SecurityMonitor singleton."""
        try:
            from .security_monitor import SecurityEvent, ThreatCategory, get_monitor

            categories: list[ThreatCategory] = []
            if result.injection_detected:
                categories.append(ThreatCategory.PROMPT_INJECTION)
            if result.pii_detected:
                categories.append(ThreatCategory.PII_EXFILTRATION)
            if result.credential_detected:
                categories.append(ThreatCategory.CREDENTIAL_LEAK)
            if result.exfiltration_detected:
                categories.append(ThreatCategory.EXFILTRATION)
            if result.intent_mismatch:
                categories.append(ThreatCategory.INTENT_MISMATCH)
            if not result.allowed:
                categories.append(ThreatCategory.POLICY_VIOLATION)

            event = SecurityEvent(
                session_id=session_id,
                categories=categories,
                risk_score=result.risk_score,
                threats=list(result.threats),
                action=result.action,
                rule_matched=result.rule_matched,
                blocked=not result.allowed,
                text_snippet=text[:200] if text else "",
                dpi_engine=result.engine,
            )
            get_monitor().record_event(event)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Security event emission failed: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _merge_results(builtin: DPIResult, proxy: DPIResult) -> DPIResult:
    """Return the stricter of two DPI results."""
    allowed = builtin.allowed and proxy.allowed
    action = proxy.action if proxy.action in {"DENY", "QUARANTINE"} else builtin.action
    threats = list({*builtin.threats, *proxy.threats})
    risk_score = max(builtin.risk_score, proxy.risk_score)
    return DPIResult(
        allowed=allowed,
        risk_score=risk_score,
        intent_category=proxy.intent_category or builtin.intent_category,
        declared_intent=builtin.declared_intent,
        detected_intent=proxy.detected_intent or builtin.detected_intent,
        intent_mismatch=builtin.intent_mismatch or proxy.intent_mismatch,
        injection_detected=builtin.injection_detected or proxy.injection_detected,
        pii_detected=builtin.pii_detected or proxy.pii_detected,
        exfiltration_detected=builtin.exfiltration_detected or proxy.exfiltration_detected,
        credential_detected=builtin.credential_detected or proxy.credential_detected,
        threats=threats,
        action=action,
        rule_matched=proxy.rule_matched or builtin.rule_matched,
        engine="merged",
        latency_ms=builtin.latency_ms + proxy.latency_ms,
    )


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "BuiltinDPIEngine",
    "DPIResult",
    "LobsterTrapClient",
    "LobsterTrapConfig",
    "LobsterTrapInspector",
]
