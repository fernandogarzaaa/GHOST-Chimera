"""Frozen-desktop entry point for Ghost Chimera.

Built by PyInstaller into GhostConsole(.exe). Starts the console with safe
defaults — localhost only, browser auto-open, blocking until killed — and
relies on the gateway's automatic port selection when 8765/8766 are taken.
"""

from __future__ import annotations

import contextlib


def main() -> int:
    from ghostchimera.control_plane.console import run_console

    with contextlib.suppress(KeyboardInterrupt):
        run_console(open_browser=True, block=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
