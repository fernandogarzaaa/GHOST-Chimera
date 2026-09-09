"""ASD-STE100-inspired simplifier for Ghost pre-fill drafts.

Rule: every user-facing pre-fill must read as plain human language that
does not scan as AI-generated. Implements the enforceable core of
Simplified Technical English deterministically (no LLM):

- R1 approved vocabulary: one simple word per meaning (utilize->use ...).
- R2 short sentences: split anything over 20 words at safe boundaries.
- R3 one instruction per sentence: split ";", em-dashes, "then"-chains.
- R4 no filler adverbs: drop very/really/extremely/simply/merely.
- R5 human tone overlay: natural contractions (do not->don't), because
  stilted uncontracted prose is itself an AI tell. Technical nouns,
  names, placeholders, code, and user edits to wording are preserved;
  only the listed mechanical transforms apply (case-preserving).

`simplify()` is idempotent: simplifying twice yields the same text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# R1: (complex, simple). Word-boundary matched, first-letter case preserved.
VOCABULARY: tuple[tuple[str, str], ...] = (
    ("utilize", "use"), ("utilization", "use"), ("commence", "start"),
    ("prior to", "before"), ("in order to", "to"), ("assistance", "help"),
    ("inform", "tell"), ("receive", "get"), ("purchase", "buy"),
    ("require", "need"), ("ensure", "make sure"), ("obtain", "get"),
    ("regarding", "about"), ("concerning", "about"), ("demonstrate", "show"),
    ("indicate", "show"), ("sufficient", "enough"), ("additional", "more"),
    ("attempt", "try"), ("inquire", "ask"), ("acquire", "get"),
    ("terminate", "stop"), ("initiate", "start"), ("facilitate", "help"),
    ("leverage", "use"), ("optimize", "improve"), ("implement", "do"),
    ("correspondence", "mail"), ("transmit", "send"), ("retain", "keep"),
    ("discontinue", "stop"), ("expedite", "speed up"), ("ascertain", "find out"),
    ("enclosed", "attached"), ("forthcoming", "coming"), ("henceforth", "from now on"),
    ("hereby", ""), ("herewith", "with this"), ("notwithstanding", "even if"),
    ("pursuant to", "under"), ("utilizing", "using"), ("finalize", "finish"),
    ("prioritize", "put first"), ("endeavor", "try"),
)

# R4 fillers removed (standalone words only).
FILLERS = ("very", "really", "extremely", "simply", "merely", "highly", "utterly")

# R5 contractions applied (word-boundary, interpolated after vocabulary).
CONTRACTIONS: tuple[tuple[str, str], ...] = (
    ("do not", "don't"), ("does not", "doesn't"), ("did not", "didn't"),
    ("cannot", "can't"), ("will not", "won't"), ("should not", "shouldn't"),
    ("would not", "wouldn't"), ("could not", "couldn't"), ("is not", "isn't"),
    ("are not", "aren't"), ("was not", "wasn't"), ("were not", "weren't"),
    ("have not", "haven't"), ("has not", "hasn't"), ("it is", "it's"),
    ("that is", "that's"), ("there is", "there's"), ("you are", "you're"),
    ("we are", "we're"), ("i am", "I'm"), ("let us", "let's"),
)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_MAX_WORDS = 20


@dataclass
class SimplifyResult:
    text: str
    rules_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _preserve_case(original: str, replacement: str) -> str:
    if not replacement:
        return ""
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _swap_vocab(sentence: str, applied: list[str]) -> str:
    for complex_, simple in VOCABULARY:
        pattern = re.compile(r"\b" + re.escape(complex_) + r"\b", re.IGNORECASE)

        def _one(match: re.Match[str], _simple: str = simple) -> str:
            word = _preserve_case(match.group(0), _simple)
            applied.append(f"R1:{match.group(0).lower()}->{_simple or '(removed)'}")
            return word

        sentence = pattern.sub(_one, sentence)
    # Collapse gaps left by removals (e.g. "hereby").
    sentence = re.sub(r"\s{2,}", " ", sentence)
    sentence = re.sub(r"\s+([,.!?;:])", r"\1", sentence)
    return sentence.strip()


def _drop_fillers(sentence: str, applied: list[str]) -> str:
    for filler in FILLERS:
        pattern = re.compile(r"\b" + filler + r"\s+", re.IGNORECASE)
        sentence, n = pattern.subn("", sentence)
        if n:
            applied.append(f"R4:{filler.lower()} x{n}")
    return sentence


def _contract(sentence: str, applied: list[str]) -> str:
    for full, short in CONTRACTIONS:
        pattern = re.compile(r"\b" + re.escape(full) + r"\b", re.IGNORECASE)

        def _one(match: re.Match[str], _short: str = short) -> str:
            applied.append(f"R5:{match.group(0).lower()}->{_short}")
            return _preserve_case(match.group(0), _short)

        sentence = pattern.sub(_one, sentence)
    return sentence


def _split_long(sentence: str, applied: list[str]) -> list[str]:
    words = sentence.split()
    if len(words) <= _MAX_WORDS:
        return [sentence]
    for boundary in (", and ", "; ", " — ", " and ", " which ", " that ",
                     " because ", " so ", " then "):
        if boundary in sentence:
            parts = [p.strip(" ,") for p in sentence.split(boundary)]
            parts = [p for p in parts if p]
            if len(parts) > 1:
                applied.append(f"R2:split@{boundary.strip()} ({len(words)}w)")
                out: list[str] = []
                for part in parts:
                    out.extend(_split_long(_finish(part), applied))
                return out
    applied.append(f"R2:unsplittable ({len(words)}w)")
    return [sentence]


def _finish(fragment: str) -> str:
    fragment = fragment.strip().rstrip(",;")
    if fragment and fragment[-1] not in ".!?":
        fragment += "."
    if fragment:
        fragment = fragment[:1].upper() + fragment[1:]
    return fragment


def simplify_sentence(sentence: str) -> tuple[str, list[str]]:
    applied: list[str] = []
    text = sentence.strip()
    if not text:
        return "", applied
    text = _swap_vocab(text, applied)
    text = _drop_fillers(text, applied)
    text = _contract(text, applied)
    return text, applied


def simplify(text: str) -> SimplifyResult:
    """Rewrite *text* in STE-core human tone. Idempotent."""
    applied: list[str] = []
    warnings: list[str] = []
    # R3: one instruction per sentence — pre-split chains first.
    chunks: list[str] = []
    for piece in re.split(r"\s*;\s*|\s+—\s+|\s+then\s+", text.strip()):
        chunks.extend(_SENT_SPLIT.split(piece))
    out: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        simplified, rules = simplify_sentence(chunk)
        applied.extend(rules)
        out.extend(_split_long(simplified, applied))
    # Deduplicate rule log preserving order.
    seen: list[str] = []
    for rule in applied:
        if rule not in seen:
            seen.append(rule)
    result = " ".join(out)
    for sentence in _SENT_SPLIT.split(result):
        if len(sentence.split()) > _MAX_WORDS:
            warnings.append(f"sentence still {len(sentence.split())} words: {sentence[:60]}…")
    return SimplifyResult(text=result, rules_applied=seen, warnings=warnings)


__all__ = ["SimplifyResult", "simplify", "simplify_sentence"]
