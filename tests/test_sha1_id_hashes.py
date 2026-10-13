"""SHA-1 is only used for IDs, and every call says so (usedforsecurity=False).

Without the flag, FIPS-mode Python builds refuse hashlib.sha1() outright and
security scanners (bandit B324, CodeQL) flag each call as weak crypto.
"""

from __future__ import annotations

import ast
import hashlib
import pathlib

import ghostchimera
from ghostchimera.control_plane.standing_orders import _stable_order_id
from ghostchimera.trust_runtime import _stable_id

PACKAGE_ROOT = pathlib.Path(ghostchimera.__file__).parent


def _sha1_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "sha1"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "hashlib"
        ):
            yield node


def test_every_sha1_call_is_marked_not_for_security() -> None:
    offenders = []
    found = 0
    for path in PACKAGE_ROOT.rglob("*.py"):
        for call in _sha1_calls(ast.parse(path.read_text(encoding="utf-8"))):
            found += 1
            flag = next((kw for kw in call.keywords if kw.arg == "usedforsecurity"), None)
            if flag is None or not isinstance(flag.value, ast.Constant) or flag.value.value is not False:
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{call.lineno}")
    assert found > 0
    assert offenders == [], f"hashlib.sha1 without usedforsecurity=False: {offenders}"


def test_ids_are_unchanged_by_the_flag() -> None:
    """The flag must not change digests, or persisted IDs would drift."""
    assert _stable_id("a", "b") == hashlib.sha1(b"a|b").hexdigest()[:16]
    raw = "title|scope|1.000000"
    assert _stable_order_id("Title", "Scope", 1.0) == hashlib.sha1(raw.encode()).hexdigest()[:16]
