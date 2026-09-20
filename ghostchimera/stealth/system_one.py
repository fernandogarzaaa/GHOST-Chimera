"""System-One style typed judgments with calibrated confidence (TypeSafe-inspired).

Fast, structured decisions for the Stealth Loop hot path: Choice (which
option), Score (position on ordered levels), Noul (yes/no probability) —
each with a full probability distribution and a spread-derived confidence,
so code can act, confirm, or escalate instead of guessing.

Deliberately dependency-free and model-free: probabilities come from
caller-supplied deterministic scorers over existing Ghost signals
(triggers, attention, friction). Confidence uses the margin-above-uniform
formula — ``(p_max - 1/n) / (1 - 1/n)`` — which reproduces TypeSafe's
published examples (0.39 on a 0.60/0.38/0.02 split, 0.53, 0.88, 1.0).

Advisory only: :func:`advise_event` observes the same signals as the loop
and reports what it *would* decide, but never changes loop decisions. Wire
it into telemetry first; promote only with decision-equality evidence.

Usage::

    from ghostchimera.stealth.system_one import (
        ChoiceQuestion, NoulQuestion, ScoreQuestion, evaluate_batch, route_on_confidence,
    )

    questions = {
        "should_attend": NoulQuestion(instructions="Does this event deserve attention?"),
        "mode": ChoiceQuestion(
            instructions="How should Ghost meet this event?",
            criteria={"witness": "...", "prepare": "...", "copilot": "...", "ghost": "..."},
        ),
    }
    answers = evaluate_batch(questions, state, scorers)
    route = route_on_confidence(answers["mode"], act_above=0.8, confirm_above=0.5)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Route verdicts returned by route_on_confidence.
ACT = "act"
CONFIRM = "confirm"
ESCALATE = "escalate"


def confidence_from_distribution(probabilities: dict[str, float]) -> float:
    """Spread-derived confidence in [0, 1].

    Margin of the peak above uniform, normalized: 1.0 when all mass sits on
    one option, 0.0 when flat. Matches TypeSafe's published Choice examples.
    """
    if not probabilities:
        return 0.0
    count = len(probabilities)
    if count == 1:
        return 1.0
    peak = max(max(0.0, min(1.0, float(value))) for value in probabilities.values())
    return round((peak - 1.0 / count) / (1.0 - 1.0 / count), 6)


def _normalize_probabilities(weights: dict[str, float]) -> dict[str, float]:
    """Clamp weights to [0, 1] and renormalize to sum 1 (uniform on empty)."""
    cleaned = {str(key): max(0.0, float(value)) for key, value in weights.items()}
    total = sum(cleaned.values())
    if total <= 0.0:
        count = len(cleaned)
        return {key: 1.0 / count for key in cleaned} if count else {}
    return {key: round(value / total, 6) for key, value in cleaned.items()}


@dataclass(frozen=True)
class ChoiceQuestion:
    """Select one option from a fixed set (TypeSafe Choice)."""

    instructions: str
    criteria: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoreQuestion:
    """Rate a position on ordered levels (TypeSafe Score)."""

    instructions: str
    levels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.levels) < 2:
            raise ValueError("Score needs at least two levels")


@dataclass(frozen=True)
class NoulQuestion:
    """Yes/no question answered as P(yes) (TypeSafe Noul)."""

    instructions: str
    true_meaning: str = ""
    false_meaning: str = ""


@dataclass(frozen=True)
class ChoiceAnswer:
    option: str
    probabilities: dict[str, float]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "choice",
            "choice": self.option,
            "probabilities": self.probabilities,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ScoreAnswer:
    score: float
    probabilities: dict[str, float]
    confidence: float
    legend: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "score",
            "score": self.score,
            "probabilities": self.probabilities,
            "confidence": self.confidence,
            "legend": self.legend,
        }


@dataclass(frozen=True)
class NoulAnswer:
    probability: float

    @property
    def certainty(self) -> float:
        """Distance from maximal uncertainty, in [0, 1]. Near 0.5 is unsure."""
        return round(abs(self.probability - 0.5) * 2.0, 6)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "noul", "noul": self.probability}


def answer_choice(question: ChoiceQuestion, weights: dict[str, float]) -> ChoiceAnswer:
    """Answer a Choice from per-option weights (missing options score 0)."""
    probabilities = _normalize_probabilities({option: weights.get(option, 0.0) for option in question.criteria})
    if not probabilities:
        raise ValueError("Choice needs at least one option")
    peak = max(probabilities.items(), key=lambda item: (item[1], item[0]))
    return ChoiceAnswer(
        option=peak[0],
        probabilities=probabilities,
        confidence=confidence_from_distribution(probabilities),
    )


def answer_score(question: ScoreQuestion, weights: dict[str, float]) -> ScoreAnswer:
    """Answer a Score as the probability-weighted mean of level numbers."""
    keys = [str(index) for index in range(len(question.levels))]
    probabilities = _normalize_probabilities({key: weights.get(key, 0.0) for key in keys})
    score = round(sum(int(key) * value for key, value in probabilities.items()), 6)
    return ScoreAnswer(
        score=score,
        probabilities=probabilities,
        confidence=confidence_from_distribution(probabilities),
        legend=dict(zip(keys, question.levels, strict=True)),
    )


def answer_noul(question: NoulQuestion, probability_yes: float) -> NoulAnswer:  # noqa: ARG001 - criteria travel with the question for future model-backed judges
    """Answer a Noul as P(yes), clamped to [0, 1]."""
    return NoulAnswer(probability=round(max(0.0, min(1.0, float(probability_yes))), 6))


Scorer = Callable[[dict[str, Any]], dict[str, float] | float]


def evaluate_batch(
    questions: dict[str, ChoiceQuestion | ScoreQuestion | NoulQuestion],
    state: dict[str, Any],
    scorers: dict[str, Scorer],
) -> dict[str, ChoiceAnswer | ScoreAnswer | NoulAnswer]:
    """Evaluate atomic questions independently against one state.

    Each question sees the same *state*; each answer comes only from its own
    *scorer* (Choice/Score: option->weight mapping; Noul: P(yes) float).
    Missing scorers answer uniform/0.5 — explicit uncertainty, never a guess.
    """
    answers: dict[str, ChoiceAnswer | ScoreAnswer | NoulAnswer] = {}
    for name, question in questions.items():
        scorer = scorers.get(name)
        if isinstance(question, ChoiceQuestion):
            weights = dict(scorer(state)) if scorer else {}
            answers[name] = answer_choice(question, weights)
        elif isinstance(question, ScoreQuestion):
            weights = dict(scorer(state)) if scorer else {}
            answers[name] = answer_score(question, weights)
        elif isinstance(question, NoulQuestion):
            probability = float(scorer(state)) if scorer else 0.5
            answers[name] = answer_noul(question, probability)
        else:
            raise ValueError(f"Unknown question type for {name!r}")
    return answers


def route_on_confidence(answer: ChoiceAnswer | ScoreAnswer, *, act_above: float, confirm_above: float) -> str:
    """Three-path routing: act, confirm, or escalate (TypeSafe pattern).

    Thresholds scale with risk: read-only paths pass low ``act_above``,
    destructive paths demand high ``act_above``. Below ``confirm_above``,
    never guess — escalate.
    """
    if not 0.0 <= confirm_above <= act_above <= 1.0:
        raise ValueError("require 0 <= confirm_above <= act_above <= 1")
    if answer.confidence >= act_above:
        return ACT
    if answer.confidence >= confirm_above:
        return CONFIRM
    return ESCALATE


def normalize_score(score: float, level_count: int) -> float:
    """Put a Score on [0, 1] by dividing by its top level number."""
    if level_count < 2:
        raise ValueError("need at least two levels")
    return max(0.0, min(1.0, score / (level_count - 1)))


def combine_weighted(parts: dict[str, float], weights: dict[str, float]) -> float:
    """Deterministic composite of normalized signals (weights in code)."""
    total = sum(max(0.0, float(value)) for value in weights.values())
    if total <= 0.0:
        raise ValueError("weights must sum above zero")
    return round(sum(parts.get(name, 0.0) * max(0.0, float(weights.get(name, 0.0))) for name in parts) / total, 6)


# ------------------------------------------------------------------
# Built-in Ghost advisory questions (observe-only)
# ------------------------------------------------------------------

INTERVENTION_MODES = ("witness", "companion", "prepare", "copilot", "ghost")

SHOULD_ATTEND = NoulQuestion(
    instructions="Does this event deserve Ghost's attention?",
    true_meaning="High-value type, trigger hit, or elevated friction",
    false_meaning="Routine noise with no signal",
)

INTERVENTION_MODE = ChoiceQuestion(
    instructions="How should Ghost meet this event?",
    criteria={
        "witness": "Observe and learn only; stay silent",
        "companion": "Contextual assistance with no side effects",
        "prepare": "Prepare the next action and wait for approval",
        "copilot": "Ask before consequential actions",
        "ghost": "Autonomous within policy",
    },
)

FRICTION_LEVEL = ScoreQuestion(
    instructions="How much behavioral friction does this event carry?",
    levels=("none", "mild", "high"),
)


def advise_event(
    *,
    event_type: str,
    high_value_type: bool,
    trigger_hit: bool,
    attention_confidence: float,
    friction_score: float,
) -> dict[str, ChoiceAnswer | ScoreAnswer | NoulAnswer]:
    """Advisory System-One judgment over one event. Never decides anything.

    Scores are built only from the caller's existing signals, so this stays
    a pure function of loop state: safe to call on the hot path for
    telemetry while the real decisions stay where they are.
    """
    state = {
        "event_type": event_type,
        "high_value_type": high_value_type,
        "trigger_hit": trigger_hit,
        "attention_confidence": attention_confidence,
        "friction_score": friction_score,
    }

    def attend_scorer(state: dict[str, Any]) -> float:
        return round(
            max(
                0.85 if state["trigger_hit"] else 0.0,
                0.75 if state["high_value_type"] else 0.0,
                min(0.7, float(state["attention_confidence"])),
                min(0.8, float(state["friction_score"])),
            ),
            6,
        )

    def mode_scorer(state: dict[str, Any]) -> dict[str, float]:
        attend = attend_scorer(state)
        friction = min(1.0, max(0.0, float(state["friction_score"])))
        calm = 1.0 - friction
        return {
            "witness": round((1.0 - attend) * 0.9 + 0.05, 6),
            "companion": round(attend * calm * 0.8 + 0.05, 6),
            "prepare": round(attend * (0.3 + 0.4 * calm) + 0.05, 6),
            "copilot": round(attend * friction * 0.9 + 0.02, 6),
            "ghost": round(attend * calm * 0.1 + 0.01, 6),
        }

    def friction_scorer(state: dict[str, Any]) -> dict[str, float]:
        friction = min(1.0, max(0.0, float(state["friction_score"])))
        return {"0": 1.0 - friction, "1": friction * 0.6, "2": friction * 0.4}

    return evaluate_batch(
        {"should_attend": SHOULD_ATTEND, "mode": INTERVENTION_MODE, "friction": FRICTION_LEVEL},
        state,
        {"should_attend": attend_scorer, "mode": mode_scorer, "friction": friction_scorer},
    )


__all__ = [
    "ACT",
    "CONFIRM",
    "ESCALATE",
    "FRICTION_LEVEL",
    "INTERVENTION_MODE",
    "INTERVENTION_MODES",
    "SHOULD_ATTEND",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "NoulAnswer",
    "NoulQuestion",
    "ScoreAnswer",
    "ScoreQuestion",
    "advise_event",
    "answer_choice",
    "answer_noul",
    "answer_score",
    "combine_weighted",
    "confidence_from_distribution",
    "evaluate_batch",
    "normalize_score",
    "route_on_confidence",
]
