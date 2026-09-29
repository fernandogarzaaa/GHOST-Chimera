"""Tests for always-on wake triggers (webhooks)."""

from __future__ import annotations

import tempfile
import unittest

from ghostchimera.chimera_pilot.always_on.triggers import WebhookRegistry, render_objective_template


class WebhookRegistryTests(unittest.TestCase):
    def test_register_trigger_unregister(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-triggers-") as tmp:
            registry = WebhookRegistry(tmp)
            registry.register(
                "deploy-finished",
                lambda payload: f"verify deployment {payload.get('version')}",
                description="CI deployment hook",
            )
            objective = registry.trigger("deploy-finished", {"version": "1.2.3"})
            self.assertEqual(objective, "verify deployment 1.2.3")
            self.assertTrue(registry.unregister("deploy-finished"))
            with self.assertRaises(KeyError):
                registry.trigger("deploy-finished", {})

    def test_trigger_unknown_raises(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-triggers-") as tmp, self.assertRaises(KeyError):
            WebhookRegistry(tmp).trigger("nope", {})

    def test_empty_objective_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-triggers-") as tmp:
            registry = WebhookRegistry(tmp)
            registry.register("blank", lambda payload: "   ")
            with self.assertRaises(ValueError):
                registry.trigger("blank", {})

    def test_empty_name_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-triggers-") as tmp, self.assertRaises(ValueError):
            WebhookRegistry(tmp).register("   ", lambda payload: "x")

    def test_definitions_persist_across_instances(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-triggers-") as tmp:
            WebhookRegistry(tmp).register("nightly", lambda payload: "run nightly check", description="cron hook")
            names = [d.name for d in WebhookRegistry(tmp).list()]
            self.assertEqual(names, ["nightly"])

    def test_names_normalize(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-triggers-") as tmp:
            registry = WebhookRegistry(tmp)
            registry.register("Deploy Finished", lambda payload: "go")
            self.assertTrue(registry.has_handler("deploy-finished"))
            self.assertEqual(registry.trigger("DEPLOY-FINISHED", {}), "go")

    def test_template_webhook_renders_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-triggers-") as tmp:
            registry = WebhookRegistry(tmp)
            registry.register_template(
                "ci-done",
                "verify build {build} on {branch}",
                description="CI hook",
            )
            self.assertEqual(
                registry.trigger("ci-done", {"build": "42", "branch": "main"}),
                "verify build 42 on main",
            )

    def test_template_webhook_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-triggers-") as tmp:
            WebhookRegistry(tmp).register_template("ci-done", "verify build {build}")
            reloaded = WebhookRegistry(tmp)
            self.assertTrue(reloaded.has_handler("ci-done"))
            self.assertEqual(reloaded.trigger("ci-done", {"build": "7"}), "verify build 7")

    def test_template_leaves_unknown_placeholders(self) -> None:
        self.assertEqual(
            render_objective_template("check {thing}", {}),
            "check {thing}",
        )

    def test_empty_template_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-triggers-") as tmp, self.assertRaises(ValueError):
            WebhookRegistry(tmp).register_template("blank", "   ")


if __name__ == "__main__":
    unittest.main()
