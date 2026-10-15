"""Verify the two CI fixes: cleared-env home resolution + version-stable SSRF blocks."""

import ipaddress
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostchimera import paths  # noqa: E402
from ghostchimera.safety_layer.ssrf import (  # noqa: E402
    SSRFPolicy,
    _is_internal_address,
)

# 1. Cleared environment (simulates Windows CI runner with no USERPROFILE/HOME)
with patch.dict(os.environ, {}, clear=True):
    d = paths.state_dir()
    print("state_dir under cleared env:", d)
    assert str(d).endswith(".ghostchimera"), d
    # NOTE: importing ghostchimera.config from a repo-root script trips a
    # pre-existing circular import (config -> safety_layer -> chimera_pilot ->
    # cognition_layer -> config) that pytest's installed-package path avoids;
    # GhostChimeraConfig.from_env() is covered by tests/test_config.py instead.

# 2. SSRF: every non-global test URL must be blocked on ANY Python version
blocked = [
    "http://100.64.0.1/",
    "http://100.100.100.100/",
    "http://192.0.0.8/",
    "http://198.18.0.1/",
    "http://[::ffff:100.64.0.1]/",
    "http://[2002:7f00:1::]/",
    "http://127.0.0.1/",
    "http://169.254.169.254/",
]
for url in blocked:
    permitted, reason = SSRFPolicy(default_allow=True).is_permitted(url)
    status = "BLOCKED " if not permitted else "ALLOWED!!"
    print(f"{status} {url} ({reason})")
    assert not permitted, url

permitted, _ = SSRFPolicy(default_allow=True).is_permitted("https://93.184.216.34/")
assert permitted, "public literal must stay allowed"
print("public literal still allowed: OK")

# 3. Raw helper sanity across the matrix
for raw in ["192.0.0.8", "::ffff:100.64.0.1", "2002:7f00:1::", "127.0.0.1"]:
    assert _is_internal_address(ipaddress.ip_address(raw)), raw
assert not _is_internal_address(ipaddress.ip_address("93.184.216.34"))
print("ALL CHECKS PASSED")
