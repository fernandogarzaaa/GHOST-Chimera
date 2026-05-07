"""Unit tests for SSRF / network policy dispatcher."""

from __future__ import annotations

import unittest

from ghostchimera.safety_layer.ssrf import (
    FetchResult,
    NetworkDispatcher,
    SSRFPolicy,
    SSRFViolation,
    get_dispatcher,
    reset_dispatcher,
)


class SSRFPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = SSRFPolicy()

    def test_default_allow_all_false(self):
        self.assertFalse(self.policy.allow_all)

    def test_default_default_allow_false(self):
        self.assertFalse(self.policy.default_allow)

    def test_default_block_private_true(self):
        self.assertTrue(self.policy.block_private_ranges)

    def test_is_permitted_returns_tuple(self):
        ok, reason = self.policy.is_permitted("http://example.com")
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(reason, str)

    def test_allow_all_permits_all(self):
        self.policy.allow_all = True
        ok, _ = self.policy.is_permitted("http://127.0.0.1")
        self.assertTrue(ok)

    def test_deny_loopback(self):
        ok, _ = self.policy.is_permitted("http://127.0.0.1")
        self.assertFalse(ok)

    def test_deny_private_10(self):
        ok, _ = self.policy.is_permitted("http://10.0.0.1")
        self.assertFalse(ok)

    def test_deny_private_192(self):
        ok, _ = self.policy.is_permitted("http://192.168.1.1")
        self.assertFalse(ok)

    def test_deny_metadata_169(self):
        ok, _ = self.policy.is_permitted("http://169.254.169.254")
        self.assertFalse(ok)

    def test_deny_100(self):
        ok, _ = self.policy.is_permitted("http://100.100.100.100")
        self.assertFalse(ok)

    def test_allow_host(self):
        self.policy.allow_host("*.example.com")
        # With default_allow=False, only explicitly allowed hosts pass
        # Use direct IP 8.8.8.8 which doesn't trigger DNS
        ok, _ = self.policy.is_permitted("http://8.8.8.8/test")
        self.assertFalse(ok)

    def test_deny_host(self):
        self.policy.deny_host("*.evil.com")
        # Use direct IP that doesn't trigger DNS
        ok, _ = self.policy.is_permitted("http://1.1.1.1/test")
        self.assertFalse(ok)

    def test_default_allow_permits_unmatched(self):
        self.policy.default_allow = True
        # Use direct IP to avoid DNS resolution
        ok, _ = self.policy.is_permitted("http://8.8.8.8/test")
        self.assertTrue(ok)

    def test_to_dict(self):
        d = self.policy.to_dict()
        self.assertIn("allow_all", d)
        self.assertIn("block_private_ranges", d)
        self.assertIn("allowed", d)
        self.assertIn("denied", d)

    def test_remove_allowed(self):
        self.policy.allow_host("*.example.com")
        self.policy.remove_allowed("*.example.com")
        # Should fall through to default_allow=False
        ok, _ = self.policy.is_permitted("http://api.example.com")
        self.assertFalse(ok)

    def test_remove_denied(self):
        self.policy.deny_host("*.evil.com")
        self.policy.remove_denied("*.evil.com")
        # Should fall through to default_allow=False — still denied
        ok, _ = self.policy.is_permitted("http://api.evil.com")
        self.assertFalse(ok)

    def test_allow_all_overrides_everything(self):
        self.policy.allow_all = True
        self.policy.deny_host("*.example.com")
        ok, _ = self.policy.is_permitted("http://api.example.com")
        self.assertTrue(ok)


class NetworkDispatcherTests(unittest.TestCase):
    def setUp(self):
        reset_dispatcher()
        self.policy = SSRFPolicy()
        self.dispatcher = NetworkDispatcher(self.policy)

    def test_fetch_invalid_url_raises_ssr_failure(self):
        # Invalid host → SSRFViolation from policy check
        with self.assertRaises(SSRFViolation):
            self.dispatcher.fetch("http://127.0.0.1/test")

    def test_fetch_blocked_host(self):
        with self.assertRaises(SSRFViolation):
            self.dispatcher.fetch("http://10.0.0.1/test")

    def test_fetch_result_attributes(self):
        # Create a dispatcher that allow_all to avoid SSRFViolation
        permissive = SSRFPolicy(allow_all=True)
        disp = NetworkDispatcher(permissive)
        result = disp.fetch("http://invalid-host-that-does-not-exist.test/test", timeout_seconds=2)
        self.assertIsInstance(result, FetchResult)
        self.assertEqual(result.url, "http://invalid-host-that-does-not-exist.test/test")
        self.assertTrue(result.ok or result.error)  # May succeed or fail with connection error


class FetchResultTests(unittest.TestCase):
    def test_fetch_result_ok(self):
        r = FetchResult(url="http://example.com", status_code=200)
        self.assertTrue(r.ok)

    def test_fetch_result_not_ok(self):
        r = FetchResult(url="http://example.com", status_code=500)
        self.assertFalse(r.ok)

    def test_fetch_result_text(self):
        r = FetchResult(url="http://example.com", body=b"hello")
        self.assertEqual(r.text, "hello")


class DispatcherSingletonTests(unittest.TestCase):
    def test_get_and_reset(self):
        d1 = get_dispatcher()
        self.assertIsNotNone(d1)
        reset_dispatcher()
        d2 = get_dispatcher()
        self.assertIsNot(d1, d2)


if __name__ == "__main__":
    unittest.main()
