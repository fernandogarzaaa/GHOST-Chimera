"""Flow dictation: Wispr-style push-to-talk post-processing for Ghost.

Pipeline (all deterministic, offline, no LLM required):

    raw transcript
      -> inline formatting ("comma" -> ",", "new paragraph" -> "\\n\\n", ...)
      -> smart formatting ("john at example dot com" -> "john@example.com",
         "3 p m" -> "3 PM")
      -> filler stripping ("um", "uh", "you know", "like" as filler)
      -> vocabulary corrections (user hotwords, longest-match-wins)
      -> capitalize-first + ensure-punctuation (per-profile toggles)

Plus `FlowHistory` (last-N transcript journal), `flow_stats` (usage
statistics derived from the journal), and `transcribe_and_format`
which runs the whole record -> transcribe -> format -> deliver pipeline
over LocalVoiceTranscriber without persisting raw audio.
"""

from __future__ import annotations

import datetime
import difflib
import json
import re
import string
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


def _learnable_term(term: str) -> bool:
    words = term.strip().split()
    if not 1 <= len(words) <= 4:
        return False
    if len(term) > 40 or len(term) < 2:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9 .,'-]+", term.strip()))


class PersonalDictionary:
    """Auto-learned hotwords persisted to the state dir.

    Entries map misheard phrases to written forms. Learning is conservative:
    only short, plain-text substitutions are kept, so junk can never poison
    future transcripts.
    """

    def __init__(self, state_dir: str | Path, *, limit: int = 200) -> None:
        self._file = Path(state_dir) / "personal_dictionary.json"
        self._limit = max(1, limit)

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def entries(self) -> dict[str, str]:
        """Learned heard -> written mapping."""

        stored = self._load().get("entries", {})
        return dict(stored) if isinstance(stored, dict) else {}

    def learn(self, heard: str, written: str) -> bool:
        """Record one correction; return True when it was kept."""

        heard_key, written_value = heard.strip(), written.strip()
        if not heard_key or not written_value or heard_key == written_value:
            return False
        if not _learnable_term(heard_key) or not _learnable_term(written_value):
            return False
        data = self._load()
        entries = data.get("entries", {})
        if not isinstance(entries, dict):
            entries = {}
        entries[heard_key.lower()] = written_value
        while len(entries) > self._limit:
            entries.pop(next(iter(entries)))
        hits = data.get("hits", {})
        if not isinstance(hits, dict):
            hits = {}
        hits[heard_key.lower()] = int(hits.get(heard_key.lower(), 0)) + 1
        data["entries"] = entries
        data["hits"] = hits
        self._save(data)
        return True

    def remove(self, heard: str) -> bool:
        """Forget one learned entry; return True when it existed."""

        data = self._load()
        entries = data.get("entries", {})
        if not isinstance(entries, dict) or heard.strip().lower() not in entries:
            return False
        del entries[heard.strip().lower()]
        data["entries"] = entries
        self._save(data)
        return True

    def stats(self) -> dict[str, Any]:
        """Entry count and total confirmed corrections."""

        data = self._load()
        entries = data.get("entries", {})
        hits = data.get("hits", {})
        if not isinstance(entries, dict):
            entries = {}
        if not isinstance(hits, dict):
            hits = {}
        return {"entries": len(entries), "corrections": sum(int(v) for v in hits.values())}

    def apply(self, text: str) -> tuple[str, list[str]]:
        """Apply learned entries longest-match-wins."""

        entries = self.entries()
        applied: list[str] = []
        for heard in sorted(entries, key=len, reverse=True):
            pattern = re.compile(r"\b" + re.escape(heard) + r"\b", re.IGNORECASE)
            text, n = pattern.subn(entries[heard], text)
            if n:
                applied.append(f"learned:{heard}->{entries[heard]} x{n}")
        return text, applied


def learn_correction(original: str, corrected: str) -> list[tuple[str, str]]:
    """Extract single-word substitutions from a user correction.

    Only unambiguous one-word swaps are returned (WhimprFlow-style
    conservative capture); anything structural is ignored.
    """

    original_words = original.split()
    corrected_words = corrected.split()
    matcher = difflib.SequenceMatcher(None, [w.lower() for w in original_words], [w.lower() for w in corrected_words])
    learned: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or i2 - i1 != 1 or j2 - j1 != 1:
            continue
        heard, written = original_words[i1], corrected_words[j1]
        if heard != written and _learnable_term(heard) and _learnable_term(written):
            learned.append((heard, written))
    return learned


@dataclass
class FormattedTranscript:
    raw: str
    text: str
    rules_applied: list[str] = field(default_factory=list)
    profile: str = "dictation"
    gated: bool = False
    gate_reason: str = ""


def format_transcript(
    raw: str,
    profile: FlowProfile | str = "dictation",
    dictionary: PersonalDictionary | dict[str, str] | None = None,
) -> FormattedTranscript:
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
    learned = dictionary.entries() if isinstance(dictionary, PersonalDictionary) else dictionary or {}
    if learned:
        if isinstance(dictionary, PersonalDictionary):
            text, rules = dictionary.apply(text)
        else:
            text, rules = apply_vocabulary(text, learned)
        applied.extend(rules)
    if prof.capitalize_first and text:
        text = text[:1].upper() + text[1:]
        applied.append("caps:first")
    if prof.ensure_punctuation and text and text[-1] not in ".!?":
        # Don't punctuate mid-thought fragments ending in an opening quote.
        text += "."
        applied.append("punct:final-period")
    return FormattedTranscript(raw=raw, text=text, rules_applied=applied, profile=prof.name)


def _word_similarity(raw: str, formatted: str) -> float:
    """Word-level similarity between raw and formatted transcripts."""

    def _tokens(text: str) -> list[str]:
        return [word.strip(string.punctuation) for word in text.lower().split() if word.strip(string.punctuation)]

    raw_words = _tokens(raw)
    formatted_words = _tokens(formatted)
    if not raw_words and not formatted_words:
        return 1.0
    if not raw_words or not formatted_words:
        return 0.0
    return difflib.SequenceMatcher(None, raw_words, formatted_words).ratio()


def _digit_runs(text: str) -> list[str]:
    return re.findall(r"\d+", text)


def gated_format_transcript(
    raw: str, profile: FlowProfile | str = "dictation", *, min_similarity: float = 0.6
) -> FormattedTranscript:
    """Format with deterministic anti-over-edit gates and raw fallback.

    Whisper transcripts are evidence; formatting must not rewrite them. When
    the pipeline changes too much or drops digit runs, the raw transcript is
    returned with ``gated=True`` and the reason recorded.
    """

    formatted = format_transcript(raw, profile)
    similarity = _word_similarity(raw, formatted.text)
    if similarity < min_similarity:
        formatted.text = raw.strip()
        formatted.gated = True
        formatted.gate_reason = f"similarity {similarity:.2f} below minimum {min_similarity:.2f}"
        return formatted
    raw_digits = _digit_runs(raw)
    formatted_digits = _digit_runs(formatted.text)
    for run in raw_digits:
        if run not in formatted_digits:
            formatted.text = raw.strip()
            formatted.gated = True
            formatted.gate_reason = f"dropped digit run {run!r}"
            return formatted
    return formatted


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

    def all_entries(self) -> list[dict[str, Any]]:
        """Every journaled entry, oldest first (bounded by the journal limit)."""

        return self.recent(self._limit)


def _entry_day(timestamp: float) -> str:
    return datetime.datetime.fromtimestamp(timestamp, tz=datetime.UTC).date().isoformat()


def flow_stats(history: FlowHistory) -> dict[str, Any]:
    """Usage statistics derived from the dictation journal.

    Words dictated, active days, current streak, per-provider counts, a
    trailing 7-day activity series, and an estimated typing-minutes-saved
    figure (words at 40 WPM, clearly an estimate).
    """

    entries = [entry for entry in history.all_entries() if isinstance(entry, dict)]
    words = sum(len(str(entry.get("text", "")).split()) for entry in entries)
    providers: dict[str, int] = {}
    days: dict[str, dict[str, int]] = {}
    for entry in entries:
        provider = str(entry.get("provider", "") or "unknown")
        providers[provider] = providers.get(provider, 0) + 1
        try:
            day = _entry_day(float(entry.get("at", 0)))
        except (TypeError, ValueError):
            continue
        bucket = days.setdefault(day, {"words": 0, "entries": 0})
        bucket["words"] += len(str(entry.get("text", "")).split())
        bucket["entries"] += 1
    today = datetime.datetime.now(tz=datetime.UTC).date()
    last_7_days = [
        {
            "date": (today - datetime.timedelta(days=offset)).isoformat(),
            "words": days.get((today - datetime.timedelta(days=offset)).isoformat(), {}).get("words", 0),
            "entries": days.get((today - datetime.timedelta(days=offset)).isoformat(), {}).get("entries", 0),
        }
        for offset in range(6, -1, -1)
    ]
    day_set = set(days)
    streak = 0
    cursor = today
    if cursor.isoformat() not in day_set:
        cursor -= datetime.timedelta(days=1)
    while cursor.isoformat() in day_set:
        streak += 1
        cursor -= datetime.timedelta(days=1)
    return {
        "entries": len(entries),
        "words": words,
        "active_days": len(days),
        "streak_days": streak,
        "avg_words_per_entry": round(words / len(entries), 1) if entries else 0.0,
        "providers": providers,
        "last_7_days": last_7_days,
        "typing_minutes_saved_estimate": round(words / 40.0, 1),
    }


def transcribe_and_format(
    transcriber: Any,
    audio_base64: str,
    *,
    mime_type: str = "",
    profile: str = "dictation",
    history: FlowHistory | None = None,
    dictionary: PersonalDictionary | dict[str, str] | None = None,
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
    formatted = format_transcript(result["transcript"], profile, dictionary)
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
    "PersonalDictionary",
    "apply_inline_formatting",
    "apply_smart_formatting",
    "apply_vocabulary",
    "flow_stats",
    "format_transcript",
    "gated_format_transcript",
    "learn_correction",
    "strip_fillers",
    "transcribe_and_format",
]
