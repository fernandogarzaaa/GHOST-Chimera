"""redact_for_egress coverage gaps (poweruser F4/F5, redteam P1-4) plus negative cases."""

from __future__ import annotations

import base64
import time

import pytest

from ghostchimera.redaction import EGRESS_MAX_STRING, redact_for_egress, redact_secrets_text


@pytest.mark.parametrize(
    ("raw", "leak"),
    [
        ("postgres://u:pw1234@db:5432/x", "pw1234"),
        ("mysql://admin:S3cretPass@10.0.0.5/db", "S3cretPass"),
        ('{"password": "hunter2"}', "hunter2"),
        ("'db_password'='hunter22'", "hunter22"),
        ("xoxb-1234567890-abcdefghij", "abcdefghij"),
        ("xoxa-2-abcdefghijklmnop", "abcdefghijklmnop"),
        ("xoxp-1234-5678-abcdefghijk", "abcdefghijk"),
        ("ghs_abcdefghijklmnopqrstuvwxyz0123", "abcdefghijklmnopqrstuvwxyz0123"),
        ("gho_abcdefghijklmnopqrstuvwxyz0123", "abcdefghijklmnopqrstuvwxyz0123"),
        ("ghu_abcdefghijklmnopqrstuvwxyz0123", "abcdefghijklmnopqrstuvwxyz0123"),
        ("glpat-abcdefghij0123456789", "abcdefghij0123456789"),
        ("sk_live_abcdefghijklmn12", "abcdefghijklmn12"),
        ("rk_live_abcdefghijklmn12", "abcdefghijklmn12"),
        ("aws_secret_access_key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMI"),
        ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMI"),
        ("bare cyevOFkkiJC7GHGZXaTmrad/rwG2utnML/Vo7hDo here", "cyevOFkkiJC7GHGZXaTmrad"),
        ("PH mobile 09171234567", "09171234567"),
        ("PH mobile 0917-123-4567", "0917-123-4567"),
        ("PH mobile (0917) 123 4567", "123 4567"),
        ("PH mobile +63 917 123 4567", "917 123 4567"),
        ("PH mobile +639171234567", "9171234567"),
        ("IBAN DE89370400440532013000", "DE89370400440532013000"),
        ("IBAN GB82 WEST 1234 5698 7654 32", "WEST 1234 5698"),
        ("server 10.20.30.40 is down", "10.20.30.40"),
        ("v6 2001:db8:85a3::8a2e:370:7334 up", "2001:db8:85a3::8a2e:370:7334"),
        ("/home/fernando/projects/x.py", "fernando"),
        ("/Users/jane.doe/Desktop", "jane.doe"),
        ("C:\\Users\\Fernando\\AppData", "Fernando"),
        ("token b64 " + base64.b64encode(b"ghp_abcdefghijklmnopqrstuvwx1234").decode(), "Z2hwX2"),
        ("url-encoded password%3Dhunter2hunter2", "hunter2hunter2"),
    ],
)
def test_shapes_are_redacted(raw: str, leak: str) -> None:
    out = redact_for_egress(raw)
    assert leak not in out, out
    assert "[redacted" in out or "[user]" in out


@pytest.mark.parametrize(
    "prose",
    [
        "Reset your password at the portal before Friday.",
        "The secret to good coffee is fresh beans.",
        "Meeting at 12:30:45 on 2026-10-14; version 1.2.3 shipped.",
        "See https://example.com/docs/getting-started for details.",
        "commit a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0 fixed it",
        "GhostChimeraConsoleSecurityTests2 and ThisIsAVeryLongCamelCaseIdentifierName123",
        "ghostchimera/control_plane/console_security.py line 40",
        "Localhost 127.0.0.1 and ::1 stay readable.",
        "Use std::vector and Self::new in code samples.",
        "Total: 4,500.00 PHP for 3 items",
        "The API key rotation guide lives in the wiki.",
    ],
)
def test_normal_prose_is_not_over_redacted(prose: str) -> None:
    assert redact_for_egress(prose) == prose


def test_deep_nesting_does_not_raise() -> None:
    nested: dict = {"leaf": "sk-abcdefghijklmnop1234"}
    for _ in range(2000):
        nested = {"n": nested}
    out = redact_for_egress(nested)  # used to raise RecursionError
    assert "sk-abcdefghijklmnop" not in str(out)


def test_huge_strings_are_clipped_before_scanning() -> None:
    blob = "a" * (10 * 1024 * 1024)
    start = time.perf_counter()
    out = redact_for_egress({"text": blob})
    assert time.perf_counter() - start < 1.0
    assert len(out["text"]) <= EGRESS_MAX_STRING + 32


def test_local_secret_redaction_keeps_pii() -> None:
    text = "email jane@acme.com key ghs_abcdefghijklmnopqrstuvwxyz0123"
    out = redact_secrets_text(text)
    assert "jane@acme.com" in out
    assert "ghs_abcdefghijklmnop" not in out
