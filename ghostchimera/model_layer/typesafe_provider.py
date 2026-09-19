"""TypeSafe System-One judgment provider (secondary model provider).

TypeSafe's Jev model is not a chat model: it answers typed judgments
(Choice / Score / Noul) with calibrated probabilities over structured
state. This module bridges it to Ghost Chimera's native
:mod:`ghostchimera.stealth.system_one` types, so a model-backed judge can
score the same questions the deterministic scorers answer — useful for
calibration checks and high-stakes confirmations.

Set ``TYPESAFE_API_KEY`` (from https://typesafe.ai) and optionally
``TYPESAFE_MODEL`` (default ``jev-latest``). All HTTP uses stdlib
``urllib``; no new dependencies.

Usage::

    from ghostchimera.model_layer.typesafe_provider import TypeSafeJudge
    from ghostchimera.stealth.system_one import NoulQuestion

    judge = TypeSafeJudge()
    if judge.available:
        answers = judge.judge(
            {"message": "Please refund the duplicate charge."},
            {"refund_requested": NoulQuestion(instructions="Does the customer request a refund?")},
        )
"""

from __future__ import annotations

import json
import os
import ssl
from typing import Any
from urllib import request as urllib_request

from ..logging_config import get_logger

logger = get_logger("typesafe_provider")

DEFAULT_MODEL = "jev-latest"
DEFAULT_BASE_URL = "https://api.typesafe.ai/v1/systemone"
KEY_ENV_VAR = "TYPESAFE_API_KEY"
MODEL_ENV_VAR = "TYPESAFE_MODEL"


class TypeSafeJudge:
    """Model-backed judge for System-One questions via the TypeSafe API."""

    name = "typesafe"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.environ.get(KEY_ENV_VAR, "")
        self.model = model or os.environ.get(MODEL_ENV_VAR, DEFAULT_MODEL)
        self.base_url = base_url or DEFAULT_BASE_URL
        self.timeout_seconds = timeout_seconds
        self.available = bool(self.api_key)

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not self.api_key:
            errors.append(f"{KEY_ENV_VAR} is not set (get one at https://typesafe.ai)")
        if not self.model:
            errors.append(f"{MODEL_ENV_VAR} must be non-empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "available": self.available, "model": self.model}

    def judge(
        self,
        state: dict[str, Any] | str | list[Any],
        questions: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate System-One *questions* against *state* via the API.

        *questions* are :mod:`ghostchimera.stealth.system_one` question
        objects; the returned dict maps ids to native answer objects.
        Raises ``RuntimeError`` when unavailable or the call fails.
        """
        from ..stealth.system_one import (  # lazy: model_layer must not import stealth at module level
            ChoiceQuestion,
            NoulQuestion,
            ScoreQuestion,
            answer_choice,
            answer_noul,
            answer_score,
        )

        if not self.available:
            raise RuntimeError(f"TypeSafeJudge is not available; set {KEY_ENV_VAR} in the environment")
        if not questions:
            return {}
        payload_questions: dict[str, Any] = {}
        for question_id, question in questions.items():
            if isinstance(question, ChoiceQuestion):
                payload_questions[question_id] = {
                    "type": "choice",
                    "instructions": question.instructions,
                    "criteria": dict(question.criteria),
                }
            elif isinstance(question, ScoreQuestion):
                payload_questions[question_id] = {
                    "type": "score",
                    "instructions": question.instructions,
                    "criteria": list(question.levels),
                }
            elif isinstance(question, NoulQuestion):
                entry: dict[str, Any] = {"type": "noul", "instructions": question.instructions}
                if question.true_meaning or question.false_meaning:
                    entry["criteria"] = {"true": question.true_meaning, "false": question.false_meaning}
                payload_questions[question_id] = entry
            else:
                raise ValueError(f"Unknown question type for {question_id!r}")

        body = json.dumps({"state": state, "model": self.model, "questions": payload_questions}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        context = ssl.create_default_context()
        req = urllib_request.Request(self.base_url, data=body, headers=headers, method="POST")
        try:
            with urllib_request.urlopen(req, context=context, timeout=self.timeout_seconds) as resp:
                response_json = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"TypeSafe API call failed: {exc}") from exc

        answers_json = response_json.get("answers")
        if not isinstance(answers_json, dict):
            raise RuntimeError("TypeSafe response missing answers")
        answers: dict[str, Any] = {}
        for question_id, question in questions.items():
            raw = answers_json.get(question_id)
            if not isinstance(raw, dict):
                raise RuntimeError(f"TypeSafe response missing answer for {question_id!r}")
            if isinstance(question, ChoiceQuestion):
                probabilities = {str(k): float(v) for k, v in dict(raw.get("probabilities", {})).items()}
                answers[question_id] = answer_choice(question, probabilities)
            elif isinstance(question, ScoreQuestion):
                probabilities = {str(k): float(v) for k, v in dict(raw.get("probabilities", {})).items()}
                answers[question_id] = answer_score(question, probabilities)
            elif isinstance(question, NoulQuestion):
                answers[question_id] = answer_noul(question, float(raw.get("noul", 0.5)))
        return answers


__all__ = ["DEFAULT_BASE_URL", "DEFAULT_MODEL", "KEY_ENV_VAR", "MODEL_ENV_VAR", "TypeSafeJudge"]
