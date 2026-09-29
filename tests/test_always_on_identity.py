"""Tests for always-on agent identity persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.always_on.identity import AgentIdentity, IdentityStore


class IdentityStoreTests(unittest.TestCase):
    def test_create_assigns_stable_id_and_persists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-identity-") as tmp:
            store = IdentityStore(tmp)
            identity = store.create("night-watch", metadata={"role": "monitor"})
            self.assertTrue(identity.agent_id.startswith("ghost-"))
            self.assertEqual(identity.name, "night-watch")
            self.assertEqual(identity.lifecycle_state, "sleeping")
            self.assertTrue((Path(tmp) / "always_on" / "identities" / f"{identity.agent_id}.json").exists())

    def test_identity_survives_store_recreation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-identity-") as tmp:
            first = IdentityStore(tmp).create("resilient")
            second = IdentityStore(tmp)
            reloaded = second.get(first.agent_id)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertEqual(reloaded.agent_id, first.agent_id)
            self.assertEqual(reloaded.name, "resilient")

    def test_get_unknown_returns_none(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-identity-") as tmp:
            self.assertIsNone(IdentityStore(tmp).get("ghost-does-not-exist"))

    def test_list_returns_all_identities(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-identity-") as tmp:
            store = IdentityStore(tmp)
            store.create("alpha")
            store.create("beta")
            names = [i.name for i in store.list()]
            # Order between same-tick creations is by agent id; the set is what matters.
            self.assertEqual(sorted(names), ["alpha", "beta"])

    def test_touch_updates_last_seen_and_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-identity-") as tmp:
            store = IdentityStore(tmp)
            identity = store.create("watcher")
            updated = store.touch(identity.agent_id, lifecycle_state="awake")
            assert updated is not None
            self.assertEqual(updated.lifecycle_state, "awake")
            self.assertGreaterEqual(updated.last_seen, identity.last_seen)
            # persisted too
            self.assertEqual(IdentityStore(tmp).get(identity.agent_id).lifecycle_state, "awake")  # type: ignore[union-attr]

    def test_touch_unknown_returns_none(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-identity-") as tmp:
            self.assertIsNone(IdentityStore(tmp).touch("ghost-nope", lifecycle_state="awake"))

    def test_get_or_create_primary_is_stable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-identity-") as tmp:
            store = IdentityStore(tmp)
            first = store.get_or_create_primary()
            second = store.get_or_create_primary()
            self.assertEqual(first.agent_id, second.agent_id)

    def test_identity_round_trip(self) -> None:
        identity = AgentIdentity(
            agent_id="ghost-abc123",
            name="rtt",
            created_at=1.0,
            last_seen=2.0,
            lifecycle_state="queued",
            metadata={"k": "v"},
        )
        restored = AgentIdentity.from_dict(identity.to_dict())
        self.assertEqual(restored, identity)


if __name__ == "__main__":
    unittest.main()
