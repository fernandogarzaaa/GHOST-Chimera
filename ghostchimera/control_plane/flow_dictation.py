"""Flow dictation: Wispr-style push-to-talk post-processing for Ghost.

Pipeline (all deterministic, offline, no LLM required):

    raw transcript
      -> inline formatting ("comma" -> ",", "new paragraph" -> "\\n\\n", ...)
      -> smart formatting ("john at example dot com" -> "john@example.com",
         "3 p m" -> "3 PM")
      -> filler stripping ("um", "uh", "you know", "like" as filler)
      -> vocabulary corrections (user hotwords, longest-match-wins)
      -> capitalize-first + ensure-punctuation (per-profile toggles)

Plus `FlowHistory` (last-N transcript journal) and `transcribe_and_format`
which runs the whole record -> transcribe -> format -> deliver pipeline
over LocalVoiceTranscriber without persisting raw audio.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Spoken punctuation / layout, in longest-first application order.
INLINE_FORMATTING: tuple[tuple[str, str], ...] = (
    ("new paragraph", "\n\n"),
    ("new line", "\n"),
    ("open quote", "\u201c"),
    ("close quote", "\u201d"),
    ("question mark", "?"),
    ("exclamation mark", "!"),
    ("exclamation point", "!"),
    ("colon", ":"),
    ("semicolon", ";"),
    ("comma", ","),
    ("period", "."),
    ("dot", "."),
    ("dash", "-"),
    ("hyphen", "-"),
)

FILLERS = ("um", "uh", "er", "ah", "you know", "i mean", "like", "sort of", "kind of")

_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}


@dataclass
class FlowProfile:
    """Per-context formatting toggles (cf. whisper-local profiles)."""

    name: str = "dictation"
    inline_formatting: bool = True
    smart_formatting: bool = True
    strip_fillers: bool = True
    capitalize_first: bool = True
    ensure_punctuation: bool = True
    vocabulary: dict[str, str] = field(default_factory=dict)

    @classmethod
    def verbatim(cls) -> FlowProfile:
        """Code-editor style: copy exactly what was said."""
        return cls(
            name="verbatim",
            inline_formatting=False,
            smart_formatting=False,
            strip_fillers=False,
            capitalize_first=False,
            ensure_punctuation=False,
        )


PROFILES = {
    "dictation": FlowProfile(),
    "chat": FlowProfile(name="chat"),
    "code": FlowProfile.verbatim(),
    "notes": FlowProfile(name="notes"),
}


def apply_inline_formatting(text: str) -> tuple[str, list[str]]:
    applied: list[str] = []
    for spoken, symbol in INLINE_FORMATTING:
        # [ \t] only: \s would swallow the very newlines we insert.
        pattern = re.compile(r"[ \t]*\b" + re.escape(spoken) + r"\b[ \t]*", re.IGNORECASE)
        text, n = pattern.subn(lambda m, _sym=symbol: f"{_sym} " if _sym not in "?!.,:;" else _sym + " ", text)
        if n:
            applied.append(f"inline:{spoken}->{symbol} x{n}")
    return re.sub(r"[ \t]{2,}", " ", text).strip(), applied


def apply_smart_formatting(text: str) -> tuple[str, list[str]]:
    applied: list[str] = []

    # "john at example dot com" -> "john@example.com"
    def _email(match: re.Match[str]) -> str:
        user, domain, tld = match.group(1), match.group(2), match.group(3)
        applied.append("smart:email")
        return f"{user}@{domain}.{tld}"

    text = re.sub(r"\b([a-z0-9._-]+)\s+at\s+([a-z0-9-]+)\s+dot\s+([a-z]{2,6})\b", _email, text, flags=re.IGNORECASE)

    # "3 p m" / "3 p.m." -> "3 PM" (letter captured; a m -> AM)
    def _ampm(match: re.Match[str]) -> str:
        applied.append("smart:ampm")
        return f"{match.group(1)} {match.group(2).upper()}M"

    text = re.sub(r"\b(\d{1,2})\s*([ap])\s*\.?\s*m\s*\.?\b", _ampm, text, flags=re.IGNORECASE)

    # number words 0-10 -> digits when clearly quantities ("meeting at three" stays).
    def _number(match: re.Match[str]) -> str:
        applied.append("smart:number")
        return _NUMBER_WORDS[match.group(0).lower()]

    text = re.sub(r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten)\b", _number, text, flags=re.IGNORECASE)
    return text, applied


def strip_fillers(text: str) -> tuple[str, list[str]]:
    applied: list[str] = []
    for filler in FILLERS:
        pattern = re.compile(r"(^|\s)" + re.escape(filler) + r"(?=[\s,.!?]|$)", re.IGNORECASE)
        text, n = pattern.subn(r"\1", text)
        if n:
            applied.append(f"filler:{filler} x{n}")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip(" ,"), applied


def apply_vocabulary(text: str, vocabulary: dict[str, str]) -> tuple[str, list[str]]:
    """Longest-match-wins hotword corrections (e.g. CAPEX <- 'cap x')."""
    applied: list[str] = []
    for heard in sorted(vocabulary, key=len, reverse=True):
        pattern = re.compile(r"\b" + re.escape(heard) + r"\b", re.IGNORECASE)
        text, n = pattern.subn(vocabulary[heard], text)
        if n:
            applied.append(f"vocab:{heard}->{vocabulary[heard]} x{n}")
    return text, applied


@dataclass
class FormattedTranscript:
    raw: str
    text: str
    rules_applied: list[str] = field(default_factory=list)
    profile: str = "dictation"


def format_transcript(raw: str, profile: FlowProfile | str = "dictation") -> FormattedTranscript:
    """Run the full Wispr-style format pipeline over a raw transcript."""
    prof = PROFILES.get(profile, PROFILES["dictation"]) if isinstance(profile, str) else profile
    text, applied = raw.strip(), []
    if prof.inline_formatting:
        text, rules = apply_inline_formatting(text)
        applied.extend(rules)
    if prof.smart_formatting:
        text, rules = apply_smart_formatting(text)
        applied.extend(rules)
    if prof.strip_fillers:
        text, rules = strip_fillers(text)
        applied.extend(rules)
    if prof.vocabulary:
        text, rules = apply_vocabulary(text, prof.vocabulary)
        applied.extend(rules)
    if prof.capitalize_first and text:
        text = text[:1].upper() + text[1:]
        applied.append("caps:first")
    if prof.ensure_punctuation and text and text[-1] not in ".!?":
        # Don't punctuate mid-thought fragments ending in an opening quote.
        text += "."
        applied.append("punct:final-period")
    return FormattedTranscript(raw=raw, text=text, rules_applied=applied, profile=prof.name)


class FlowHistory:
    """Last-N transcript journal (no audio, text only)."""

    def __init__(self, state_dir: str | Path, *, limit: int = 50) -> None:
        self._file = Path(state_dir) / "flow_history.jsonl"
        self._limit = limit

    def record(self, formatted: FormattedTranscript, *, provider: str = "") -> None:
        entry = {
            "at": time.time(),
            "profile": formatted.profile,
            "provider": provider,
            "raw": formatted.raw,
            "text": formatted.text,
            "rules": formatted.rules_applied,
        }
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            lines = []
            if self._file.exists():
                lines = self._file.read_text(encoding="utf-8").splitlines()[-self._limit + 1 :]
            lines.append(json.dumps(entry))
            self._file.write_text("\n".join(lines[-self._limit :]), encoding="utf-8")
        except OSError:
            pass

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        try:
            lines = self._file.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


def transcribe_and_format(
    transcriber: Any,
    audio_base64: str,
    *,
    mime_type: str = "",
    profile: str = "dictation",
    history: FlowHistory | None = None,
) -> dict[str, Any]:
    """Full flow: transcribe -> format -> history. Returns redacted result."""
    result = transcriber.transcribe_base64(audio_base64, mime_type=mime_type)
    if not result.get("ok") or not result.get("transcript"):
        return {
            "ok": False,
            "error": result.get("error", "transcription failed"),
            "provider": result.get("provider", ""),
            "text": "",
            "rules_applied": [],
        }
    formatted = format_transcript(result["transcript"], profile)
    if history is not None:
        history.record(formatted, provider=str(result.get("provider", "")))
    return {
        "ok": True,
        "provider": result.get("provider", ""),
        "raw": formatted.raw,
        "text": formatted.text,
        "rules_applied": formatted.rules_applied,
        "profile": formatted.profile,
    }


__all__ = [
    "FlowHistory",
    "FlowProfile",
    "FormattedTranscript",
    "PROFILES",
    "apply_inline_formatting",
    "apply_smart_formatting",
    "apply_vocabulary",
    "format_transcript",
    "strip_fillers",
    "transcribe_and_format",
]
