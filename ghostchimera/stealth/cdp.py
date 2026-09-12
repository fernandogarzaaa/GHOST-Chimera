"""Minimal Chrome DevTools Protocol client for live browser perception and action.

Connects to a Chrome instance started with remote debugging enabled, for
example ``chrome --remote-debugging-port=9222``. Ghost never launches the
browser itself; the operator starts it explicitly. All network I/O runs on a
private background thread so callers stay synchronous.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import itertools
import json
import threading
import urllib.request
from contextlib import suppress
from typing import Any


class CdpError(RuntimeError):
    """Raised when the browser endpoint is unreachable or reports an error."""


def list_targets(host: str = "127.0.0.1", port: int = 9222, *, timeout: float = 5.0) -> list[dict[str, Any]]:
    """Return debuggable targets from the browser's HTTP endpoint."""

    url = f"http://{host}:{port}/json/list"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise CdpError(f"Chrome DevTools endpoint unreachable at {url}: {exc}") from exc
    if not isinstance(payload, list):
        raise CdpError(f"Unexpected DevTools response from {url}")
    return [target for target in payload if isinstance(target, dict)]


def probe(host: str = "127.0.0.1", port: int = 9222, *, timeout: float = 5.0) -> bool:
    """Return True when a DevTools endpoint answers."""

    try:
        list_targets(host, port, timeout=timeout)
    except CdpError:
        return False
    return True


def chrome_remote_debugging_command(port: int = 9222, user_data_dir: str = "") -> str:
    """Return the command the operator runs to expose a debuggable Chrome."""

    profile = f' --user-data-dir="{user_data_dir}"' if user_data_dir else ""
    return f"chrome --remote-debugging-port={port}{profile}"


def page_websocket_url(host: str = "127.0.0.1", port: int = 9222, *, timeout: float = 5.0) -> str:
    """Return the WebSocket URL of the first debuggable page target."""

    for target in list_targets(host, port, timeout=timeout):
        url = str(target.get("webSocketDebuggerUrl", ""))
        if target.get("type") == "page" and url:
            return url
    raise CdpError("No debuggable page target found; open a tab in the debug Chrome instance")


class CdpClient:
    """Synchronous CDP session backed by a private asyncio thread."""

    def __init__(self, ws_url: str, *, timeout: float = 30.0) -> None:
        self.ws_url = ws_url
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._loop = asyncio.new_event_loop()
        self._connection: Any = None
        self._thread = threading.Thread(target=self._serve, name="ghost-cdp", daemon=True)
        self._thread.start()
        self._call("connect")

    def _serve(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=self.timeout + 10.0)

    def _call(self, action: str, *args: Any) -> Any:
        return self._submit(self._dispatch(action, *args))

    async def _dispatch(self, action: str, *args: Any) -> Any:
        if action == "connect":
            import websockets

            try:
                self._connection = await asyncio.wait_for(
                    websockets.connect(self.ws_url, max_size=32 * 1024 * 1024), timeout=self.timeout
                )
            except Exception as exc:
                raise CdpError(f"Cannot connect to {self.ws_url}: {exc}") from exc
            await self._send("Page.enable", {})
            await self._send("DOM.enable", {})
            await self._send("Runtime.enable", {})
            return True
        if action == "close":
            connection, self._connection = self._connection, None
            if connection is not None:
                with suppress(Exception):
                    await connection.close()
            self._loop.call_soon_threadsafe(self._loop.stop)
            return True
        if self._connection is None:
            raise CdpError("CDP session is closed")
        method, params = action, args[0] if args else {}
        return await self._send(method, params)

    async def _send(self, method: str, params: dict[str, Any]) -> Any:
        assert self._connection is not None
        call_id = next(self._ids)
        await self._connection.send(json.dumps({"id": call_id, "method": method, "params": params}))
        deadline = self._loop.time() + self.timeout
        while True:
            remaining = deadline - self._loop.time()
            if remaining <= 0:
                raise CdpError(f"Timed out waiting for {method} response")
            try:
                raw = await asyncio.wait_for(self._connection.recv(), timeout=remaining)
            except TimeoutError as exc:
                raise CdpError(f"Timed out waiting for {method} response") from exc
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict) or message.get("id") != call_id:
                continue
            if "error" in message:
                raise CdpError(f"{method} failed: {message['error']}")
            return message.get("result", {})

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a raw CDP command and return its result payload."""

        return self._call(method, params or {})

    def navigate(self, url: str, *, wait_for_load: bool = True) -> dict[str, Any]:
        """Navigate the page, optionally waiting for the load event."""

        self._submit(self._navigate_and_wait(url) if wait_for_load else self._dispatch("Page.navigate", {"url": url}))
        return {"url": url, "loaded": wait_for_load}

    async def _navigate_and_wait(self, url: str) -> None:
        await self._send("Page.navigate", {"url": url})
        deadline = self._loop.time() + self.timeout
        assert self._connection is not None
        while True:
            remaining = deadline - self._loop.time()
            if remaining <= 0:
                raise CdpError("Timed out waiting for page load")
            try:
                raw = await asyncio.wait_for(self._connection.recv(), timeout=remaining)
            except TimeoutError as exc:
                raise CdpError("Timed out waiting for page load") from exc
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("method") == "Page.loadEventFired":
                return

    def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript in the page and return the JSON value."""

        result = self._call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        payload = result.get("result", {}) if isinstance(result, dict) else {}
        return payload.get("value")

    def describe(self, *, max_chars: int = 4000) -> dict[str, Any]:
        """Return title, URL, and visible text of the current page."""

        text = self.evaluate(
            "({title: document.title, url: location.href, "
            "text: (document.body ? document.body.innerText : '').slice(0, " + str(max(0, max_chars)) + ")})"
        )
        if not isinstance(text, dict):
            return {"title": "", "url": "", "text": ""}
        return {
            "title": str(text.get("title", "")),
            "url": str(text.get("url", "")),
            "text": str(text.get("text", "")),
        }

    def click(self, selector: str) -> bool:
        """Click the first element matching a CSS selector."""

        return bool(
            self.evaluate(
                "(sel => { const el = document.querySelector(sel); if (!el) return false; el.click(); return true; })("
                + json.dumps(selector)
                + ")"
            )
        )

    def type_text(self, selector: str, text: str) -> bool:
        """Replace the value of an input and dispatch input events."""

        return bool(
            self.evaluate(
                "(args => { const el = document.querySelector(args.sel); if (!el) return false;"
                " el.focus(); el.value = args.text;"
                " el.dispatchEvent(new Event('input', {bubbles: true}));"
                " el.dispatchEvent(new Event('change', {bubbles: true})); return true; })("
                + json.dumps({"sel": selector, "text": text})
                + ")"
            )
        )

    def screenshot(self) -> bytes:
        """Capture a PNG screenshot of the current viewport."""

        result = self._call("Page.captureScreenshot", {"format": "png"})
        data = result.get("data", "") if isinstance(result, dict) else ""
        try:
            return base64.b64decode(data)
        except (binascii.Error, ValueError) as exc:
            raise CdpError(f"Invalid screenshot payload: {exc}") from exc

    def close(self) -> None:
        """Close the session and stop the background thread."""

        with suppress(Exception):
            self._call("close")
        self._thread.join(timeout=5.0)


__all__ = [
    "CdpClient",
    "CdpError",
    "chrome_remote_debugging_command",
    "list_targets",
    "page_websocket_url",
    "probe",
]
