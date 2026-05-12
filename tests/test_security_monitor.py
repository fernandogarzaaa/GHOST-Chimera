"""Tests for the Security Monitor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.safety_layer.security_monitor import (
    SecurityEvent,
    SecurityMonitor,
    ThreatCategory,
    get_monitor,
)


class TestSecurityEvent(unittest.TestCase):
    def test_to_dict_roundtrip(self):
        event = SecurityEvent(
            session_id="s1",
            categories=[ThreatCategory.PROMPT_INJECTION, ThreatCategory.POLICY_VIOLATION],
            risk_score=0.85,
            threats=["prompt_injection:ignore_previous"],
            action="DENY",
            blocked=True,
            text_snippet="ignore all previous",
            dpi_engine="builtin",
        )
        d = event.to_dict()
        self.assertIn("session_id", d)
        self.assertIn("categories", d)
        self.assertIn("prompt_injection", d["categories"])
        self.assertEqual(d["risk_score"], 0.85)
        self.assertTrue(d["blocked"])

    def test_from_dict_roundtrip(self):
        event = SecurityEvent(
            session_id="abc",
            categories=[ThreatCategory.CREDENTIAL_LEAK],
            risk_score=0.90,
            threats=["credential:openai_api_key"],
            action="QUARANTINE",
            blocked=True,
        )
        restored = SecurityEvent.from_dict(event.to_dict())
        self.assertEqual(restored.session_id, "abc")
        self.assertIn(ThreatCategory.CREDENTIAL_LEAK, restored.categories)
        self.assertEqual(restored.risk_score, 0.90)
        self.assertTrue(restored.blocked)

    def test_from_dict_ignores_unknown_categories(self):
        d = {"categories": ["unknown_category"], "session_id": "x"}
        event = SecurityEvent.from_dict(d)
        self.assertEqual(event.categories, [])

    def test_timestamp_set_automatically(self):
        event = SecurityEvent()
        self.assertTrue(event.timestamp.endswith("Z") or "T" in event.timestamp)


class TestSecurityMonitor(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="ghostchimera-monitor-test-")
        self.events_file = str(Path(self.tmpdir) / "security_events.json")
        self.monitor = SecurityMonitor(events_file=self.events_file)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_event(self, **kwargs) -> SecurityEvent:
        defaults = {
            "session_id": "s1",
            "categories": [ThreatCategory.PROMPT_INJECTION],
            "risk_score": 0.85,
            "threats": ["prompt_injection:test"],
            "action": "DENY",
            "blocked": True,
        }
        defaults.update(kwargs)
        return SecurityEvent(**defaults)

    # --- record + retrieve ---

    def test_record_and_get_events(self):
        self.monitor.record_event(self._make_event())
        events = self.monitor.get_events(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["session_id"], "s1")

    def test_get_events_blocked_only_filter(self):
        self.monitor.record_event(self._make_event(blocked=True))
        self.monitor.record_event(self._make_event(blocked=False, action="LOG"))
        blocked = self.monitor.get_events(blocked_only=True)
        self.assertEqual(len(blocked), 1)
        self.assertTrue(blocked[0]["blocked"])

    def test_get_events_min_risk_filter(self):
        self.monitor.record_event(self._make_event(risk_score=0.9))
        self.monitor.record_event(self._make_event(risk_score=0.2, action="ALLOW", blocked=False))
        high_risk = self.monitor.get_events(min_risk=0.5)
        self.assertEqual(len(high_risk), 1)
        self.assertEqual(high_risk[0]["risk_score"], 0.9)

    def test_get_events_category_filter(self):
        self.monitor.record_event(self._make_event(categories=[ThreatCategory.PROMPT_INJECTION]))
        self.monitor.record_event(self._make_event(categories=[ThreatCategory.CREDENTIAL_LEAK]))
        inj = self.monitor.get_events(threat_category=ThreatCategory.PROMPT_INJECTION)
        self.assertEqual(len(inj), 1)
        self.assertIn("prompt_injection", inj[0]["categories"])

    def test_get_events_session_filter(self):
        self.monitor.record_event(self._make_event(session_id="s1"))
        self.monitor.record_event(self._make_event(session_id="s2"))
        s1_events = self.monitor.get_events(session_id="s1")
        self.assertEqual(len(s1_events), 1)
        self.assertEqual(s1_events[0]["session_id"], "s1")

    def test_get_events_limit(self):
        for _ in range(10):
            self.monitor.record_event(self._make_event())
        limited = self.monitor.get_events(limit=3)
        self.assertEqual(len(limited), 3)

    # --- threat summary ---

    def test_empty_summary(self):
        summary = self.monitor.get_threat_summary()
        self.assertEqual(summary["total_events"], 0)
        self.assertEqual(summary["blocked_events"], 0)
        self.assertEqual(summary["block_rate"], 0.0)

    def test_summary_counts(self):
        self.monitor.record_event(self._make_event(blocked=True, risk_score=0.9))
        self.monitor.record_event(self._make_event(blocked=True, risk_score=0.8))
        self.monitor.record_event(self._make_event(blocked=False, action="LOG", risk_score=0.3))
        summary = self.monitor.get_threat_summary()
        self.assertEqual(summary["total_events"], 3)
        self.assertEqual(summary["blocked_events"], 2)
        self.assertAlmostEqual(summary["block_rate"], 2 / 3, places=3)
        self.assertAlmostEqual(summary["average_risk_score"], (0.9 + 0.8 + 0.3) / 3, places=3)
        self.assertEqual(summary["max_risk_score"], 0.9)

    def test_summary_by_category(self):
        self.monitor.record_event(self._make_event(categories=[ThreatCategory.PROMPT_INJECTION]))
        self.monitor.record_event(self._make_event(categories=[ThreatCategory.CREDENTIAL_LEAK]))
        self.monitor.record_event(self._make_event(categories=[ThreatCategory.PROMPT_INJECTION]))
        summary = self.monitor.get_threat_summary()
        self.assertEqual(summary["by_category"]["prompt_injection"], 2)
        self.assertEqual(summary["by_category"]["credential_leak"], 1)

    def test_summary_top_threats(self):
        for _ in range(3):
            self.monitor.record_event(self._make_event(threats=["prompt_injection:ignore"]))
        self.monitor.record_event(self._make_event(threats=["credential:openai_key"]))
        summary = self.monitor.get_threat_summary()
        top = summary["top_threats"]
        self.assertGreater(len(top), 0)
        self.assertEqual(top[0]["threat"], "prompt_injection:ignore")
        self.assertEqual(top[0]["count"], 3)

    def test_summary_sessions_affected(self):
        self.monitor.record_event(self._make_event(session_id="a"))
        self.monitor.record_event(self._make_event(session_id="b"))
        self.monitor.record_event(self._make_event(session_id="a"))
        summary = self.monitor.get_threat_summary()
        self.assertEqual(summary["sessions_affected"], 2)

    def test_summary_by_action(self):
        self.monitor.record_event(self._make_event(action="DENY"))
        self.monitor.record_event(self._make_event(action="DENY"))
        self.monitor.record_event(self._make_event(action="LOG", blocked=False))
        summary = self.monitor.get_threat_summary()
        self.assertEqual(summary["by_action"]["DENY"], 2)
        self.assertEqual(summary["by_action"]["LOG"], 1)

    # --- risk timeline ---

    def test_empty_timeline(self):
        timeline = self.monitor.get_risk_timeline()
        self.assertEqual(timeline, [])

    def test_timeline_has_buckets(self):
        self.monitor.record_event(self._make_event(risk_score=0.8))
        self.monitor.record_event(self._make_event(risk_score=0.6))
        timeline = self.monitor.get_risk_timeline(bucket_minutes=5)
        self.assertIsInstance(timeline, list)
        if timeline:
            bucket = timeline[0]
            self.assertIn("timestamp", bucket)
            self.assertIn("event_count", bucket)
            self.assertIn("average_risk_score", bucket)
            self.assertIn("max_risk_score", bucket)

    # --- persistence ---

    def test_events_persisted_to_file(self):
        self.monitor.record_event(self._make_event())
        self.assertTrue(Path(self.events_file).exists())
        with open(self.events_file) as fh:
            data = json.load(fh)
        self.assertEqual(len(data["events"]), 1)

    def test_reload_from_file(self):
        self.monitor.record_event(self._make_event())
        monitor2 = SecurityMonitor(events_file=self.events_file)
        events = monitor2.get_events()
        self.assertEqual(len(events), 1)

    # --- max_events cap ---

    def test_max_events_cap(self):
        monitor = SecurityMonitor(events_file=self.events_file, max_events=5)
        for _ in range(10):
            monitor.record_event(self._make_event())
        events = monitor.get_events(limit=100)
        self.assertLessEqual(len(events), 5)

    # --- clear ---

    def test_clear(self):
        self.monitor.record_event(self._make_event())
        self.monitor.clear()
        events = self.monitor.get_events()
        self.assertEqual(len(events), 0)


class TestGetMonitorSingleton(unittest.TestCase):
    def test_returns_same_instance(self):
        import ghostchimera.safety_layer.security_monitor as _mod
        old = _mod._monitor_instance
        try:
            _mod._monitor_instance = None
            m1 = get_monitor()
            m2 = get_monitor()
            self.assertIs(m1, m2)
        finally:
            _mod._monitor_instance = old


if __name__ == "__main__":
    unittest.main()
