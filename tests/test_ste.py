"""STE simplifier tests: deterministic, idempotent, human-tone."""

from __future__ import annotations

from ghostchimera.stealth.ste import simplify


def test_vocabulary_swaps() -> None:
    result = simplify("Please utilize the enclosed file prior to the meeting.")
    assert "utilize" not in result.text
    assert "use" in result.text
    assert "before" in result.text
    assert any(r.startswith("R1:") for r in result.rules_applied)


def test_long_sentence_splits() -> None:
    text = (
        "I have completed the very thorough review of the proposal and I want "
        "to inform you that we should commence work prior to Friday in order "
        "to meet the deadline."
    )
    result = simplify(text)
    for sentence in result.text.split(". "):
        assert len(sentence.split()) <= 20, sentence
    assert any(r.startswith("R2:") for r in result.rules_applied)


def test_filler_and_contractions() -> None:
    result = simplify("This is really very important and it is not ready.")
    assert "really" not in result.text and "very" not in result.text
    assert "it's" in result.text or "isn't" in result.text or "not" in result.text


def test_idempotent() -> None:
    text = (
        "Please utilize this to commence. It is very important that you inform them prior to Friday, in order to start."
    )
    once = simplify(text).text
    twice = simplify(once).text
    assert once == twice


def test_simple_text_untouched() -> None:
    text = "Hi John. I moved the meeting to Friday. Let me know if that works."
    result = simplify(text)
    assert result.text == text
    assert result.rules_applied == []


def test_bpo_prefill_example() -> None:
    text = (
        "Hi John, I have updated your schedule as requested. "
        "Please inform me prior to Thursday in order to finalize the booking."
    )
    result = simplify(text)
    assert "inform" not in result.text and "finalize" not in result.text
    assert "tell" in result.text and "finish" in result.text
    assert "John" in result.text  # names preserved
