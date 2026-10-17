"""Boundary tests for egress/PII redaction (written from testteeth survivors).

Secret-shaped strings are assembled at runtime so the repository's strict
secret scan never sees a literal credential in this file.
"""

from __future__ import annotations

import base64
import os

import pytest

from ghostchimera import redaction as r

# A GitHub-PAT-shaped fake, built at runtime.
FAKE_PAT = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def _luhn_digit(prefix: str) -> str:
    """Independent Luhn check-digit computation for test fixtures."""
    total = 0
    for i, ch in enumerate(reversed(prefix + "0")):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return str((10 - total % 10) % 10)


def _card(length: int, start: str = "4") -> str:
    body = start + "1" * (length - len(start) - 1)
    return body + _luhn_digit(body)


def test_fake_pat_is_secret_shaped() -> None:
    assert r._secret_patterns_hit(FAKE_PAT)


# ---------------------------------------------------------------------------
# Luhn / IBAN
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("length", [13, 16, 19])
def test_luhn_accepts_valid_lengths(length: int) -> None:
    assert r._luhn_ok(_card(length)) is True


@pytest.mark.parametrize("length", [12, 20])
def test_luhn_rejects_out_of_range_lengths(length: int) -> None:
    assert r._luhn_ok(_card(length)) is False


def test_luhn_doubling_rules() -> None:
    # Known-valid test numbers exercise doubled digits > 9 (subtract 9).
    assert r._luhn_ok("4111111111111111") is True
    assert r._luhn_ok("5555555555554444") is True
    assert r._luhn_ok("378282246310005") is True
    assert r._luhn_ok("4111111111111112") is False
    assert r._luhn_ok("5555555555554445") is False
    # 9 doubled is 18 -> 9; a ">= 9" rule would turn it into 0 and break this.
    assert r._luhn_ok("4999999999999996") is (sum(_digits_luhn("4999999999999996")) % 10 == 0)


def _digits_luhn(number: str) -> list[int]:
    out = []
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        out.append(d)
    return out


def test_card_redaction_end_to_end() -> None:
    assert r.redact_pii_text("card 4111 1111 1111 1111 ok") == "card [redacted:card] ok"
    assert "4111111111111112" in r.redact_pii_text("id 4111111111111112")


def _iban(country: str, bban: str) -> str:
    rearranged = bban + country + "00"
    num = int("".join(str(int(ch, 36)) for ch in rearranged))
    check = 98 - num % 97
    return f"{country}{check:02d}{bban}"


def test_iban_length_bounds_and_checksum() -> None:
    assert r._iban_ok("NO9386011117947") is True  # 15 chars, shortest real IBAN
    assert r._iban_ok("GB82WEST12345698765432") is True
    assert r._iban_ok("GB82 WEST 1234 5698 7654 32") is True
    assert r._iban_ok("GB83WEST12345698765432") is False
    long34 = _iban("LC", "A" * 30)
    assert len(long34) == 34 and r._iban_ok(long34) is True
    long35 = _iban("LC", "A" * 31)
    assert len(long35) == 35 and r._iban_ok(long35) is False
    short14 = _iban("NO", "1" * 10)
    assert len(short14) == 14 and r._iban_ok(short14) is False
    assert r._iban_ok("GB82WEST1234569876543!") is False  # non-alnum -> ValueError path


def test_home_dir_keep_list() -> None:
    assert r.redact_pii_text("/home/alice/x") == "/home/[user]/x"
    assert r.redact_pii_text("C:\\Users\\Public\\x") == "C:\\Users\\Public\\x"
    assert r.redact_pii_text("/Users/Shared/y") == "/Users/Shared/y"


# ---------------------------------------------------------------------------
# High-entropy and base64-encoded secrets
# ---------------------------------------------------------------------------


RANDOMISH = "aZ3kQ9xT7mN2pL5vB8cR1wY4hJ6dF0gS"  # 32 chars, mixed case + digits, high entropy


def test_looks_random_boundaries() -> None:
    assert len(RANDOMISH) == 32
    assert r._looks_random(RANDOMISH) is True
    assert r._looks_random(RANDOMISH[:31]) is False
    assert r._looks_random(RANDOMISH + "==") is True  # padding stripped
    assert r._looks_random(RANDOMISH.replace("Z", "z").replace("Q", "q").upper()) is False  # no lowercase
    assert r._looks_random("".join(c for c in RANDOMISH if not c.isdigit()) + "abcdefghij") is False  # no digit
    assert r._looks_random("a/b/c" + RANDOMISH) is True  # two slashes allowed
    assert r._looks_random("a/b/c/" + RANDOMISH) is False  # more than two slashes: a path
    assert r._looks_random("Aa1" + "b" * 40) is False  # low entropy


def test_high_entropy_token_redacted_in_text() -> None:
    assert r.redact_secrets_text(f"token {RANDOMISH} end") == "token [redacted] end"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def test_decoded_secret_detects_encoded_credentials() -> None:
    encoded = _b64(f"token: {FAKE_PAT}")
    assert r._decoded_secret(encoded) is True
    # Unpadded form must still decode (padding is recomputed).
    unpadded = encoded.rstrip("=")
    assert len(unpadded) % 4 != 0
    assert r._decoded_secret(unpadded) is True
    # Pick a payload whose base64 needs exactly one "=" and check it too.
    for extra in range(3):
        enc = _b64(f"pw {FAKE_PAT}" + "x" * extra).rstrip("=")
        assert r._decoded_secret(enc) is True
    assert r._decoded_secret(_b64("just a harmless sentence, nothing secret")) is False
    assert r._decoded_secret(_b64("\x00\x01binary " + FAKE_PAT)) is False  # not printable


def test_decoded_secret_size_bound() -> None:
    payload = f"k {FAKE_PAT} "
    enc = _b64(payload + "a" * (3072 - len(payload)))  # exactly 4096 base64 chars
    assert len(enc) == 4096
    assert r._decoded_secret(enc) is True
    big = _b64(payload + "a" * (3075 - len(payload)))
    assert len(big) == 4100
    assert r._decoded_secret(big) is False


def test_encoded_secret_redacted_in_text() -> None:
    out = r.redact_secrets_text("payload " + _b64(f"secret {FAKE_PAT}") + " tail")
    assert FAKE_PAT not in out and "[redacted]" in out and out.endswith(" tail")


def test_url_encoded_secret_only_rescanned_when_it_hides_one() -> None:
    assert "hunter2" not in r.redact_secrets_text("q=password%3Dhunter2xyz")
    # Plain percent-encoding without a secret is left as written (not decoded).
    assert r.redact_secrets_text("path=a%20b%20c") == "path=a%20b%20c"


# ---------------------------------------------------------------------------
# Structural limits
# ---------------------------------------------------------------------------


def test_egress_text_clip_boundary() -> None:
    exact = "a" * r.EGRESS_MAX_STRING
    assert r.redact_egress_text(exact) == exact
    over = "a" * (r.EGRESS_MAX_STRING + 1)
    assert r.redact_egress_text(over) == "a" * r.EGRESS_MAX_STRING + "...[truncated]"


def _nested(depth: int, leaf: object) -> object:
    value = leaf
    for _ in range(depth):
        value = [value]
    return value


def _unwrap(value: object) -> object:
    while isinstance(value, list):
        value = value[0]
    return value


@pytest.mark.parametrize("fn", [r.redact_for_egress, r.redact_secret_values])
def test_depth_limit_is_exact(fn) -> None:
    assert _unwrap(fn(_nested(r.EGRESS_MAX_DEPTH, "ok"))) == "ok"
    assert _unwrap(fn(_nested(r.EGRESS_MAX_DEPTH + 1, "ok"))) == "[redacted:depth]"


@pytest.mark.parametrize("fn", [r.redact_for_egress, r.redact_secret_values])
def test_depth_limit_counts_dicts(fn) -> None:
    value: object = "ok"
    for _ in range(r.EGRESS_MAX_DEPTH + 1):
        value = {"k": value}
    out = fn(value)
    for _ in range(r.EGRESS_MAX_DEPTH + 1):
        out = out["k"]
    assert out == "[redacted:depth]"


def test_egress_structures() -> None:
    src = {"api_key": "x", "empty_token": "", "items": ("a@b.co", FAKE_PAT), "n": 3}
    out = r.redact_for_egress(src)
    assert out == {"api_key": "[redacted]", "empty_token": "", "items": ["[redacted:email]", "[redacted]"], "n": 3}
    assert src["items"][1] == FAKE_PAT  # not mutated
    kept = r.redact_secret_values({"pw_hint": "n", "list": [f"x {FAKE_PAT}", "a@b.co"]}, markers=("hint",))
    assert kept == {"pw_hint": "[redacted]", "list": ["x [redacted]", "a@b.co"]}


def test_redact_value_flag_and_passthrough() -> None:
    text = f"see {FAKE_PAT}"
    assert r.redact_value({"msg": text}) == {"msg": "see [redacted]"}
    assert r.redact_value({"msg": text}, redact_strings=False) == {"msg": text}
    assert r.redact_value([text]) == ["see [redacted]"]
    assert r.redact_value({"secrets": {"token": "t", "name": "n"}}, passthrough_keys={"secrets"}) == {
        "secrets": {"token": "[redacted]", "name": "n"}
    }


def test_pii_redaction_replaces_every_occurrence() -> None:
    assert r.redact_pii_text("a@b.co and c@d.io") == "[redacted:email] and [redacted:email]"


# ---------------------------------------------------------------------------
# Environment scrubbing
# ---------------------------------------------------------------------------


def test_is_secret_env_key() -> None:
    assert r.is_secret_env_key("NEBIUS_API_KEY") is True
    assert r.is_secret_env_key("PATH") is False
    assert r.is_secret_env_key("MY_VAR", markers=("my_",)) is True


def test_scrubbed_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GC_TEST_API_KEY", "s3cret")
    monkeypatch.setenv("GC_TEST_PLAIN", "visible")
    monkeypatch.setenv("GC_KEEP_TOKEN", "kept")
    env = r.scrubbed_environ(keep={"GC_KEEP_TOKEN"})
    assert "GC_TEST_API_KEY" not in env
    assert env["GC_TEST_PLAIN"] == "visible"
    assert env["GC_KEEP_TOKEN"] == "kept"
    assert env.get("PATH") == os.environ.get("PATH")
