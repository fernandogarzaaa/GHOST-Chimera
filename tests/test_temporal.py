"""Tests for temporal context (framing of now plus upcoming items)."""

from __future__ import annotations

import unittest
from datetime import datetime

from ghostchimera.stealth.events import new_event
from ghostchimera.stealth.temporal import TemporalContext, daypart, is_quiet_hours


def _at(hour: int, day: int = 15) -> float:
    return datetime(2026, 9, day, hour, 0).timestamp()


def _cal(event_type: str = "calendar.event_created", timestamp: float = 1000.0, **payload) -> object:
    base = {"event_id": "cal-1", "title": "Standup", "starts_at": 2000.0, "ends_at": 2300.0}
    base.update(payload)
    return new_event(event_type, source="calendar", payload=base, timestamp=timestamp)


class IngestTests(unittest.TestCase):
    def test_created_updated_and_starting(self) -> None:
        context = TemporalContext()

        self.assertTrue(context.observe_event(_cal()))
        self.assertEqual(len(context), 1)
        self.assertTrue(context.observe_event(_cal("calendar.event_updated", starts_at=2100.0)))
        self.assertEqual(len(context), 1)
        self.assertEqual(context.upcoming(now=1000.0)[0].starts_at, 2100.0)
        self.assertTrue(context.observe_event(_cal("calendar.event_starting", timestamp=2050.0)))
        self.assertEqual(len(context), 1)

    def test_non_calendar_and_startless_ignored(self) -> None:
        context = TemporalContext()

        self.assertFalse(context.observe_event(new_event("email.received", source="gmail", timestamp=1000.0)))
        self.assertFalse(
            context.observe_event(_cal(timestamp=1000.0, starts_at=None, event_id="cal-x", title="No time"))
        )
        self.assertEqual(len(context), 0)

    def test_prune_keeps_grace_window(self) -> None:
        context = TemporalContext()
        context.observe_event(_cal())

        self.assertEqual(context.prune(now=2300.0 + 899.0), 0)
        self.assertEqual(len(context), 1)
        self.assertEqual(context.prune(now=2300.0 + 900.0), 1)
        self.assertEqual(len(context), 0)


class QueryTests(unittest.TestCase):
    def _two_meetings(self) -> TemporalContext:
        context = TemporalContext()
        context.observe_event(_cal(event_id="a", title="Early", starts_at=2000.0, ends_at=2100.0))
        context.observe_event(_cal(event_id="b", title="Late", starts_at=3000.0, ends_at=3100.0))
        return context

    def test_happening_now(self) -> None:
        context = self._two_meetings()

        self.assertEqual([item.title for item in context.happening_now(now=2050.0)], ["Early"])
        self.assertEqual(context.happening_now(now=2500.0), [])

    def test_upcoming_window_and_limit(self) -> None:
        context = self._two_meetings()

        self.assertEqual([item.title for item in context.upcoming(now=1000.0)], ["Early", "Late"])
        self.assertEqual([item.title for item in context.upcoming(now=1000.0, within_s=500.0)], [])
        self.assertEqual([item.title for item in context.upcoming(now=1000.0, limit=1)], ["Early"])
        self.assertEqual(context.upcoming(now=1000.0, limit=0), [])


class FramingTests(unittest.TestCase):
    def test_dayparts_and_quiet_hours(self) -> None:
        self.assertEqual(daypart(_at(6)), "morning")
        self.assertEqual(daypart(_at(13)), "afternoon")
        self.assertEqual(daypart(_at(19)), "evening")
        self.assertEqual(daypart(_at(23)), "night")
        self.assertFalse(is_quiet_hours(_at(9)))
        self.assertTrue(is_quiet_hours(_at(23)))
        self.assertTrue(is_quiet_hours(_at(6)))

    def test_describe_names_weekday(self) -> None:
        context = TemporalContext()

        self.assertIn("Tuesday morning", context.describe(_at(10)))


class RenderTests(unittest.TestCase):
    def test_block_with_now_and_next(self) -> None:
        context = TemporalContext()
        context.observe_event(_cal(event_id="a", title="Early", starts_at=2000.0, ends_at=2100.0))
        context.observe_event(_cal(event_id="b", title="Late", starts_at=3000.0, ends_at=3100.0))
        block = context.render(now=2050.0)

        self.assertIn("# Temporal context", block)
        self.assertIn("now: Early", block)
        self.assertIn("next: Late", block)

    def test_empty_and_truncation(self) -> None:
        context = TemporalContext()

        self.assertIn("no upcoming items", context.render(now=1000.0).lower())
        context.observe_event(_cal(event_id="a", title="Early", starts_at=2000.0, ends_at=2100.0))
        short = context.render(now=1000.0, max_chars=30)

        self.assertIn("truncated", short)


class PersistenceTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        context = TemporalContext()
        context.observe_event(_cal())
        restored = TemporalContext.from_dict(context.to_dict())

        self.assertEqual(len(restored), 1)
        self.assertEqual(restored.upcoming(now=1000.0)[0].title, "Standup")

    def test_startless_items_dropped(self) -> None:
        restored = TemporalContext.from_dict({"items": [{"id": "x", "title": "No time"}]})

        self.assertEqual(len(restored), 0)


class LoopIntegrationTests(unittest.TestCase):
    def test_calendar_event_reaches_temporal_block(self) -> None:
        from ghostchimera.stealth import StealthLoop

        loop = StealthLoop()
        try:
            loop.emit(_cal(timestamp=1000.0))
            block = loop.get_temporal_context(now=1500.0)

            self.assertIn("Standup", block)
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
