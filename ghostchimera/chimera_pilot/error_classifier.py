"""Error classifier — taxonomy, auto-recovery from LLM/provider errors.

Patterns adapted from Hermes-Agent's ErrorClassifier (Nous Research, MIT licensed).
Extends the inline ErrorClassifier from agent_loop.py into a full taxonomy
with rule-based classification, auto-recovery planning, and severity scoring.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..logging_config import get_logger

logger = get_logger("error_classifier")

# ---------------------------------------------------------------------------
# Error categories
# ---------------------------------------------------------------------------

class ErrorCategory(StrEnum):
    RATE_LIMIT = "rate_limit"
    INSUFFICIENT_QUOTA = "insufficient_quota"
    CONTEXT_LENGTH = "context_length"
    MODEL_NOT_FOUND = "model_not_found"
    AUTHENTICATION = "authentication"
    OVERLOADED = "overloaded"
    TIMEOUT = "timeout"
    INVALID_REQUEST = "invalid_request"
    SERVER_ERROR = "server_error"
    MALFORMED_RESPONSE = "malformed_response"
    CONNECTION = "connection"
    SECURITY = "security"
    DEFAULT = "default"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Classification result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RecoveryAction:
    """A single recovery action."""
    action: str
    detail: str = ""
    priority: int = 0  # lower = higher priority


@dataclass(frozen=True)
class AutoRecoveryPlan:
    """Recommended recovery actions for an error."""
    categories: list[ErrorCategory]
    severity: Severity
    message: str
    actions: list[RecoveryAction] = field(default_factory=list)
    is_recoverable: bool = True
    retry: bool = False
    backoff_seconds: float = 0.0
    switch_model: bool = False
    compress: bool = False
    requires_user_action: bool = False

    @property
    def recommended_action(self) -> str:
        if self.actions:
            return self.actions[0].action
        return "investigate"


# ---------------------------------------------------------------------------
# Error classifier
# ---------------------------------------------------------------------------

class ErrorClassifier:
    """Classify LLM/provider errors and recommend recovery strategies.

    Supports rule-based classification with regex patterns and custom
    predicates. Builds auto-recovery plans based on error taxonomy.
    """

    # Built-in rule: (regex_or_text, ErrorCategory, RecoveryAction defaults)
    DEFAULT_RULES: list[tuple[str, ErrorCategory, dict[str, Any]]] = [
        (
            r'(rate[_\s-]?limit|too many requests|429)',
            ErrorCategory.RATE_LIMIT,
            {"retry": True, "backoff_seconds": 5.0, "severity": Severity.MEDIUM},
        ),
        (
            r'(insufficient[_\s-]?quota|billing[_\s-]?limit|account limit|quota exceeded)',
            ErrorCategory.INSUFFICIENT_QUOTA,
            {"retry": False, "severity": Severity.CRITICAL, "requires_user_action": True},
        ),
        (
            r'(context[_\s-]?length|token[_\s-]?limit|max[_\s-]?tokens|context[_\s-]?window|length[_\s-]?exceeded)',
            ErrorCategory.CONTEXT_LENGTH,
            {"retry": False, "compress": True, "severity": Severity.HIGH},
        ),
        (
            r'(model[_\s-]?not[_\s-]?found|model[_\s-]?unavailable|does[_\s-]?not[_\s-]?exist|404)',
            ErrorCategory.MODEL_NOT_FOUND,
            {"retry": False, "switch_model": True, "severity": Severity.MEDIUM},
        ),
        (
            r'(auth|unauthorized|401|invalid[_\s-]?api[_\s-]?key|authentication[_\s-]?failed)',
            ErrorCategory.AUTHENTICATION,
            {"retry": False, "severity": Severity.CRITICAL, "requires_user_action": True},
        ),
        (
            r'(overloaded|server[_\s-]?error|50[0-3]|service[_\s-]?unavailable)',
            ErrorCategory.OVERLOADED,
            {"retry": True, "backoff_seconds": 10.0, "severity": Severity.MEDIUM},
        ),
        (
            r'(timeout|timed[_\s-]?out|deadline[_\s-]?exceeded|ETIMEDOUT|110)',
            ErrorCategory.TIMEOUT,
            {"retry": True, "backoff_seconds": 15.0, "severity": Severity.HIGH},
        ),
        (
            r'(invalid[_\s-]?request|invalid[_\s-]?body|schema[_\s-]?violation|400)',
            ErrorCategory.INVALID_REQUEST,
            {"retry": False, "severity": Severity.HIGH, "requires_user_action": True},
        ),
        (
            r'(50[4-9]|5[2-9][0-9]|5[6-9][0-9]|gateway[_\s-]?timeout)',
            ErrorCategory.SERVER_ERROR,
            {"retry": True, "backoff_seconds": 30.0, "severity": Severity.HIGH},
        ),
        (
            r'(malformed|parse[_\s-]?error|unexpected[_\s-]?token|json[_\s-]?decode)',
            ErrorCategory.MALFORMED_RESPONSE,
            {"retry": True, "backoff_seconds": 2.0, "severity": Severity.MEDIUM},
        ),
        (
            r'(connection[_\s-]?(?:refused|reset|abort|closed|timed)?|ECONNREFUSED|ECONNRESET|ENOTFOUND)',
            ErrorCategory.CONNECTION,
            {"retry": True, "backoff_seconds": 10.0, "severity": Severity.HIGH},
        ),
        (
            r'(injection|poisoning|sandbox|forbidden|blocked|sanitized)',
            ErrorCategory.SECURITY,
            {"retry": False, "severity": Severity.CRITICAL, "requires_user_action": True},
        ),
    ]

    def __init__(self):
        self._rules: list[tuple[str, ErrorCategory, dict[str, Any]]] = list(self.DEFAULT_RULES)
        self._predicates: list[tuple[Callable[[str, str | None], bool], ErrorCategory, dict[str, Any]]] = []

    def register_rule(
        self,
        pattern: str,
        category: ErrorCategory,
        actions: dict[str, Any] | None = None,
    ) -> None:
        """Register a custom classification rule."""
        self._rules.append((pattern, category, actions or {}))

    def register_predicate(
        self,
        predicate: Callable[[str, str | None], bool],
        category: ErrorCategory,
        actions: dict[str, Any] | None = None,
    ) -> None:
        """Register a custom predicate-based rule."""
        self._predicates.append((predicate, category, actions or {}))

    def classify(self, error_msg: str, error_type: str | None = None) -> AutoRecoveryPlan:
        """Classify an error and build a recovery plan."""
        full_text = f"{error_type or ''} {error_msg}".lower()

        # Check predicates first (higher priority than regex)
        for pred, category, actions in self._predicates:
            try:
                if pred(error_msg, error_type):
                    return self._build_plan(category, actions, full_text)
            except Exception:
                continue

        # Check regex rules
        for pattern, category, actions in self._rules:
            if pattern in full_text or re.search(pattern, full_text, re.IGNORECASE):
                return self._build_plan(category, actions, full_text)

        # Default: unclassified
        return AutoRecoveryPlan(
            categories=[ErrorCategory.DEFAULT],
            severity=Severity.HIGH,
            message=f"Unclassified error: {error_msg[:200]}",
            is_recoverable=False,
        )

    def classify_multi(self, errors: list[tuple[str, str | None]]) -> list[AutoRecoveryPlan]:
        """Classify multiple errors."""
        return [self.classify(msg, err_type) for msg, err_type in errors]

    def taxonomy(self) -> dict[str, dict]:
        """Return the full taxonomy."""
        return {cat.value: {
            "patterns": [r for r, c, _ in self._rules if c == cat],
            "is_recoverable": any(
                True for _, c, a in self._rules if c == cat
            ),
        } for cat in ErrorCategory if cat != ErrorCategory.DEFAULT}

    def _build_plan(
        self,
        category: ErrorCategory,
        actions: dict[str, Any],
        full_text: str,
    ) -> AutoRecoveryPlan:
        severity = Severity(actions.get("severity", Severity.MEDIUM))
        action_list: list[RecoveryAction] = []

        if actions.get("retry"):
            backoff = actions.get("backoff_seconds", 5.0)
            action_list.append(RecoveryAction(
                action="retry_with_backoff",
                detail=f"Wait {backoff}s before retrying",
                priority=1,
            ))

        if actions.get("switch_model"):
            action_list.append(RecoveryAction(
                action="switch_model",
                detail="Switch to fallback model provider",
                priority=2,
            ))

        if actions.get("compress"):
            action_list.append(RecoveryAction(
                action="compress_context",
                detail="Compress conversation context to free tokens",
                priority=3,
            ))

        if actions.get("requires_user_action"):
            action_list.append(RecoveryAction(
                action="require_user_action",
                detail="User must resolve the issue manually",
                priority=0,
            ))

        if not action_list:
            action_list.append(RecoveryAction(
                action="investigate",
                detail="Manual investigation required",
                priority=5,
            ))

        return AutoRecoveryPlan(
            categories=[category],
            severity=severity,
            message=f"{category.value}: {full_text[:200]}",
            actions=action_list,
            is_recoverable=actions.get("retry", False) or actions.get("switch_model", False) or actions.get("compress", False),
            retry=actions.get("retry", False),
            backoff_seconds=actions.get("backoff_seconds", 0.0),
            switch_model=actions.get("switch_model", False),
            compress=actions.get("compress", False),
            requires_user_action=actions.get("requires_user_action", False),
        )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

_default_classifier: ErrorClassifier | None = None


def get_classifier() -> ErrorClassifier:
    """Get the default error classifier."""
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = ErrorClassifier()
    return _default_classifier


__all__ = [
    "ErrorClassifier",
    "ErrorCategory",
    "Severity",
    "RecoveryAction",
    "AutoRecoveryPlan",
    "get_classifier",
]
