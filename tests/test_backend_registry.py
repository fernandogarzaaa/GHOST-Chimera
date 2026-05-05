"""Tests for the self-registering backend registry."""

from __future__ import annotations

import unittest

from ghostchimera.chimera_pilot.backends.deterministic import DeterministicBackend
from ghostchimera.chimera_pilot.backend_registry import (
    BackendRegistry,
    default,
    discover_builtin_backends,
)


class TestBackendRegistry(unittest.TestCase):
    def test_singleton(self):
        r1 = BackendRegistry()
        r2 = BackendRegistry()
        self.assertIs(r1, r2)
        self.assertIs(r1, default)

    def test_get_registered_ids_sorted(self):
        # Reset singleton for clean state
        default._backends.clear()
        default._check_fns.clear()
        default._generation += 1
        ids = default.get_registered_ids()
        self.assertEqual(ids, sorted(ids))

    def test_get_all_classes_returns_types(self):
        classes = default.get_all_classes()
        for c in classes:
            self.assertIsInstance(c, type)

    def test_register_and_deregister(self):
        backend = DeterministicBackend()
        registry = BackendRegistry()
        registry.register(DeterministicBackend)
        self.assertIn("DeterministicBackend", registry.get_registered_ids())
        registry.deregister("DeterministicBackend")
        self.assertNotIn("DeterministicBackend", registry.get_registered_ids())

    def test_is_available_no_check_fn(self):
        registry = BackendRegistry()
        registry.register(DeterministicBackend)
        # No check_fn means always available
        self.assertTrue(registry.is_available("DeterministicBackend"))

    def test_get_registered_ids_includes_builtin(self):
        discover_builtin_backends()
        ids = default.get_registered_ids()
        self.assertIn("DeterministicBackend", ids)


class TestDiscoverBuiltinBackends(unittest.TestCase):
    def test_discovery_returns_list(self):
        modules = discover_builtin_backends()
        self.assertIsInstance(modules, list)

    def test_discovery_includes_deterministic(self):
        modules = discover_builtin_backends()
        module_names = [m.split(".")[-1] for m in modules]
        self.assertIn("deterministic", module_names)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
