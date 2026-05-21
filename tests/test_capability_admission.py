from __future__ import annotations

import json
import tempfile
import unittest

from ghostchimera.capability_admission import CapabilityAdmissionStore


class CapabilityAdmissionStoreTests(unittest.TestCase):
    def test_create_inspect_approve_activate_and_list(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-admission-") as tmp:
            store = CapabilityAdmissionStore(tmp)
            created = store.create_record(
                capability_kind="model",
                name="openrouter/test-model",
                source="openrouter",
                risk_level="medium",
                requested_permissions=["model.chat"],
                metadata={"api_key": "sk-testsecret123456"},
            )
            inspected = store.transition(created["record"]["id"], "inspected", reviewer="tester")
            approved = store.transition(created["record"]["id"], "approved", reviewer="tester")
            active = store.transition(created["record"]["id"], "active", reviewer="tester")
            records = store.list_records()

            self.assertTrue(created["ok"])
            self.assertEqual(inspected["record"]["status"], "inspected")
            self.assertEqual(approved["record"]["status"], "approved")
            self.assertEqual(active["record"]["status"], "active")
            self.assertEqual(records["count"], 1)
            self.assertNotIn("sk-testsecret123456", json.dumps(records))

    def test_invalid_transition_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-admission-invalid-") as tmp:
            store = CapabilityAdmissionStore(tmp)
            created = store.create_record(capability_kind="mcp", name="external", risk_level="high")
            invalid = store.transition(created["record"]["id"], "active", reviewer="tester")

            self.assertFalse(invalid["ok"])
            self.assertEqual(store.get_record(created["record"]["id"])["record"]["status"], "discovered")

    def test_revoke_and_quarantine_active_record(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-admission-revoke-") as tmp:
            store = CapabilityAdmissionStore(tmp)
            created = store.create_record(capability_kind="skill", name="repo-skill", risk_level="low")
            record_id = created["record"]["id"]
            store.transition(record_id, "inspected")
            store.transition(record_id, "approved")
            store.transition(record_id, "active")
            quarantined = store.transition(record_id, "quarantined", reason="unexpected file writes")
            revoked = store.transition(record_id, "revoked", reason="operator revoked")

            self.assertEqual(quarantined["record"]["status"], "quarantined")
            self.assertEqual(revoked["record"]["status"], "revoked")

    def test_summary_flags_high_risk_unreviewed_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-admission-summary-") as tmp:
            store = CapabilityAdmissionStore(tmp)
            store.create_record(capability_kind="mcp", name="unknown-mcp", risk_level="high")
            store.create_record(capability_kind="model", name="safe-model", risk_level="low")

            summary = store.summary()
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["counts"]["total"], 2)
            self.assertEqual(summary["counts"]["unreviewed_high_risk"], 1)
            self.assertFalse(summary["production_ready"])
            self.assertTrue(summary["warnings"])

    def test_register_or_update_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-admission-upsert-") as tmp:
            store = CapabilityAdmissionStore(tmp)
            first = store.register_or_update(
                capability_kind="connector",
                name="github",
                source="console",
                risk_level="medium",
                requested_permissions=["repo.read"],
            )
            second = store.register_or_update(
                capability_kind="connector",
                name="github",
                source="console",
                risk_level="high",
                requested_permissions=["repo.read", "repo.write"],
            )

            self.assertEqual(first["record"]["id"], second["record"]["id"])
            self.assertEqual(second["record"]["risk_level"], "high")
            self.assertEqual(store.list_records()["count"], 1)


if __name__ == "__main__":
    unittest.main()
