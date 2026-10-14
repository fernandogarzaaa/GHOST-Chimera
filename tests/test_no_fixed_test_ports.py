"""Guard: live-server tests bind ephemeral ports (port 0), never fixed numbers.

Fixed numbers collided across files (two modules both used 19373) and with
whatever a shared CI runner already had listening, which made the suite
flaky. Port-resolution tests that exercise concrete-port behaviour on purpose
are allowlisted; they claim free blocks first.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ALLOWLIST = {"test_gateway_server.py", "test_gateway_ws_auth.py", "test_no_fixed_test_ports.py"}
PATTERNS = (
    re.compile(r"^_PORT\s*=\s*\[\d+\]", re.MULTILINE),
    re.compile(r"GatewayServer\([^)]*\bport=[1-9]\d*"),
    re.compile(r"run_console\([^)]*\bport=[1-9]\d*", re.DOTALL),
    re.compile(r"http://127\.0\.0\.1:1[89]\d{3}/api"),
)


def test_live_server_tests_use_ephemeral_ports() -> None:
    offenders = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name in ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in PATTERNS:
            match = pattern.search(text)
            if match:
                offenders.append(f"{path.name}: {match.group(0)[:60]!r}")
    assert not offenders, "use port=0, http_port=0 and read server._http_server.server_address[1]:\n" + "\n".join(
        offenders
    )
