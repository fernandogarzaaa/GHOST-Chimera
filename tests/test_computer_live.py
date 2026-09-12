"""Tests for live computer-use backends and loop attachment."""

from __future__ import annotations

import sys
import unittest
from unittest import mock

from ghostchimera.stealth import (
    ComputerApproval,
    StealthLoop,
)
from ghostchimera.stealth.computer_live import (
    CdpBrowserExecutor,
    OpenCodeVisionExecutor,
    PyAutoGuiDesktopExecutor,
    attach_live_backends,
    live_capability,
)
from ghostchimera.stealth.hosts import OpenCodeAdapter
from ghostchimera.stealth.intervention import InterventionState


class FakeCdp:
    def __init__(self) -> None:
        self.calls: list = []

    def describe(self) -> dict:
        self.calls.append(("describe",))
        return {"title": "T", "url": "https://example.test", "text": "hi"}

    def navigate(self, url: str) -> dict:
        self.calls.append(("navigate", url))
        return {"url": url, "loaded": True}

    def click(self, selector: str) -> bool:
        self.calls.append(("click", selector))
        return True

    def type_text(self, selector: str, text: str) -> bool:
        self.calls.append(("type", selector, text))
        return True

    def back(self) -> bool:
        self.calls.append(("back",))
        return True

    def fill_form(self, fields: dict) -> dict:
        self.calls.append(("fill", fields))
        return {key: True for key in fields}

    def select_option(self, selector: str, value: str) -> bool:
        self.calls.append(("select", selector, value))
        return True

    def hover(self, selector: str) -> bool:
        self.calls.append(("hover", selector))
        return True

    def scroll_to(self, target: str = "bottom") -> bool:
        self.calls.append(("scroll", target))
        return True

    def wait_for_text(self, text: str, *, timeout: float = 10.0) -> bool:
        self.calls.append(("wait_for", text))
        return True

    def html(self, *, max_chars: int = 20000) -> str:
        self.calls.append(("html",))
        return "<html>fake</html>"


class FakeDesktopAdapter:
    def __init__(self) -> None:
        self.calls: list = []

    def move_to(self, x: int, y: int) -> None:
        self.calls.append(("move_to", x, y))

    def click(self) -> None:
        self.calls.append(("click",))

    def type_text(self, text: str, interval: float = 0.01) -> None:
        self.calls.append(("type_text", text))

    def hotkey(self, keys: list) -> None:
        self.calls.append(("hotkey", keys))

    def screenshot(self, path: str) -> None:
        self.calls.append(("screenshot", path))
        with open(path, "wb") as handle:
            handle.write(b"fake-png")


class FakeVisionProvider:
    def __init__(self) -> None:
        self.calls: list = []

    def chat_with_files(self, system: str, prompt: str, files: list) -> str:
        self.calls.append((prompt, files))
        return "a login dialog"


class BrowserExecutorTests(unittest.TestCase):
    def test_routes_browser_and_generic_operations(self) -> None:
        cdp = FakeCdp()
        executor = CdpBrowserExecutor(cdp)

        self.assertIn("T", str(executor({"operation": "browser.read"})))
        self.assertEqual(
            executor({"operation": "browser.navigate", "target": "https://x.test"})["url"], "https://x.test"
        )
        self.assertTrue(executor({"operation": "ui.click", "target": "#go"})["clicked"])
        self.assertTrue(executor({"operation": "ui.type", "target": "#q", "parameters": {"text": "hi"}})["typed"])
        with self.assertRaises(RuntimeError):
            executor({"operation": "browser.launch"})

    def test_extended_browser_operations_and_fenced_read(self) -> None:
        from ghostchimera.stealth.untrusted import is_fenced

        cdp = FakeCdp()
        executor = CdpBrowserExecutor(cdp)

        self.assertTrue(executor({"operation": "browser.back"})["done"])
        self.assertEqual(
            executor({"operation": "browser.fill", "parameters": {"fields": {"#a": "1"}}})["filled"], {"#a": True}
        )
        self.assertTrue(
            executor({"operation": "browser.select", "target": "#s", "parameters": {"value": "v"}})["selected"]
        )
        self.assertTrue(executor({"operation": "browser.hover", "target": "#h"})["hovered"])
        self.assertTrue(executor({"operation": "browser.scroll", "parameters": {"to": "bottom"}})["scrolled"])
        self.assertTrue(executor({"operation": "browser.wait_for", "parameters": {"text": "done"}})["found"])

        read = executor({"operation": "browser.read"})
        self.assertTrue(is_fenced(read["page"]["text"]))
        self.assertIn("https://example.test", read["page"]["text"])

        html = executor({"operation": "browser.html", "target": "https://example.test"})
        self.assertTrue(is_fenced(html["html"]))


class DesktopExecutorTests(unittest.TestCase):
    def test_routes_desktop_operations(self) -> None:
        adapter = FakeDesktopAdapter()
        executor = PyAutoGuiDesktopExecutor(adapter)

        self.assertEqual(executor({"operation": "desktop.click", "parameters": {"at": "10, 20"}})["at"], [10, 20])
        self.assertEqual(executor({"operation": "desktop.type", "parameters": {"text": "hi"}})["chars"], 2)
        self.assertEqual(
            executor({"operation": "desktop.press", "parameters": {"keys": ["ctrl", "s"]}})["keys"], ["ctrl", "s"]
        )
        shot = executor({"operation": "desktop.read", "parameters": {}})
        self.assertTrue(shot["screenshot_path"].endswith(".png"))
        self.assertIn("screenshot", [call[0] for call in adapter.calls])

    def test_bad_coordinates_rejected(self) -> None:
        executor = PyAutoGuiDesktopExecutor(FakeDesktopAdapter())
        with self.assertRaises(RuntimeError):
            executor({"operation": "desktop.click", "parameters": {"at": "nowhere"}})

    def test_missing_pyautogui_raises_with_install_hint(self) -> None:
        with mock.patch.dict(sys.modules, {"pyautogui": None}), self.assertRaises(RuntimeError) as exc:
            PyAutoGuiDesktopExecutor(None)
        self.assertIn("ghostchimera[desktop]", str(exc.exception))


class VisionExecutorTests(unittest.TestCase):
    def test_analyzes_screenshot_file(self) -> None:
        import tempfile

        provider = FakeVisionProvider()
        executor = OpenCodeVisionExecutor(provider)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"fake-png")
            path = tmp.name
        try:
            result = executor({"operation": "vision.read", "parameters": {"screenshot_path": path}})
        finally:
            import os

            os.unlink(path)

        self.assertEqual(result["analysis"], "a login dialog")
        self.assertEqual(result["screenshot_path"], path)

    def test_missing_screenshot_rejected(self) -> None:
        executor = OpenCodeVisionExecutor(FakeVisionProvider())
        with self.assertRaises(RuntimeError):
            executor({"operation": "vision.read", "parameters": {}})


class AttachLiveBackendsTests(unittest.TestCase):
    def test_attach_registers_live_providers_and_preserves_approvals(self) -> None:
        from ghostchimera.stealth import new_event

        loop = StealthLoop(computer_capability=live_capability())
        try:
            attached = attach_live_backends(loop, browser=FakeCdp(), vision=FakeVisionProvider())
            self.assertEqual(attached["browser"], "live-browser")
            self.assertEqual(attached["vision"], "live-vision")
            self.assertIsNone(attached["desktop"])

            planned = loop.request_computer_use(
                {"operation": "browser.read", "target": "page"}, workflow="browse", dry_run=True
            )
            self.assertTrue(planned["ok"])
            self.assertEqual(planned["plan"]["provider"], "live-browser")

            denied = loop.request_computer_use(
                {"operation": "browser.read", "target": "page", "action_id": planned["plan"]["action"]["action_id"]},
                workflow="browse",
            )
            self.assertFalse(denied["ok"])

            approval = ComputerApproval(approved_by="operator", action_id=planned["plan"]["action"]["action_id"])
            executed = loop.request_computer_use(
                {"operation": "browser.read", "target": "page", "action_id": planned["plan"]["action"]["action_id"]},
                workflow="browse",
                approval=approval,
            )
            self.assertTrue(executed["ok"])
            self.assertIn("https://example.test", str(executed["receipt"]))
            loop.emit(new_event("file.modified", source="fs", confidence=0.2))
            self.assertIsNotNone(loop.last_result)
        finally:
            loop.close()

    def test_new_operations_are_plannable_with_approval(self) -> None:
        loop = StealthLoop()
        try:
            attach_live_backends(loop, browser=FakeCdp())
            planned = loop.request_computer_use(
                {"operation": "browser.fill", "parameters": {"fields": {"#a": "1"}}},
                workflow="browse",
                dry_run=True,
            )
            self.assertTrue(planned["ok"])
            self.assertTrue(planned["plan"]["approval_required"])
        finally:
            loop.close()


class OpenCodeAdapterTests(unittest.TestCase):
    def test_install_manifest_and_context_block(self) -> None:
        from ghostchimera.stealth.intervention import Intervention

        loop = StealthLoop()
        try:
            adapter = OpenCodeAdapter(loop)
            manifest = adapter.install()
            self.assertEqual(manifest["plugin"]["skills"], ["ghost-context"])
            self.assertIn("/ghost", manifest["plugin"]["slash"])

            intervention = Intervention(
                trigger_event_id="evt-1",
                workflow="demo",
                confidence=0.9,
                reason="test",
                provenance={},
            )
            intervention.transition(InterventionState.QUEUED)
            intervention.transition(InterventionState.PREPARING)
            intervention.context = {
                "reason": "demo",
                "confidence": 0.9,
                "workflow": "demo",
                "items": [],
                "warnings": [],
                "provenance": {},
                "tokens": 0,
            }
            intervention.transition(InterventionState.READY)
            loop.interventions[intervention.id] = intervention
            block = adapter.context_block(intervention.id)
            self.assertTrue(block.startswith("<ghost-context>"))
            self.assertIn("Ghost", block)
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
