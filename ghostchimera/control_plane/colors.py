"""ANSI color utilities for Ghost Chimera CLI."""

from __future__ import annotations


class Colors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"


def color(text: str, fg: str, bold: bool = False) -> str:
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
