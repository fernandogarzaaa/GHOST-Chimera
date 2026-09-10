"""EVE Perception Hierarchy (spec section 6).

Level 0: Event perception (already done via normalized events)
Level 1: Structured perception (DOM, A11y, UIA, MCP, APIs)
Level 2: Visual perception (screenshots, OCR, vision models) - last resort
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .eve_model import EnvironmentState, PerceptionLevel
from .events import Event


@dataclass
class PerceptionResult:
    """Result of a perception request."""

    level: PerceptionLevel
    success: bool
    environment: EnvironmentState | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


class PerceptionProvider(ABC):
    """Base class for perception providers."""

    @property
    @abstractmethod
    def level(self) -> PerceptionLevel:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def perceive(self, event: Event, context: dict[str, Any]) -> PerceptionResult:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass


class EventPerceptionProvider(PerceptionProvider):
    """Level 0: Already handled by normalized Event schema."""

    @property
    def level(self) -> PerceptionLevel:
        return PerceptionLevel.EVENT

    @property
    def name(self) -> str:
        return "event"

    async def perceive(self, event: Event, context: dict[str, Any]) -> PerceptionResult:
        env = EnvironmentState(
            active_application=str(event.payload.get("application") or ""),
            active_window=str(event.payload.get("window") or ""),
            active_url=str(event.payload.get("url") or ""),
            timestamp=event.timestamp,
        )
        return PerceptionResult(
            level=self.level,
            success=True,
            environment=env,
            data={"event_type": event.event_type, "payload": event.payload},
        )

    def is_available(self) -> bool:
        return True


class StructuredPerceptionProvider(PerceptionProvider):
    """Level 1: Structured information (DOM, A11y, UIA, MCP, APIs)."""

    def __init__(self):
        self._mcp_clients: dict[str, Any] = {}

    @property
    def level(self) -> PerceptionLevel:
        return PerceptionLevel.STRUCTURED

    @property
    def name(self) -> str:
        return "structured"

    async def perceive(self, event: Event, context: dict[str, Any]) -> PerceptionResult:
        start = time.time()
        try:
            env = EnvironmentState(
                active_application=str(event.payload.get("application") or ""),
                active_window=str(event.payload.get("window") or ""),
                active_url=str(event.payload.get("url") or ""),
                timestamp=event.timestamp,
            )

            # Extract structured data from event payload
            data = {}
            if "dom" in event.payload:
                data["dom"] = event.payload["dom"]
            if "accessibility_tree" in event.payload:
                data["accessibility_tree"] = event.payload["accessibility_tree"]
            if "ui_elements" in event.payload:
                data["ui_elements"] = event.payload["ui_elements"]
            if "mcp_data" in event.payload:
                data["mcp"] = event.payload["mcp_data"]

            return PerceptionResult(
                level=self.level,
                success=True,
                environment=env,
                data=data,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return PerceptionResult(
                level=self.level,
                success=False,
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    def is_available(self) -> bool:
        return True

    def register_mcp_client(self, name: str, client: Any) -> None:
        self._mcp_clients[name] = client


class BrowserPerceptionProvider(PerceptionProvider):
    """Level 1b: Browser DevTools / CDP perception."""

    def __init__(self):
        self._cdp_sessions: dict[str, Any] = {}

    @property
    def level(self) -> PerceptionLevel:
        return PerceptionLevel.BROWSER

    @property
    def name(self) -> str:
        return "browser"

    async def perceive(self, event: Event, context: dict[str, Any]) -> PerceptionResult:
        start = time.time()
        try:
            url = str(event.payload.get("url") or event.payload.get("active_url") or "")
            if not url:
                return PerceptionResult(
                    level=self.level,
                    success=False,
                    error="No URL in event",
                    latency_ms=(time.time() - start) * 1000,
                )

            env = EnvironmentState(
                active_application="browser",
                active_url=url,
                active_window=str(event.payload.get("window") or ""),
                timestamp=event.timestamp,
            )

            # In real implementation, this would connect via CDP
            # For now, return structured data from event if available
            data = {}
            if "browser_dom" in event.payload:
                data["dom"] = event.payload["browser_dom"]
            if "browser_a11y" in event.payload:
                data["accessibility_tree"] = event.payload["browser_a11y"]
            if "console_logs" in event.payload:
                data["console"] = event.payload["console_logs"]
            if "network_requests" in event.payload:
                data["network"] = event.payload["network_requests"]

            return PerceptionResult(
                level=self.level,
                success=True,
                environment=env,
                data=data,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return PerceptionResult(
                level=self.level,
                success=False,
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    def is_available(self) -> bool:
        # Would check for CDP connection in real implementation
        return True

    def register_cdp_session(self, session_id: str, session: Any) -> None:
        self._cdp_sessions[session_id] = session


class AccessibilityPerceptionProvider(PerceptionProvider):
    """Level 1c: Accessibility tree (UIA, AT-SPI, etc.)."""

    @property
    def level(self) -> PerceptionLevel:
        return PerceptionLevel.ACCESSIBILITY

    @property
    def name(self) -> str:
        return "accessibility"

    async def perceive(self, event: Event, context: dict[str, Any]) -> PerceptionResult:
        start = time.time()
        try:
            env = EnvironmentState(
                active_application=str(event.payload.get("application") or ""),
                active_window=str(event.payload.get("window") or ""),
                active_url=str(event.payload.get("url") or ""),
                timestamp=event.timestamp,
            )

            data = {}
            if "accessibility_tree" in event.payload:
                data["accessibility_tree"] = event.payload["accessibility_tree"]
            if "focused_element" in event.payload:
                data["focused_element"] = event.payload["focused_element"]
            if "window_bounds" in event.payload:
                data["window_bounds"] = event.payload["window_bounds"]

            return PerceptionResult(
                level=self.level,
                success=True,
                environment=env,
                data=data,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return PerceptionResult(
                level=self.level,
                success=False,
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    def is_available(self) -> bool:
        # Would check for UIA/AT-SPI availability
        return True


class VisionPerceptionProvider(PerceptionProvider):
    """Level 2: Visual perception (screenshots, OCR, vision models) - LAST RESORT."""

    def __init__(self):
        self._vision_models: dict[str, Any] = {}

    @property
    def level(self) -> PerceptionLevel:
        return PerceptionLevel.VISION

    @property
    def name(self) -> str:
        return "vision"

    async def perceive(self, event: Event, context: dict[str, Any]) -> PerceptionResult:
        start = time.time()
        try:
            env = EnvironmentState(
                active_application=str(event.payload.get("application") or ""),
                active_window=str(event.payload.get("window") or ""),
                active_url=str(event.payload.get("url") or ""),
                timestamp=event.timestamp,
            )

            data = {}
            if "screenshot" in event.payload:
                data["screenshot"] = event.payload["screenshot"]
            if "ocr_text" in event.payload:
                data["ocr_text"] = event.payload["ocr_text"]
            if "vision_analysis" in event.payload:
                data["vision_analysis"] = event.payload["vision_analysis"]
            if "cursor_location" in event.payload:
                data["cursor"] = event.payload["cursor_location"]

            return PerceptionResult(
                level=self.level,
                success=True,
                environment=env,
                data=data,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return PerceptionResult(
                level=self.level,
                success=False,
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    def is_available(self) -> bool:
        # Would check for vision model availability
        return True

    def register_vision_model(self, name: str, model: Any) -> None:
        self._vision_models[name] = model


class PerceptionManager:
    """Orchestrates hierarchical perception (spec section 6)."""

    def __init__(self):
        self.providers: dict[PerceptionLevel, PerceptionProvider] = {
            PerceptionLevel.EVENT: EventPerceptionProvider(),
            PerceptionLevel.STRUCTURED: StructuredPerceptionProvider(),
            PerceptionLevel.BROWSER: BrowserPerceptionProvider(),
            PerceptionLevel.ACCESSIBILITY: AccessibilityPerceptionProvider(),
            PerceptionLevel.VISION: VisionPerceptionProvider(),
        }
        self._fallback_order = [
            PerceptionLevel.STRUCTURED,
            PerceptionLevel.BROWSER,
            PerceptionLevel.ACCESSIBILITY,
            PerceptionLevel.VISION,
        ]

    async def perceive(
        self, event: Event, requested_level: PerceptionLevel, context: dict[str, Any]
    ) -> PerceptionResult:
        """Perceive at requested level, falling back if unavailable."""
        provider = self.providers.get(requested_level)
        if not provider:
            return PerceptionResult(
                level=requested_level,
                success=False,
                error=f"No provider for level {requested_level}",
            )

        if not provider.is_available():
            # Try fallback chain
            for fallback_level in self._fallback_order:
                if fallback_level == requested_level:
                    continue
                fallback = self.providers.get(fallback_level)
                if fallback and fallback.is_available():
                    result = await fallback.perceive(event, context)
                    result.data["fallback_from"] = requested_level.value
                    return result

            return PerceptionResult(
                level=requested_level,
                success=False,
                error=f"Provider {requested_level} unavailable and no fallback",
            )

        return await provider.perceive(event, context)

    def get_available_levels(self) -> list[PerceptionLevel]:
        return [level for level, provider in self.providers.items() if provider.is_available()]


__all__ = [
    "PerceptionProvider",
    "PerceptionResult",
    "EventPerceptionProvider",
    "StructuredPerceptionProvider",
    "BrowserPerceptionProvider",
    "AccessibilityPerceptionProvider",
    "VisionPerceptionProvider",
    "PerceptionManager",
]
