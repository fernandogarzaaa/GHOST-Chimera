"""Tests for Ghost Console latency telemetry."""

from __future__ import annotations

import tempfile
import unittest

from ghostchimera.control_plane.latency import latency_summary, read_latency_events, record_latency_event


class LatencyTelemetryTests(unittest.TestCase):
    def test_latency_summary_reports_p95_and_over_budget_routes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-latency-") as tmp:
            record_latency_event(tmp, route="/api/console/status", method="GET", duration_ms=25, ok=True)
            record_latency_event(tmp, route="/api/console/status", method="GET", duration_ms=300, ok=True)
            record_latency_event(tmp, route="/api/console/run", method="POST", duration_ms=3200, ok=False, error="Timeout")

            summary = latency_summary(tmp)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["event_count"], 3)
        self.assertEqual(summary["over_budget_count"], 2)
        self.assertEqual(summary["error_count"], 1)
        self.assertGreaterEqual(summary["p95_ms"], 300)
        self.assertIn(summary["status"], {"watch", "slow"})
        self.assertTrue(summary["routes"])
        self.assertTrue(summary["recommendations"])

    def test_latency_store_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-latency-") as tmp:
            for index in range(550):
                record_latency_event(tmp, route=f"/api/console/test/{index}", method="GET", duration_ms=index, ok=True)

            events = read_latency_events(tmp, limit=600)

        self.assertEqual(len(events), 500)
        self.assertEqual(events[0]["route"], "/api/console/test/50")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
