"""Google Gemini provider for Ghost Chimera.

Connects to the Google AI Studio / Gemini API using the ``generativelanguage``
REST endpoint.  No additional dependencies are required — this provider uses the
stdlib ``urllib`` package exactly like :class:`~ghostchimera.model_layer.providers.OpenAIProvider`.

Configuration
-------------
Set ``GOOGLE_API_KEY`` (from https://ai.google.dev/) and optionally
``GEMINI_MODEL`` in the environment, **or** inject an
:class:`~ghostchimera.model_layer.auth_profiles.AuthProfile`.

Supported models (June 2025)::

    gemini-2.0-flash-exp    # default — fast, 1 M token context
    gemini-1.5-pro          # largest context, vision, long documents
    gemini-1.5-flash        # faster, cheaper, 1 M tokens
    gemini-1.0-pro          # legacy

Long-context document processing
---------------------------------
``GeminiProvider.chat_long_context()`` accepts a ``documents`` list and an
instruction prompt.  It assembles a multi-part request and sets the safety
threshold to the model's declared maximum context window.  This is the primary
entrypoint for Track 2's document-processing use cases (contracts, reports,
code bases, etc.).

Multi-agent support
-------------------
``GeminiProvider.multi_agent_chat()`` accepts a ``history`` list of
``{"role": ..., "parts": [...]}`` turns and appends a new user turn, enabling
multi-turn agent workflows.

Usage::

    from ghostchimera.model_layer.gemini_provider import GeminiProvider

    provider = GeminiProvider()            # uses GOOGLE_API_KEY + GEMINI_MODEL
    response = provider.chat("You are helpful.", "Explain RAG in 2 sentences.")

    long_resp = provider.chat_long_context(
        instruction="Summarise each document in one bullet point.",
        documents=["<doc1 text>", "<doc2 text>"],
    )
"""

from __future__ import annotations

import json
import os
import ssl
from typing import TYPE_CHECKING, Any
from urllib import request as urllib_request

from ..logging_config import get_logger

if TYPE_CHECKING:
    from .auth_profiles import AuthProfile

logger = get_logger("gemini_provider")


class GeminiProvider:
    """Provider that connects to the Google AI Studio / Gemini API.

    Compatible with the :class:`~ghostchimera.model_layer.providers.BaseProvider`
    interface: implements :meth:`chat`, :meth:`validate_config`, and
    :meth:`to_dict`.  Also adds :meth:`chat_long_context` and
    :meth:`multi_agent_chat` for Track 2 use cases.
    """

    name = "gemini"
    _API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
    _DEFAULT_MODEL = "gemini-2.0-flash-exp"
    _DEFAULT_MAX_OUTPUT_TOKENS = 2048

    def __init__(self, profile: AuthProfile | None = None) -> None:
        if profile is not None:
            self.api_key = profile.api_key or profile.oauth_token or os.environ.get("GOOGLE_API_KEY", "")
            self.model = profile.model or os.environ.get("GEMINI_MODEL", self._DEFAULT_MODEL)
        else:
            self.api_key = os.environ.get("GOOGLE_API_KEY", "")
            self.model = os.environ.get("GEMINI_MODEL", self._DEFAULT_MODEL)
        self.available = bool(self.api_key)
        logger.debug("Provider %s model=%s initialized", self.name, self.model)

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not self.api_key:
            errors.append("GOOGLE_API_KEY is not set (get one at https://ai.google.dev/)")
        if not self.model:
            errors.append("GEMINI_MODEL must be non-empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "model": self.model,
        }

    def chat(self, system_message: str, user_message: str) -> str:
        """Single-turn chat completion via the Gemini generateContent endpoint.

        The Gemini REST API does not have a dedicated system role; the system
        message is prepended to the user message with a clear separator.
        """
        if not self.available:
            raise RuntimeError("GeminiProvider is not available; set GOOGLE_API_KEY in the environment")
        combined_prompt = f"{system_message}\n\n---\n\n{user_message}" if system_message else user_message
        contents = [{"role": "user", "parts": [{"text": combined_prompt}]}]
        return self._generate(contents)

    # ------------------------------------------------------------------
    # Track 2 extensions
    # ------------------------------------------------------------------

    def chat_long_context(
        self,
        instruction: str,
        *,
        documents: list[str] | None = None,
        history: list[dict[str, Any]] | None = None,
        max_output_tokens: int | None = None,
    ) -> str:
        """Process long-context document(s) with a Gemini model.

        Assembles a multi-part Gemini request: all ``documents`` are prepended
        as separate text parts before the ``instruction`` prompt.  Gemini 1.5 Pro
        and Gemini 2.0 Flash support up to 1 000 000 input tokens, making this
        suitable for full-contract, report, or codebase analysis.

        Parameters
        ----------
        instruction:
            The task description / question to answer over the documents.
        documents:
            List of document text strings.  Each is added as a separate
            ``text`` part in the Gemini request.
        history:
            Optional prior conversation turns (``{"role": ..., "parts": [...]}``).
        max_output_tokens:
            Override the default output token budget.
        """
        if not self.available:
            raise RuntimeError("GeminiProvider is not available; set GOOGLE_API_KEY in the environment")

        contents: list[dict[str, Any]] = list(history or [])

        # Build parts for this turn: documents first, then the instruction
        parts: list[dict[str, str]] = []
        for i, doc in enumerate(documents or []):
            parts.append({"text": f"[Document {i + 1}]\n{doc}\n"})
        parts.append({"text": instruction})
        contents.append({"role": "user", "parts": parts})

        return self._generate(
            contents,
            max_output_tokens=max_output_tokens or self._DEFAULT_MAX_OUTPUT_TOKENS,
        )

    def multi_agent_chat(
        self,
        history: list[dict[str, Any]],
        *,
        new_message: str,
        agent_role: str = "user",
        system_context: str = "",
    ) -> tuple[str, list[dict[str, Any]]]:
        """Append *new_message* to *history* and return the model reply + updated history.

        Designed for multi-agent loops where agents exchange messages and the
        full history is passed in each turn.

        Parameters
        ----------
        history:
            Prior conversation turns in Gemini format
            (``[{"role": "user"|"model", "parts": [{"text": ...}]}]``).
        new_message:
            The new message to append.
        agent_role:
            Role for the new message (``"user"`` or ``"model"``).
        system_context:
            Optional system/context preamble prepended to the first user turn.

        Returns
        -------
        tuple[str, list]:
            ``(reply_text, updated_history)`` where *updated_history* includes
            the new user turn and the model's reply turn, ready for the next
            call.
        """
        if not self.available:
            raise RuntimeError("GeminiProvider is not available; set GOOGLE_API_KEY in the environment")

        contents = list(history)

        if system_context and not contents:
            contents.append({"role": "user", "parts": [{"text": f"[Context]\n{system_context}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})

        contents.append({"role": agent_role, "parts": [{"text": new_message}]})
        reply = self._generate(contents)
        contents.append({"role": "model", "parts": [{"text": reply}]})
        return reply, contents

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    def _generate(
        self,
        contents: list[dict[str, Any]],
        *,
        max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> str:
        """POST to the Gemini generateContent endpoint and return the text."""
        url = f"{self._API_BASE}/{self.model}:generateContent?key={self.api_key}"
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_output_tokens,
                "temperature": 0.0,
            },
        }
        data = json.dumps(body).encode("utf-8")
        ctx = ssl.create_default_context()
        req = urllib_request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(req, context=ctx) as resp:
            response_json = json.loads(resp.read().decode("utf-8"))

        candidates = response_json.get("candidates")
        if not candidates:
            error = response_json.get("error", {})
            raise RuntimeError(f"Gemini API error: {error.get('message', response_json)}")
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            raise RuntimeError("Gemini response has no parts")
        return "".join(p.get("text", "") for p in parts).strip()


__all__ = ["GeminiProvider"]
