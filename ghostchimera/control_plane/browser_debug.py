"""Managed Chrome remote-debugging lifecycle for the Ghost Console.

Computer Use needs a Chrome instance with remote debugging enabled, and the
console-first rule means the operator must never open a terminal for it.
This manager finds the Chrome binary, launches it with a dedicated Ghost
profile directory (never the operator's everyday profile), waits until the
DevTools endpoint answers, and stops it on request. Launching only ever
happens through an explicit operator action (console button / API call).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_DEBUG_PORT = 9222
_LAUNCH_POLL_INTERVAL = 0.25


def find_chrome(executable: str | None = None) -> str | None:
    """Locate a Chrome/Chromium binary without launching anything."""

    override = (executable or os.environ.get("GHOSTCHIMERA_CHROME_BINARY", "")).strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return str(candidate)
        return None
    for name in ("chrome", "chrome.exe", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    if sys.platform.startswith("win"):
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
            Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    else:
        candidates = [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
            Path("/snap/bin/chromium"),
        ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


class ChromeDebugManager:
    """Own the lifecycle of one debuggable Chrome instance."""

    def __init__(self, state_dir: str | Path, *, default_port: int = DEFAULT_DEBUG_PORT) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.default_port = default_port
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._port: int | None = None

    @staticmethod
    def _check_port(port: int | None) -> int:
        if isinstance(port, bool):
            raise ValueError(f"Debug port must be 1-65535, got {port!r}")
        try:
            value = int(port) if not isinstance(port, int) else port  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Debug port must be 1-65535, got {port!r}") from exc
        if not 1 <= value <= 65535:
            raise ValueError(f"Debug port must be 1-65535, got {port!r}")
        return value

    def profile_dir(self) -> Path:
        """Dedicated Chrome profile directory under the Ghost state dir."""

        path = self.state_dir / "chrome-debug-profile"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def is_managed_running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def debug_open(self, port: int | None = None) -> bool:
        """Return True when a DevTools endpoint answers on the port."""

        from ..stealth.cdp import probe

        return probe("127.0.0.1", self._check_port(port if port is not None else (self._port or self.default_port)))

    def debug_websocket_url(self, port: int | None = None) -> str:
        """Return the page WebSocket URL, or raise when debugging is closed."""

        from ..stealth.cdp import page_websocket_url

        return page_websocket_url(
            "127.0.0.1", self._check_port(port if port is not None else (self._port or self.default_port))
        )

    def status(self) -> dict[str, Any]:
        binary = find_chrome()
        port = self._port or self.default_port
        return {
            "installed": binary is not None,
            "binary": binary or "",
            "managed_running": self.is_managed_running(),
            "debug_port": port,
            "debug_open": self.debug_open(port),
            "pid": self._process.pid if self.is_managed_running() and self._process else None,
            "profile_dir": str(self.profile_dir()),
        }

    def launch(
        self,
        port: int | None = None,
        *,
        headless: bool = True,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Launch Chrome with remote debugging, waiting until it answers."""

        target_port = self._check_port(port if port is not None else self.default_port)
        with self._lock:
            if self.is_managed_running():
                return {
                    "ok": True,
                    "already_running": True,
                    "port": self._port,
                    "pid": self._process.pid if self._process else None,
                }
            if self.debug_open(target_port):
                self._port = target_port
                return {"ok": True, "already_running": True, "port": target_port, "pid": None}
            binary = find_chrome()
            if binary is None:
                raise RuntimeError("No Chrome/Chromium binary found. Install Chrome or set GHOSTCHIMERA_CHROME_BINARY.")
            args = [
                binary,
                f"--remote-debugging-port={target_port}",
                f"--user-data-dir={self.profile_dir()}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            if headless:
                args.append("--headless=new")
            try:
                self._process = subprocess.Popen(  # noqa: S603 - operator-approved fixed-shape launch
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    **(
                        {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                        if sys.platform.startswith("win")
                        else {}
                    ),
                )
            except OSError as exc:
                self._process = None
                raise RuntimeError(f"Could not launch Chrome: {exc}") from exc
            self._port = target_port
            deadline = time.time() + max(1.0, timeout)
            while time.time() < deadline:
                if self._process.poll() is not None:
                    self._process = None
                    raise RuntimeError("Chrome exited before the DevTools endpoint answered")
                if self.debug_open(target_port):
                    pid = self._process.pid
                    return {"ok": True, "already_running": False, "port": target_port, "pid": pid}
                time.sleep(_LAUNCH_POLL_INTERVAL)
            self._terminate_locked()
            raise RuntimeError(f"Chrome did not answer on port {target_port} within {timeout}s")

    def stop(self) -> dict[str, Any]:
        """Terminate the managed Chrome instance, if any."""

        with self._lock:
            process, self._process = self._process, None
            if process is None or process.poll() is not None:
                return {"ok": True, "was_running": False}
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)
            return {"ok": True, "was_running": True}

    def _terminate_locked(self) -> None:
        process, self._process = self._process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()


__all__ = ["ChromeDebugManager", "DEFAULT_DEBUG_PORT", "find_chrome"]
