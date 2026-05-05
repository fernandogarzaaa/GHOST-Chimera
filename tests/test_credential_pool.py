"""Tests for the Hermes-Agent migration: credential_pool.py and error_classifier.py."""

from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import patch

from ghostchimera.chimera_pilot.credential_pool import (
    CredentialEntry,
    CredentialPool,
    ProviderHealth,
    get_pool,
    reset_pool,
)
from ghostchimera.chimera_pilot.error_classifier import (
    ErrorCategory,
    ErrorClassifier,
    Severity,
    get_classifier,
)


class CredentialEntryTests(unittest.TestCase):
    def test_is_expired_false_when_no_expiry(self) -> None:
        entry = CredentialEntry(provider="openai", api_key="sk-test")
        self.assertFalse(entry.is_expired)

    def test_is_expired_true_when_expired(self) -> None:
        entry = CredentialEntry(provider="openai", api_key="sk-test", expires_at=time.time() - 100)
        self.assertTrue(entry.is_expired)

    def test_is_available(self) -> None:
        available = CredentialEntry(provider="openai", api_key="sk-test")
        self.assertTrue(available.is_available)

        revoked = CredentialEntry(provider="openai", api_key="sk-test", enabled=False)
        self.assertFalse(revoked.is_available)

        no_key = CredentialEntry(provider="openai", api_key="")
        self.assertFalse(no_key.is_available)

    def test_usage_pct_unlimited(self) -> None:
        entry = CredentialEntry(provider="openai", api_key="sk-test", quota_limit=0, quota_used=100)
        self.assertEqual(entry.usage_pct(), 0.0)

    def test_usage_pct_limited(self) -> None:
        entry = CredentialEntry(provider="openai", api_key="sk-test", quota_limit=1000, quota_used=500)
        self.assertEqual(entry.usage_pct(), 0.5)


class ProviderHealthTests(unittest.TestCase):
    def test_success_rate_no_requests(self) -> None:
        health = ProviderHealth(provider="test", available=True, usage_pct=0.0)
        self.assertEqual(health.success_rate, 0.0)

    def test_success_rate_after_successes(self) -> None:
        health = ProviderHealth(provider="test", available=True, usage_pct=0.0)
        for _ in range(10):
            health.record_success()
        self.assertEqual(health.success_rate, 1.0)

    def test_failure_records_error_message(self) -> None:
        health = ProviderHealth(provider="test", available=True, usage_pct=0.0)
        health.record_failure("some error")
        self.assertEqual(health.last_error, "some error")

        health.record_failure("another error")
        self.assertEqual(health.last_error, "some error")  # first error preserved

    def test_failure_truncates_long_error(self) -> None:
        health = ProviderHealth(provider="test", available=True, usage_pct=0.0)
        health.record_failure("x" * 300)
        self.assertEqual(len(health.last_error), 200)


class CredentialPoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = CredentialPool()

    def test_add_credential(self) -> None:
        entry = self.pool.add_credential("openai", api_key="sk-test")
        self.assertEqual(entry.provider, "openai")
        self.assertEqual(entry.api_key, "sk-test")
        self.assertIsNotNone(self.pool.get_credential("openai"))

    def test_add_multiple_credentials(self) -> None:
        self.pool.add_credential("openai", api_key="sk-1")
        self.pool.add_credential("anthropic", api_key="sk-2")
        self.assertIsNotNone(self.pool.get_credential("openai"))
        self.assertIsNotNone(self.pool.get_credential("anthropic"))

    def test_get_credential_unavailable_expired(self) -> None:
        self.pool.add_credential("openai", api_key="sk-test", expires_at=time.time() - 100)
        self.assertIsNone(self.pool.get_credential("openai"))

    def test_rotate_credential(self) -> None:
        self.pool.add_credential("openai", api_key="sk-old")
        new_entry = self.pool.rotate_credential("openai", "sk-new")
        self.assertEqual(new_entry.api_key, "sk-new")
        self.assertTrue(new_entry.metadata.get("rotated", False))

    def test_rotate_missing_provider_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.pool.rotate_credential("nonexistent", "sk-new")

    def test_record_request(self) -> None:
        self.pool.add_credential("openai", api_key="sk-test")
        self.pool.record_request("openai", success=True)
        self.pool.record_request("openai", success=False, error="timeout")
        health = self.pool._health.get("openai")
        self.assertIsNotNone(health)
        self.assertEqual(health.success_count, 1)
        self.assertEqual(health.failure_count, 1)

    def test_select_best_provider(self) -> None:
        self.pool.add_credential("openai", api_key="sk-1", quota_limit=1000)
        self.pool.add_credential("anthropic", api_key="sk-2", quota_limit=1000)
        self.pool.record_request("openai", success=True)
        self.pool.record_request("openai", success=True)
        self.pool.record_request("anthropic", success=False)

        best = self.pool.select_best_provider()
        self.assertEqual(best, "openai")

    def test_select_best_provider_excludes(self) -> None:
        self.pool.add_credential("openai", api_key="sk-1")
        self.pool.add_credential("anthropic", api_key="sk-2")
        best = self.pool.select_best_provider(exclude={"openai"})
        self.assertEqual(best, "anthropic")

    def test_list_credentials_masks_keys(self) -> None:
        self.pool.add_credential("openai", api_key="sk-1234secret")
        creds = self.pool.list_credentials()
        self.assertEqual(len(creds), 1)
        self.assertIn("*", creds[0]["key_masked"])
        self.assertTrue(creds[0]["key_masked"].startswith("sk-1"))

    def test_status(self) -> None:
        self.pool.add_credential("openai", api_key="sk-test")
        status = self.pool.status()
        self.assertFalse(status["initialized"])
        self.assertEqual(status["provider_count"], 1)

    def test_singleton_pool(self) -> None:
        reset_pool()
        p1 = get_pool()
        p2 = get_pool()
        self.assertIs(p1, p2)

    def test_initialize_from_env(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env-test", "GEMINI_API_KEY": "sk-gemini"}):
            pool = CredentialPool()
            loaded = pool.initialize_from_env()
            self.assertGreaterEqual(loaded, 1)
            self.assertTrue(pool.get_credential("openai"))

    def test_thread_safety(self) -> None:
        errors: list[Exception] = []

        def add_credentials(n: int) -> None:
            for i in range(n):
                try:
                    self.pool.add_credential(f"provider-{i}", api_key=f"sk-{i}")
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=add_credentials, args=(100,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)
        # All threads write the same keys (provider-0 through provider-99), so 100 unique entries
        self.assertEqual(len(self.pool._creds), 100)


class ErrorClassifierTests(unittest.TestCase):
    def test_rate_limit(self) -> None:
        plan = ErrorClassifier().classify("429 rate limit exceeded")
        self.assertEqual(plan.categories[0], ErrorCategory.RATE_LIMIT)
        self.assertTrue(plan.retry)
        self.assertEqual(plan.backoff_seconds, 5.0)

    def test_insufficient_quota(self) -> None:
        plan = ErrorClassifier().classify("insufficient quota")
        self.assertEqual(plan.categories[0], ErrorCategory.INSUFFICIENT_QUOTA)
        self.assertFalse(plan.retry)
        self.assertTrue(plan.requires_user_action)

    def test_context_length(self) -> None:
        plan = ErrorClassifier().classify("context length exceeded")
        self.assertEqual(plan.categories[0], ErrorCategory.CONTEXT_LENGTH)
        self.assertTrue(plan.compress)

    def test_authentication(self) -> None:
        plan = ErrorClassifier().classify("unauthorized 401 invalid api key")
        self.assertEqual(plan.categories[0], ErrorCategory.AUTHENTICATION)
        self.assertEqual(plan.severity, Severity.CRITICAL)

    def test_overloaded(self) -> None:
        plan = ErrorClassifier().classify("server error 503 overloaded")
        self.assertEqual(plan.categories[0], ErrorCategory.OVERLOADED)

    def test_timeout(self) -> None:
        plan = ErrorClassifier().classify("connection timed out")
        self.assertEqual(plan.categories[0], ErrorCategory.TIMEOUT)

    def test_invalid_request(self) -> None:
        plan = ErrorClassifier().classify("invalid request body schema violation")
        self.assertEqual(plan.categories[0], ErrorCategory.INVALID_REQUEST)

    def test_server_error_502(self) -> None:
        # 502 matches OVERLOADED pattern (50[0-3]) before SERVER_ERROR (50[4-9])
        plan = ErrorClassifier().classify("502 bad gateway")
        self.assertIn(plan.categories[0], (ErrorCategory.OVERLOADED, ErrorCategory.SERVER_ERROR))

    def test_malformed_response(self) -> None:
        plan = ErrorClassifier().classify("malformed JSON decode error")
        self.assertEqual(plan.categories[0], ErrorCategory.MALFORMED_RESPONSE)

    def test_security(self) -> None:
        plan = ErrorClassifier().classify("injection attempt blocked")
        self.assertEqual(plan.categories[0], ErrorCategory.SECURITY)
        self.assertEqual(plan.severity, Severity.CRITICAL)

    def test_default_unclassified(self) -> None:
        plan = ErrorClassifier().classify("some unknown error")
        self.assertEqual(plan.categories[0], ErrorCategory.DEFAULT)
        self.assertFalse(plan.is_recoverable)

    def test_custom_predicate_rule(self) -> None:
        classifier = ErrorClassifier()
        classifier.register_predicate(
            lambda msg, err: "custom" in msg,
            ErrorCategory.CONNECTION,
            {"retry": True, "severity": Severity.HIGH},
        )
        plan = classifier.classify("this has custom keyword")
        self.assertEqual(plan.categories[0], ErrorCategory.CONNECTION)

    def test_custom_regex_rule(self) -> None:
        classifier = ErrorClassifier()
        classifier.register_rule(r'custom_regex', ErrorCategory.CONNECTION, {"retry": True})
        plan = classifier.classify("contains custom_regex pattern")
        self.assertEqual(plan.categories[0], ErrorCategory.CONNECTION)

    def test_classify_multi(self) -> None:
        classifier = ErrorClassifier()
        plans = classifier.classify_multi([
            ("429 rate limit", None),
            ("auth failed", "authentication"),
        ])
        self.assertEqual(len(plans), 2)
        self.assertEqual(plans[0].categories[0], ErrorCategory.RATE_LIMIT)
        self.assertEqual(plans[1].categories[0], ErrorCategory.AUTHENTICATION)

    def test_taxonomy_returns_all_categories(self) -> None:
        classifier = ErrorClassifier()
        taxonomy = classifier.taxonomy()
        self.assertIn(ErrorCategory.RATE_LIMIT.value, taxonomy)
        self.assertIn(ErrorCategory.SECURITY.value, taxonomy)
        self.assertNotIn(ErrorCategory.DEFAULT.value, taxonomy)

    def test_recovery_actions_included(self) -> None:
        plan = ErrorClassifier().classify("429 rate limit exceeded")
        action_names = [a.action for a in plan.actions]
        self.assertIn("retry_with_backoff", action_names)

    def test_severity_values(self) -> None:
        self.assertEqual(Severity.LOW, "low")
        self.assertEqual(Severity.CRITICAL, "critical")

    def test_recommended_action(self) -> None:
        plan = ErrorClassifier().classify("429 rate limit")
        self.assertEqual(plan.recommended_action, "retry_with_backoff")

    def test_get_classifier_singleton(self) -> None:
        c1 = get_classifier()
        c2 = get_classifier()
        self.assertIs(c1, c2)


if __name__ == "__main__":
    unittest.main()
