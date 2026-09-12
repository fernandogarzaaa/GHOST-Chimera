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
import time
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


def browser_websocket_url(host: str = "127.0.0.1", port: int = 9222, *, timeout: float = 5.0) -> str:
    """Return the browser-level WebSocket URL for tab management."""

    url = f"http://{host}:{port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise CdpError(f"Chrome DevTools endpoint unreachable at {url}: {exc}") from exc
    ws_url = str(payload.get("webSocketDebuggerUrl", "")) if isinstance(payload, dict) else ""
    if not ws_url:
        raise CdpError(f"No browser WebSocket URL at {url}")
    return ws_url


class _CdpConnection:
    """Synchronous CDP session backed by a private asyncio thread."""

    _enable_domains: tuple[str, ...] = ()

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
            for domain in self._enable_domains:
                await self._send(f"{domain}.enable", {})
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

    def close(self) -> None:
        """Close the session and stop the background thread."""

        with suppress(Exception):
            self._call("close")
        self._thread.join(timeout=5.0)


class CdpClient(_CdpConnection):
    """Page-level session: perception and action inside one tab."""

    _enable_domains = ("Page", "DOM", "Runtime")

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

    def back(self) -> bool:
        """Navigate back in history."""

        return bool(self.evaluate("window.history.back(); true"))

    def forward(self) -> bool:
        """Navigate forward in history."""

        return bool(self.evaluate("window.history.forward(); true"))

    def reload(self) -> bool:
        """Reload the current page."""

        return bool(self.evaluate("location.reload(); true"))

    def fill_form(self, fields: dict[str, str]) -> dict[str, bool]:
        """Fill multiple inputs keyed by CSS selector."""

        return {selector: self.type_text(selector, str(value)) for selector, value in fields.items()}

    def select_option(self, selector: str, value: str) -> bool:
        """Choose an option in a select element."""

        return bool(
            self.evaluate(
                "(args => { const el = document.querySelector(args.sel); if (!el) return false;"
                " el.value = args.value;"
                " el.dispatchEvent(new Event('input', {bubbles: true}));"
                " el.dispatchEvent(new Event('change', {bubbles: true})); return true; })("
                + json.dumps({"sel": selector, "value": value})
                + ")"
            )
        )

    def set_checked(self, selector: str, checked: bool = True) -> bool:
        """Set a checkbox or radio input."""

        return bool(
            self.evaluate(
                "(args => { const el = document.querySelector(args.sel); if (!el) return false;"
                " el.checked = args.checked;"
                " el.dispatchEvent(new Event('input', {bubbles: true}));"
                " el.dispatchEvent(new Event('change', {bubbles: true})); return true; })("
                + json.dumps({"sel": selector, "checked": checked})
                + ")"
            )
        )

    def submit(self, selector: str | None = None) -> bool:
        """Submit a form by selector, or the first form on the page."""

        target = json.dumps(selector)
        return bool(
            self.evaluate(
                "(sel => { const form = sel ? document.querySelector(sel) : document.querySelector('form');"
                " if (!form || form.tagName !== 'FORM') return false;"
                " if (typeof form.requestSubmit === 'function') { form.requestSubmit(); } else { form.submit(); }"
                " return true; })(" + target + ")"
            )
        )

    def hover(self, selector: str) -> bool:
        """Dispatch hover mouse events on the first matching element."""

        return bool(
            self.evaluate(
                "(sel => { const el = document.querySelector(sel); if (!el) return false;"
                " const rect = el.getBoundingClientRect();"
                " const opts = {bubbles: true, clientX: rect.left + 1, clientY: rect.top + 1};"
                " el.dispatchEvent(new MouseEvent('mouseover', opts));"
                " el.dispatchEvent(new MouseEvent('mousemove', opts)); return true; })(" + json.dumps(selector) + ")"
            )
        )

    def scroll_to(self, target: str = "bottom") -> bool:
        """Scroll to top/bottom, x,y coordinates, or a CSS selector into view."""

        return bool(
            self.evaluate(
                "(target => {"
                " if (target === 'top') { window.scrollTo(0, 0); return true; }"
                " if (target === 'bottom') { window.scrollTo(0, document.body.scrollHeight); return true; }"
                " const coords = target.split(',');"
                " if (coords.length === 2 && !isNaN(Number(coords[0])) && !isNaN(Number(coords[1]))) {"
                " window.scrollTo(Number(coords[0]), Number(coords[1])); return true; }"
                " const el = document.querySelector(target);"
                " if (!el) return false; el.scrollIntoView(); return true; })(" + json.dumps(target) + ")"
            )
        )

    def wait_for_text(self, text: str, *, timeout: float = 10.0) -> bool:
        """Poll visible text until it appears or the timeout expires."""

        needle = json.dumps(text)
        deadline = time.time() + max(0.0, timeout)
        while True:
            found = self.evaluate(f"document.body ? document.body.innerText.includes({needle}) : false")
            if found:
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.25)

    def html(self, *, max_chars: int = 20000) -> str:
        """Return the page markup, truncated."""

        markup = self.evaluate("document.documentElement.outerHTML.slice(0, " + str(max(0, max_chars)) + ")")
        return str(markup or "")


class CdpBrowser(_CdpConnection):
    """Browser-level session: tab management across the debug Chrome."""

    def list_tabs(self) -> list[dict[str, Any]]:
        """Return debuggable targets visible to this browser session."""

        result = self._call("Target.getTargets", {})
        targets = result.get("targetInfos", []) if isinstance(result, dict) else []
        return [target for target in targets if isinstance(target, dict)]

    def new_tab(self, url: str = "about:blank") -> dict[str, Any]:
        """Open a new tab and return its target record."""

        result = self._call("Target.createTarget", {"url": url})
        if not isinstance(result, dict) or not result.get("targetId"):
            raise CdpError(f"Could not open tab for {url}: {result!r}")
        return {"target_id": result["targetId"], "url": url}

    def close_tab(self, target_id: str) -> bool:
        """Close the tab with the given target ID."""

        result = self._call("Target.closeTarget", {"targetId": target_id})
        return bool(result.get("success", False)) if isinstance(result, dict) else False

    def activate_tab(self, target_id: str) -> None:
        """Bring the tab with the given target ID to the front."""

        self._call("Target.activateTarget", {"targetId": target_id})


__all__ = [
    "CdpBrowser",
    "CdpClient",
    "CdpError",
    "browser_websocket_url",
    "chrome_remote_debugging_command",
    "list_targets",
    "page_websocket_url",
    "probe",
]


__all__ = [
    "CdpClient",
    "CdpError",
    "chrome_remote_debugging_command",
    "list_targets",
    "page_websocket_url",
    "probe",
]
