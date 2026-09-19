"""Launch an isolated Ghost Console on a fixed port and hold it for EVE QA.

Usage: python -u scripts/hold_console_for_eve.py [--ws-port 8790] [--http-port 8791]
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ws-port", type=int, default=8790)
    parser.add_argument("--http-port", type=int, default=8791)
    args = parser.parse_args()

    from ghostchimera.control_plane.console import run_console

    state_dir = Path(tempfile.mkdtemp(prefix="ghostchimera-eve-"))
    with contextlib.redirect_stdout(io.StringIO()):
        server = run_console(
            host="127.0.0.1",
            port=args.ws_port,
            http_port=args.http_port,
            state_dir=state_dir,
            open_browser=False,
            block=False,
        )
    print(json.dumps({"eve_target": f"http://127.0.0.1:{args.http_port}", "state_dir": str(state_dir)}, sort_keys=True))
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
