"""Unit tests for approval flow runtime."""

import os
import sys
import unittest
import unittest.mock

from ghostchimera.safety_layer.approval import (
    ApprovalHandler,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalResult,
    AutoApproveHandler,
    AutoDenyHandler,
    CallbackApprovalHandler,
    approve,
    get_default_handler,
    get_default_policy,
    set_default_handler,
)


class ApprovalPolicyTests(unittest.TestCase):
    def setUp(self):
        """
        Create a fresh ApprovalPolicy instance and assign it to `self.policy` for use by each test method.
        """
        self.policy = ApprovalPolicy()

    def test_default_trusted_includes_read_file(self):
        self.assertEqual(self.policy.classify("read_file"), "trusted")

    def test_default_trusted_includes_code_search(self):
        self.assertEqual(self.policy.classify("code_search"), "trusted")

    def test_default_blocked_includes_delete_wildcard(self):
        self.assertEqual(self.policy.classify("delete_record"), "blocked")
        self.assertEqual(self.policy.classify("delete_anything"), "blocked")

    def test_default_blocked_includes_rm_wildcard(self):
        self.assertEqual(self.policy.classify("rm_temp"), "blocked")

    def test_classify_unknown_is_requires_approval(self):
        self.assertEqual(self.policy.classify("write_code"), "requires_approval")

    def test_add_trusted(self):
        self.policy.add_trusted("write_code")
        self.assertEqual(self.policy.classify("write_code"), "trusted")

    def test_add_blocked(self):
        self.policy.add_blocked("debug_tool")
        self.assertEqual(self.policy.classify("debug_tool"), "blocked")

    def test_remove_trusted(self):
        self.policy.remove_trusted("read_file")
        self.assertEqual(self.policy.classify("read_file"), "requires_approval")

    def test_remove_blocked(self):
        self.policy.remove_blocked("delete_*")
        # "delete_*" is gone; "delete_record" falls through to requires_approval
        self.assertEqual(self.policy.classify("delete_record"), "requires_approval")

    def test_glob_pattern_trusted(self):
        self.policy.add_trusted("read_*")
        self.assertEqual(self.policy.classify("read_file"), "trusted")
        self.assertEqual(self.policy.classify("read_log"), "trusted")

    def test_glob_pattern_blocked(self):
        self.policy.add_blocked("write_*")
        self.assertEqual(self.policy.classify("write_code"), "blocked")

    def test_to_dict(self):
        d = self.policy.to_dict()
        self.assertIn("trusted", d)
        self.assertIn("blocked", d)


class ApprovalRequestTests(unittest.TestCase):
    def test_creation_with_defaults(self):
        req = ApprovalRequest(tool_name="shell", arguments={"cmd": "ls"})
        self.assertEqual(req.tool_name, "shell")
        self.assertEqual(req.arguments, {"cmd": "ls"})
        self.assertEqual(req.requester, "")
        self.assertEqual(req.context, {})

    def test_creation_with_all_fields(self):
        req = ApprovalRequest(
            tool_name="shell",
            arguments={"cmd": "ls"},
            requester="agent-1",
            context={"task_id": "abc"},
        )
        self.assertEqual(req.requester, "agent-1")
        self.assertEqual(req.context, {"task_id": "abc"})

    def test_to_dict(self):
        req = ApprovalRequest(tool_name="shell", arguments={"cmd": "ls"}, requester="agent-1")
        d = req.to_dict()
        self.assertEqual(d["tool_name"], "shell")
        self.assertEqual(d["arguments"], {"cmd": "ls"})
        self.assertEqual(d["requester"], "agent-1")
        self.assertEqual(d["context"], {})


class ApprovalResultTests(unittest.TestCase):
    def test_allow(self):
        r = ApprovalResult.allow(reason="ok", approver="policy")
        self.assertTrue(r.approved)
        self.assertEqual(r.reason, "ok")
        self.assertEqual(r.approver, "policy")

    def test_deny(self):
        r = ApprovalResult.deny(reason="nope", approver="policy")
        self.assertFalse(r.approved)
        self.assertEqual(r.reason, "nope")

    def test_to_dict(self):
        r = ApprovalResult(approved=True, reason="ok")
        d = r.to_dict()
        self.assertTrue(d["approved"])
        self.assertEqual(d["reason"], "ok")


class AutoApproveHandlerTests(unittest.TestCase):
    def setUp(self):
        """
        Create a fresh ApprovalPolicy and an AutoApproveHandler bound to it for use in each test.
        
        Initializes self.policy with a new ApprovalPolicy instance and self.handler with an AutoApproveHandler that uses that policy.
        """
        self.policy = ApprovalPolicy()
        self.handler = AutoApproveHandler(self.policy)

    def test_auto_approves_requires_approval(self):
        # "write_code" is not trusted/blocked → requires_approval → auto-approved
        req = ApprovalRequest(tool_name="write_code", requester="agent")
        result = self.handler.handle(req)
        self.assertTrue(result.approved)

    def test_does_not_overwrite_trusted(self):
        req = ApprovalRequest(tool_name="read_file", requester="agent")
        result = self.handler.handle(req)
        self.assertTrue(result.approved)
        self.assertIn("trusted", result.reason)

    def test_does_not_overwrite_blocked(self):
        req = ApprovalRequest(tool_name="delete_record", requester="agent")
        result = self.handler.handle(req)
        self.assertFalse(result.approved)
        self.assertIn("blocked", result.reason)


class AutoDenyHandlerTests(unittest.TestCase):
    def setUp(self):
        """
        Prepare a fresh ApprovalPolicy and an AutoDenyHandler instance for each test.
        
        Creates:
        - self.policy: a new ApprovalPolicy
        - self.handler: an AutoDenyHandler constructed with the new policy
        """
        self.policy = ApprovalPolicy()
        self.handler = AutoDenyHandler(self.policy)

    def test_auto_denies_requires_approval(self):
        req = ApprovalRequest(tool_name="write_code", requester="agent")
        result = self.handler.handle(req)
        self.assertFalse(result.approved)

    def test_does_not_overwrite_trusted(self):
        req = ApprovalRequest(tool_name="read_file", requester="agent")
        result = self.handler.handle(req)
        self.assertTrue(result.approved)


class CallbackApprovalHandlerTests(unittest.TestCase):
    def setUp(self):
        """
        Create a fresh ApprovalPolicy instance and assign it to `self.policy` for use by each test method.
        """
        self.policy = ApprovalPolicy()

    def test_callback_approve(self):
        handler = CallbackApprovalHandler(lambda r: True, self.policy)
        req = ApprovalRequest(tool_name="write_code", requester="agent")
        self.assertTrue(handler.handle(req).approved)

    def test_callback_deny(self):
        handler = CallbackApprovalHandler(lambda r: False, self.policy)
        req = ApprovalRequest(tool_name="write_code", requester="agent")
        self.assertFalse(handler.handle(req).approved)

    def test_callback_exception(self):
        handler = CallbackApprovalHandler(lambda r: 1 / 0, self.policy)
        req = ApprovalRequest(tool_name="write_code", requester="agent")
        result = handler.handle(req)
        self.assertFalse(result.approved)


class ApprovalHandlerIntegrationTests(unittest.TestCase):
    def test_approved_flow(self):
        policy = ApprovalPolicy()
        policy.add_trusted("read_file")
        handler = AutoApproveHandler(policy)
        result = handler.handle(ApprovalRequest(tool_name="read_file"))
        self.assertTrue(result.approved)

    def test_deny_then_recover(self):
        policy = ApprovalPolicy()
        handler = AutoDenyHandler(policy)
        result1 = handler.handle(ApprovalRequest(tool_name="write_code"))
        self.assertFalse(result1.approved)
        policy.add_trusted("write_code")
        result2 = handler.handle(ApprovalRequest(tool_name="write_code"))
        self.assertTrue(result2.approved)


class DefaultPolicyAndHandlerTests(unittest.TestCase):
    def setUp(self):
        # Avoid the blocking sys.stdin.isatty() in get_default_handler()
        # by pre-seeding the singleton.
        """
        Prepare the test fixture by pre-seeding the approval module's default handler.
        
        Sets ghostchimera.safety_layer.approval._default_handler to an AutoDenyHandler(ApprovalPolicy()) to avoid blocking behavior (for example, sys.stdin.isatty()) when tests call get_default_handler().
        """
        import ghostchimera.safety_layer.approval as approval_mod
        approval_mod._default_handler = AutoDenyHandler(ApprovalPolicy())

    def test_get_default_policy_returns_policy(self):
        p = get_default_policy()
        self.assertIsInstance(p, ApprovalPolicy)

    def test_get_default_handler_returns_handler(self):
        h = get_default_handler()
        self.assertIsInstance(h, ApprovalHandler)

    def test_set_default_handler_overrides(self):
        original = get_default_handler()
        custom = AutoApproveHandler(ApprovalPolicy())
        set_default_handler(custom)
        self.assertIsInstance(get_default_handler(), AutoApproveHandler)
        set_default_handler(original)  # restore


class ApproveFunctionTests(unittest.TestCase):
    def setUp(self):
        """
        Prepare the test fixture by installing a non-interactive default approval handler.
        
        Sets ghostchimera.safety_layer.approval._default_handler to an AutoDenyHandler backed by a fresh ApprovalPolicy so tests do not block on interactive checks (e.g., sys.stdin.isatty()).
        """
        import ghostchimera.safety_layer.approval as approval_mod
        approval_mod._default_handler = AutoDenyHandler(ApprovalPolicy())

    def test_approve_uses_default_handler(self):
        set_default_handler(AutoDenyHandler(ApprovalPolicy()))
        result = approve("write_code", requester="test")
        self.assertFalse(result.approved)
        set_default_handler(AutoApproveHandler(ApprovalPolicy()))


if __name__ == "__main__":
    unittest.main()
