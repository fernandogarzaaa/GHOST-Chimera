"""Control plane exports."""

from __future__ import annotations


def run_cli() -> None:
    from .cli import run_cli as _run_cli

    _run_cli()


__all__ = ["run_cli"]
