"""ANSI color utilities for Ghost Chimera CLI."""

from __future__ import annotations

import os
import sys
from typing import TextIO


def color_enabled(stream: TextIO | None = None) -> bool:
    """Return True when ANSI colour should be emitted on *stream* (default stdout).

    Follows https://no-color.org: any non-empty ``NO_COLOR`` disables colour.
    ``FORCE_COLOR`` (non-empty, not ``0``) forces it on. Otherwise colour is
    only used when the stream is an interactive terminal and ``TERM`` is not
    ``dumb``, so piped/redirected output and CI logs stay plain text.
    """
    if os.environ.get("NO_COLOR"):
        return False
    force = os.environ.get("FORCE_COLOR", "")
    if force and force != "0":
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    stream = sys.stdout if stream is None else stream
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


class _ColorsMeta(type):
    # Codes are resolved on every access so modules that captured ``Colors``
    # at import time still honour NO_COLOR / a redirected stdout at call time.
    def __getattribute__(cls, name: str):
        value = type.__getattribute__(cls, name)
        if name.isupper() and isinstance(value, str) and not color_enabled():
            return ""
        return value


class Colors(metaclass=_ColorsMeta):
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"


def color(text: str, fg: str, bold: bool = False) -> str:
    if not color_enabled():
        return text
    prefix = Colors.BOLD if bold else ""
    return f"{prefix}{fg}{text}{Colors.RESET}"


def print_header(title: str) -> None:
    print()
    print(color(f"  == {title} ==", Colors.CYAN, True))


def print_info(msg: str) -> None:
    print(f"  {Colors.DIM}{msg}{Colors.RESET}")


def print_success(msg: str) -> None:
    print(f"  {Colors.GREEN}{msg}{Colors.RESET}")


def print_warning(msg: str) -> None:
    print(f"  {Colors.YELLOW}{msg}{Colors.RESET}")


def print_error(msg: str) -> None:
    print(f"  {Colors.RED}{msg}{Colors.RESET}")
