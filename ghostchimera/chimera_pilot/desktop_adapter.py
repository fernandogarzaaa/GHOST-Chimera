"""Cross-platform desktop adapters for live desktop actions."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DesktopAdapterInfo:
    id: str
    platform: str
    supports_semantic_targeting: bool = False


class PyAutoGuiDesktopAdapter:
    """PyAutoGUI-backed adapter with a stable interface."""

    info = DesktopAdapterInfo(id="desktop.pyautogui", platform="generic", supports_semantic_targeting=False)

    def __init__(self, pg: Any) -> None:
        self.pg = pg

    def move_to(self, x: int, y: int) -> None:
        self.pg.moveTo(int(x), int(y))

    def click(self) -> None:
        self.pg.click()

    def double_click(self) -> None:
        self.pg.doubleClick()

    def right_click(self) -> None:
        self.pg.rightClick()

    def type_text(self, text: str, interval: float = 0.01) -> None:
        self.pg.write(text, interval=interval)

    def hotkey(self, keys: list[str]) -> None:
        self.pg.hotkey(*keys)

    def screenshot(self, path: str) -> None:
        try:
            self.pg.screenshot(path)
            return
        except TypeError:
            image = self.pg.screenshot()
        if not hasattr(image, "save"):
            raise RuntimeError("pyautogui screenshot result cannot be saved")
        image.save(path)


class MacOSDesktopAdapter(PyAutoGuiDesktopAdapter):
    info = DesktopAdapterInfo(id="desktop.pyautogui.macos", platform="macos", supports_semantic_targeting=False)


class WindowsDesktopAdapter(PyAutoGuiDesktopAdapter):
    info = DesktopAdapterInfo(id="desktop.pyautogui.windows", platform="windows", supports_semantic_targeting=False)


class LinuxDesktopAdapter(PyAutoGuiDesktopAdapter):
    info = DesktopAdapterInfo(id="desktop.pyautogui.linux", platform="linux", supports_semantic_targeting=False)


def build_desktop_adapter(pg: Any, system_name: str | None = None) -> PyAutoGuiDesktopAdapter:
    system_value = (system_name or platform.system() or "").strip().lower()
    if system_value == "darwin":
        return MacOSDesktopAdapter(pg)
    if system_value == "windows":
        return WindowsDesktopAdapter(pg)
    if system_value == "linux":
        return LinuxDesktopAdapter(pg)
    return PyAutoGuiDesktopAdapter(pg)

