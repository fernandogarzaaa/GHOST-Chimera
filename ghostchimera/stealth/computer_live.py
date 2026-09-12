"""Live Computer Use backends: real browser, desktop, and vision execution.

Planning, policy, and approvals stay in :mod:`ghostchimera.stealth.computer`.
This module supplies executors that perform approved actions:

- ``CdpBrowserExecutor`` drives a Chrome instance the operator started with
  remote debugging enabled.
- ``PyAutoGuiDesktopExecutor`` drives the local desktop through the existing
  Chimera Pilot desktop adapter (requires the ``desktop`` extra).
- ``OpenCodeVisionExecutor`` answers visual questions through the OpenCode
  CLI provider, attaching screenshot files with ``opencode run --file``.

Nothing here launches browsers, installs packages, or bypasses approval:
executors only run inside :meth:`ComputerUseManager.execute` after the plan
is approved, and :func:`attach_live_backends` leaves the default-deny
posture for anything not explicitly attached.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .computer import (
    ComputerCapability,
    ComputerModality,
    ComputerRisk,
    ComputerUseManager,
    DelegatingComputerProvider,
)


class CdpBrowserExecutor:
    """Execute browser actions through a live CDP session."""

    def __init__(self, cdp: Any) -> None:
        self._cdp = cdp

    def __call__(self, action: dict[str, Any]) -> dict[str, Any]:
        operation = str(action.get("operation", ""))
        target = str(action.get("target", ""))
        parameters = action.get("parameters") or {}
        if operation in ("browser.read", "ui.read"):
            return {"page": self._cdp.describe()}
        if operation == "browser.navigate":
            return self._cdp.navigate(target or str(parameters.get("url", "")))
        if operation in ("browser.click", "ui.click"):
            selector = target or str(parameters.get("selector", ""))
            return {"clicked": self._cdp.click(selector), "selector": selector}
        if operation in ("browser.type", "ui.type"):
            selector = target or str(parameters.get("selector", ""))
            text = str(parameters.get("text", ""))
            return {"typed": self._cdp.type_text(selector, text), "selector": selector}
        raise RuntimeError(f"Unsupported browser operation: {operation}")


class PyAutoGuiDesktopExecutor:
    """Execute desktop actions through PyAutoGUI (``desktop`` extra)."""

    def __init__(self, adapter: Any | None = None) -> None:
        if adapter is None:
            try:
                import pyautogui
            except ImportError as exc:
                raise RuntimeError("Desktop computer use needs PyAutoGUI: pip install 'ghostchimera[desktop]'") from exc
            from ..chimera_pilot.desktop_adapter import build_desktop_adapter

            adapter = build_desktop_adapter(pyautogui)
        self._adapter = adapter

    @staticmethod
    def _coordinates(target: str, parameters: dict[str, Any]) -> tuple[int, int]:
        raw = target or str(parameters.get("at", ""))
        try:
            x_text, y_text = raw.split(",", 1)
            return int(x_text.strip()), int(y_text.strip())
        except (ValueError, AttributeError) as exc:
            raise RuntimeError(f"Desktop click needs 'x,y' coordinates, got {raw!r}") from exc

    def __call__(self, action: dict[str, Any]) -> dict[str, Any]:
        operation = str(action.get("operation", ""))
        target = str(action.get("target", ""))
        parameters = action.get("parameters") or {}
        if operation == "desktop.read":
            path = str(parameters.get("path") or "")
            if not path:
                handle, path = tempfile.mkstemp(prefix="ghost-desktop-", suffix=".png")
                os.close(handle)
            self._adapter.screenshot(path)
            return {"screenshot_path": path}
        if operation == "desktop.click":
            x, y = self._coordinates(target, parameters)
            self._adapter.move_to(x, y)
            self._adapter.click()
            return {"clicked": True, "at": [x, y]}
        if operation == "desktop.type":
            text = str(parameters.get("text", target))
            self._adapter.type_text(text)
            return {"typed": True, "chars": len(text)}
        if operation == "desktop.press":
            keys = parameters.get("keys", [])
            key_list = [keys] if isinstance(keys, str) else [str(key) for key in keys]
            if not key_list:
                raise RuntimeError("Desktop press needs parameters.keys")
            self._adapter.hotkey(key_list)
            return {"pressed": True, "keys": key_list}
        if operation == "desktop.wait":
            seconds = min(30.0, max(0.0, float(parameters.get("seconds", 1.0))))
            time.sleep(seconds)
            return {"waited": seconds}
        raise RuntimeError(f"Unsupported desktop operation: {operation}")


class OpenCodeVisionExecutor:
    """Answer visual questions through the OpenCode CLI provider."""

    DEFAULT_PROMPT = (
        "Describe what is visible in the attached screenshot image, focusing on "
        "UI elements, text, and anything that looks like an error or dialog."
    )

    def __init__(self, provider: Any | None = None) -> None:
        if provider is None:
            from ..model_layer.opencode_cli_provider import OpenCodeCliProvider

            provider = OpenCodeCliProvider()
        self._provider = provider

    def __call__(self, action: dict[str, Any]) -> dict[str, Any]:
        parameters = action.get("parameters") or {}
        path = str(parameters.get("screenshot_path") or parameters.get("image_path") or "")
        if not path or not Path(path).is_file():
            raise RuntimeError("Vision analysis needs parameters.screenshot_path pointing at an image file")
        prompt = str(parameters.get("prompt") or self.DEFAULT_PROMPT)
        analysis = self._provider.chat_with_files(
            "You are the vision backend for Ghost Chimera computer use. Answer concisely.",
            prompt,
            [path],
        )
        return {"analysis": analysis, "screenshot_path": path}


LIVE_OPERATIONS = frozenset(
    {
        "browser.read",
        "browser.click",
        "browser.type",
        "browser.navigate",
        "desktop.read",
        "desktop.click",
        "desktop.type",
        "desktop.press",
        "desktop.wait",
        "vision.read",
        "vision.capture",
        "vision.locate",
        "ui.read",
        "ui.click",
        "ui.type",
    }
)


def live_capability(name: str = "live") -> ComputerCapability:
    """Default-deny-except-explicit capability for attached live backends."""

    return ComputerCapability(
        name=name,
        enabled=True,
        allowed_modalities=frozenset({ComputerModality.BROWSER, ComputerModality.DESKTOP, ComputerModality.VISION}),
        allowed_operations=LIVE_OPERATIONS,
        max_risk=ComputerRisk.MEDIUM,
    )


def attach_live_backends(
    loop: Any,
    *,
    browser: Any = None,
    desktop: Any = False,
    vision: Any = None,
    capability: ComputerCapability | None = None,
) -> dict[str, Any]:
    """Attach live executors to a loop's ComputerUse manager.

    Arguments accept a ready executor, a ready client object, or True to
    build the default (CDP sessions and vision models must still be supplied
    explicitly; only the desktop adapter self-builds from PyAutoGUI).
    """

    attached: dict[str, Any] = {"browser": None, "desktop": None, "vision": None}
    manager: ComputerUseManager = loop.computer
    if browser is not None and browser is not False:
        if isinstance(browser, str):
            from .cdp import CdpClient

            browser = CdpClient(browser)
        if hasattr(browser, "describe") and not callable(browser):
            executor: Any = CdpBrowserExecutor(browser)
        else:
            executor = browser
        manager.register(
            DelegatingComputerProvider(name="live-browser", modality=ComputerModality.BROWSER, executor=executor)
        )
        attached["browser"] = "live-browser"
    if desktop:
        executor = desktop if callable(desktop) else PyAutoGuiDesktopExecutor(None if desktop is True else desktop)
        manager.register(
            DelegatingComputerProvider(name="live-desktop", modality=ComputerModality.DESKTOP, executor=executor)
        )
        attached["desktop"] = "live-desktop"
    if vision is not None and vision is not False:
        executor = vision if callable(vision) else OpenCodeVisionExecutor(None if vision is True else vision)
        manager.register(
            DelegatingComputerProvider(name="live-vision", modality=ComputerModality.VISION, executor=executor)
        )
        attached["vision"] = "live-vision"
    loop.computer_capability = capability or live_capability()
    attached["capability"] = loop.computer_capability.name
    return attached


def attach_managed_browser(loop: Any, manager: Any, *, capability: ComputerCapability | None = None) -> dict[str, Any]:
    """Attach the console-managed debuggable Chrome to a loop.

    The manager must already have debugging open (the operator launches it
    from the console); this only connects, never launches.
    """

    from .cdp import CdpClient

    return attach_live_backends(loop, browser=CdpClient(manager.debug_websocket_url()), capability=capability)


__all__ = [
    "LIVE_OPERATIONS",
    "CdpBrowserExecutor",
    "OpenCodeVisionExecutor",
    "PyAutoGuiDesktopExecutor",
    "attach_live_backends",
    "attach_managed_browser",
    "live_capability",
]
