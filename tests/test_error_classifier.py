"""Unit tests for error classifier."""

import unittest

from ghostchimera.chimera_pilot.error_classifier import (
    AutoRecoveryPlan,
    ErrorCategory,
    ErrorClassifier,
    RecoveryAction,
    Severity,
    get_classifier,
)


class ErrorClassifierTests(unittest.TestCase):
    def setUp(self):
        self.classifier = ErrorClassifier()

    def test_rate_limit_classification(self):
        plan = self.classifier.classify("429 Too Many Requests", "api_error")
        self.assertIsInstance(plan, AutoRecoveryPlan)
        self.assertEqual(plan.categories[0], ErrorCategory.RATE_LIMIT)
        self.assertTrue(plan.retry)
        self.assertEqual(plan.recommended_action, "retry_with_backoff")

    def test_rate_limit_variation(self):
        plan = self.classifier.classify("rate limit exceeded", None)
        self.assertEqual(plan.categories[0], ErrorCategory.RATE_LIMIT)

    def test_rate_limit_another_variation(self):
        plan = self.classifier.classify("too many requests", None)
        self.assertEqual(plan.categories[0], ErrorCategory.RATE_LIMIT)

    def test_context_length_classification(self):
        plan = self.classifier.classify("context length exceeded", None)
        self.assertEqual(plan.categories[0], ErrorCategory.CONTEXT_LENGTH)
        self.assertTrue(plan.compress)

    def test_authentication_error(self):
        plan = self.classifier.classify("unauthorized: invalid API key", None)
        self.assertEqual(plan.categories[0], ErrorCategory.AUTHENTICATION)

    def test_timeout_error(self):
        plan = self.classifier.classify("connection timed out", None)
        self.assertEqual(plan.categories[0], ErrorCategory.TIMEOUT)
        self.assertTrue(plan.retry)

    def test_server_error_503(self):
        plan = self.classifier.classify("503 Service Unavailable", None)
        self.assertEqual(plan.categories[0], ErrorCategory.OVERLOADED)
        self.assertTrue(plan.retry)

    def test_invalid_request(self):
        plan = self.classifier.classify("invalid request body", None)
        self.assertEqual(plan.categories[0], ErrorCategory.INVALID_REQUEST)

    def test_connection_error(self):
        plan = self.classifier.classify("ECONNREFUSED", None)
        self.assertEqual(plan.categories[0], ErrorCategory.CONNECTION)
        self.assertTrue(plan.retry)

    def test_security_error(self):
        plan = self.classifier.classify("sandbox forbidden", None)
        self.assertEqual(plan.categories[0], ErrorCategory.SECURITY)
        self.assertTrue(plan.requires_user_action)

    def test_unclassified_error(self):
        plan = self.classifier.classify("some unknown error", None)
        self.assertEqual(plan.categories[0], ErrorCategory.DEFAULT)
        self.assertFalse(plan.is_recoverable)

    def test_custom_predicate(self):
        self.classifier.register_predicate(
            lambda msg, _: "custom" in msg.lower(),
            ErrorCategory.CONNECTION,
            {"retry": True, "severity": Severity.LOW},
        )
        plan = self.classifier.classify("this is a custom error", None)
        self.assertEqual(plan.categories[0], ErrorCategory.CONNECTION)

    def test_taxonomy_contains_all_categories(self):
        taxonomy = self.classifier.taxonomy()
        self.assertIn("rate_limit", taxonomy)
        self.assertIn("connection", taxonomy)
        self.assertIn("security", taxonomy)

    def test_severity_levels(self):
        plan_rl = self.classifier.classify("429 Too Many Requests", None)
        self.assertEqual(plan_rl.severity, Severity.MEDIUM)
        plan_auth = self.classifier.classify("authentication failed", None)
        self.assertEqual(plan_auth.severity, Severity.CRITICAL)

    def test_recommend_action_fallback(self):
        plan = self.classifier.classify("504 Gateway Timeout", None)
        self.assertEqual(plan.recommended_action, "retry_with_backoff")

    def test_default_says_no_retry(self):
        plan = self.classifier.classify("totally unknown error xyz123", None)
        self.assertFalse(plan.retry)
        self.assertFalse(plan.switch_model)
        self.assertFalse(plan.compress)


class AutoRecoveryPlanTests(unittest.TestCase):
    def test_creation_with_custom_actions(self):
        plan = AutoRecoveryPlan(
            categories=[ErrorCategory.RATE_LIMIT],
            severity=Severity.MEDIUM,
            message="test",
            actions=[RecoveryAction(action="custom", detail="x", priority=1)],
            retry=True,
        )
        self.assertTrue(plan.retry)
        self.assertEqual(plan.recommended_action, "custom")


class ClassifierSingletonTests(unittest.TestCase):
    def test_get_classifier_returns_instance(self):
        c = get_classifier()
        self.assertIsInstance(c, ErrorClassifier)


if __name__ == "__main__":
    unittest.main()
