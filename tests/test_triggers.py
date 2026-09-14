"""Tests for the declarative Trigger Engine."""

from __future__ import annotations

import unittest

from ghostchimera.stealth.events import new_event
from ghostchimera.stealth.stealth_policy import AutonomyLevel
from ghostchimera.stealth.triggers import Trigger, TriggerCondition, TriggerEngine, define_trigger


def _event(event_type: str = "email.received", timestamp: float = 1000.0, **kwargs) -> object:
    payload = kwargs.pop("payload", {"subject": "invoice overdue", "amount": 42})
    return new_event(event_type, source="gmail", payload=payload, timestamp=timestamp, **kwargs)


class ConditionTests(unittest.TestCase):
    def test_ops_matrix(self) -> None:
        event = _event()

        self.assertTrue(TriggerCondition("payload.subject", "contains", "invoice").matches(event))
        self.assertTrue(TriggerCondition("payload.amount", "gt", 40).matches(event))
        self.assertTrue(TriggerCondition("payload.amount", "lte", 42).matches(event))
        self.assertTrue(TriggerCondition("source", "eq", "gmail").matches(event))
        self.assertTrue(TriggerCondition("payload.amount", "in", [1, 42]).matches(event))
        self.assertTrue(TriggerCondition("payload.missing", "ne", "x").matches(event))
        self.assertFalse(TriggerCondition("payload.missing", "eq", "x").matches(event))
        self.assertFalse(TriggerCondition("payload.missing", "exists").matches(event))
        self.assertTrue(TriggerCondition("payload.subject", "exists").matches(event))
        self.assertFalse(TriggerCondition("payload.amount", "gt", "nan-compare").matches(event))

    def test_unknown_op_rejected_on_load(self) -> None:
        condition = TriggerCondition.from_dict({"field": "source", "op": "frob", "value": "gmail"})

        self.assertEqual(condition.op, "eq")
        self.assertTrue(condition.matches(_event()))


class MatchingTests(unittest.TestCase):
    def test_event_type_forms(self) -> None:
        event = _event("email.received")

        self.assertTrue(Trigger("a", event_type="email.received").matches_event(event))
        self.assertTrue(Trigger("b", event_type="email.*").matches_event(event))
        self.assertTrue(Trigger("c", event_type="*").matches_event(event))
        self.assertFalse(Trigger("d", event_type="calendar.*").matches_event(event))

    def test_autonomy_gate(self) -> None:
        trigger = Trigger("gated", event_type="*", min_autonomy=AutonomyLevel.INJECT)
        event = _event()

        self.assertFalse(trigger.should_fire(event, AutonomyLevel.OBSERVE))
        self.assertTrue(trigger.should_fire(event, AutonomyLevel.INJECT))

    def test_cooldown_uses_event_time(self) -> None:
        engine = TriggerEngine()
        engine.register(Trigger("slow", event_type="*", cooldown_s=60.0, action={"kind": "note"}))

        self.assertEqual(len(engine.evaluate(_event(timestamp=1000.0))), 1)
        self.assertEqual(engine.evaluate(_event(timestamp=1005.0)), [])
        self.assertEqual(len(engine.evaluate(_event(timestamp=1061.0))), 1)

    def test_disabled_trigger_never_fires(self) -> None:
        engine = TriggerEngine()
        engine.register(Trigger("off", event_type="*", enabled=False))

        self.assertEqual(engine.evaluate(_event()), [])
        self.assertTrue(engine.enable("off"))
        self.assertEqual(len(engine.evaluate(_event())), 1)
        self.assertTrue(engine.disable("off"))
        self.assertEqual(engine.evaluate(_event()), [])


class EngineTests(unittest.TestCase):
    def test_define_from_dict_and_hit_shape(self) -> None:
        engine = TriggerEngine()
        trigger = engine.define(
            {
                "trigger": {
                    "name": "invoice-watch",
                    "when": {"event": "email.*", "autonomy": "prepare", "cooldown_s": 10},
                    "conditions": [{"field": "payload.subject", "op": "contains", "value": "invoice"}],
                    "action": {"kind": "suggest", "workflow": "pay-invoice"},
                }
            }
        )

        self.assertEqual(trigger.min_autonomy, AutonomyLevel.PREPARE)
        hits = engine.evaluate(_event(timestamp=2000.0), AutonomyLevel.PREPARE)

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].trigger_name, "invoice-watch")
        self.assertEqual(hits[0].action["workflow"], "pay-invoice")
        self.assertEqual(engine.recent_hits()[0].event_id, hits[0].event_id)
        self.assertEqual(engine.evaluate(_event("calendar.event_created", timestamp=2001.0)), [])

    def test_unknown_autonomy_falls_back_to_observe(self) -> None:
        trigger = define_trigger({"name": "x", "min_autonomy": "frob"})

        self.assertEqual(trigger.min_autonomy, AutonomyLevel.OBSERVE)

    def test_round_trip_preserves_rules(self) -> None:
        engine = TriggerEngine()
        engine.define(
            {
                "name": "t1",
                "event_type": "file.*",
                "conditions": [{"field": "actor", "op": "eq", "value": "alex"}],
                "min_autonomy": "observe",
                "cooldown_s": 5,
                "action": {"kind": "note"},
            }
        )
        restored = TriggerEngine.from_dict(engine.to_dict())

        self.assertEqual(len(restored), 1)
        self.assertEqual(restored.get("t1").conditions[0].field, "actor")
        self.assertEqual(len(restored.evaluate(_event("file.modified", actor="alex"))), 1)
        self.assertEqual(restored.evaluate(_event("file.modified", actor="sam")), [])

    def test_unregister(self) -> None:
        engine = TriggerEngine()
        engine.register(Trigger("tmp", event_type="*"))

        self.assertTrue(engine.unregister("tmp"))
        self.assertFalse(engine.unregister("tmp"))
        self.assertEqual(len(engine), 0)


class LoopIntegrationTests(unittest.TestCase):
    def test_loop_records_hits_without_changing_decisions(self) -> None:
        from ghostchimera.stealth import StealthLoop

        loop = StealthLoop()
        plain = StealthLoop()
        try:
            loop.triggers.define(
                {
                    "name": "invoice-watch",
                    "event_type": "email.received",
                    "conditions": [{"field": "payload.subject", "op": "contains", "value": "invoice"}],
                    "action": {"kind": "suggest", "workflow": "pay-invoice"},
                }
            )
            event = _event(timestamp=3000.0)
            loop.emit(event)
            plain.emit(_event(timestamp=3000.0))

            self.assertEqual(loop.last_result.decision, plain.last_result.decision)
            self.assertEqual(len(loop.recent_trigger_hits()), 1)
            self.assertEqual(loop.recent_trigger_hits()[0].trigger_name, "invoice-watch")

            weak = new_event("file.modified", source="watcher", confidence=0.2, timestamp=3001.0)
            loop.emit(weak)

            self.assertEqual(loop.last_result.decision, "none")
            self.assertEqual(len(loop.recent_trigger_hits()), 1)
        finally:
            loop.close()
            plain.close()


if __name__ == "__main__":
    unittest.main()
