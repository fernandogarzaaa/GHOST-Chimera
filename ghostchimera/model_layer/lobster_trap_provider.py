"""Lobster Trap provider wrapper for Ghost Chimera.

Wraps any :class:`~ghostchimera.model_layer.providers.BaseProvider` and gates
every ``chat()`` call through the Lobster Trap DPI inspection pipeline.  Blocked
calls raise :class:`LobsterTrapViolation` instead of reaching the underlying
provider, ensuring adversarial prompts never touch the LLM backend.

Usage::

    from ghostchimera.model_layer.lobster_trap_provider import LobsterTrapProvider
    from ghostchimera.model_layer.providers import OpenAIProvider
    from ghostchimera.safety_layer.lobster_trap import LobsterTrapConfig

    config = LobsterTrapConfig(enabled=True)
    provider = LobsterTrapProvider(OpenAIProvider(), config=config)
    response = provider.chat("You are helpful.", "Summarise the paper")
    # raises LobsterTrapViolation if injection / exfiltration detected
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..logging_config import get_logger
from ..safety_layer.lobster_trap import LobsterTrapConfig, LobsterTrapInspector
from .providers import BaseProvider

if TYPE_CHECKING:
    pass

logger = get_logger("lobster_trap_provider")


class LobsterTrapViolation(PermissionError):
    """Raised when the DPI engine blocks a prompt or response."""


class LobsterTrapProvider(BaseProvider):
    """DPI-gated provider wrapper.

    Wraps any ``BaseProvider`` and routes every ``chat()`` call through the
    Lobster Trap inspection pipeline.  Blocked calls raise
    :class:`LobsterTrapViolation`; passing calls are forwarded transparently.

    Parameters
    ----------
    inner:
        The underlying provider to wrap.
    config:
        Lobster Trap configuration.  When ``None`` the config is loaded from
        environment variables via :meth:`LobsterTrapConfig.from_env`.
    session_id:
        Optional correlation ID attached to every security event.
    declared_intent:
        Intent label the agent declares for this session (used for
        declared-vs-detected mismatch detection).
    """

    name = "lobster_trap"

    def __init__(
        self,
        inner: BaseProvider,
        *,
        config: LobsterTrapConfig | None = None,
        session_id: str = "",
        declared_intent: str | None = None,
    ) -> None:
        self._inner = inner
        self._config = config or LobsterTrapConfig.from_env()
        self._inspector = LobsterTrapInspector(self._config)
        self._session_id = session_id
        self._declared_intent = declared_intent
        self.available = inner.available

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    def validate_config(self) -> list[str]:
        return self._inner.validate_config()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "available": self.available,
            "inner": self._inner.to_dict() if hasattr(self._inner, "to_dict") else self._inner.name,
            "lobster_trap": {
                "enabled": self._config.enabled,
                "proxy_url": self._config.proxy_url if self._config.enabled else None,
                "fail_open": self._config.fail_open,
            },
        }
        return d

    def chat(self, system_message: str, user_message: str) -> str:
        """Gate *system_message* + *user_message* through DPI then delegate.

        Raises :class:`LobsterTrapViolation` if the DPI engine blocks the
        prompt.  The response is also inspected for credential/exfiltration
        content before being returned to the caller.
        """
        combined = f"{system_message}\n{user_message}"
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
        model = getattr(self._inner, "model", "unknown")

        # --- inspect prompt ---
        prompt_result = self._inspector.inspect_prompt(
            combined,
            declared_intent=self._declared_intent,
            session_id=self._session_id,
            messages=messages,
            model=str(model),
        )
        if not prompt_result.allowed:
            raise LobsterTrapViolation(
                f"Prompt blocked by DPI [{prompt_result.action}]: {', '.join(prompt_result.threats[:5])}"
            )

        # --- forward to real provider ---
        response = self._inner.chat(system_message, user_message)

        # --- inspect response ---
        response_result = self._inspector.inspect_prompt(
            response,
            declared_intent=self._declared_intent,
            session_id=self._session_id,
        )
        if not response_result.allowed:
            logger.warning(
                "Response blocked by DPI [%s] risk=%.2f threats=%s",
                response_result.action,
                response_result.risk_score,
                response_result.threats[:5],
            )
            raise LobsterTrapViolation(
                f"Response blocked by DPI [{response_result.action}]: {', '.join(response_result.threats[:5])}"
            )

        return response


__all__ = ["LobsterTrapProvider", "LobsterTrapViolation"]
