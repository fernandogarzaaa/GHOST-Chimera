"""Tests for the safe Computer Use hierarchy."""

from __future__ import annotations

import time

from ghostchimera.stealth import (
    ComputerAction,
    ComputerApproval,
    ComputerCapability,
    ComputerModality,
    ComputerRisk,
    ComputerUseManager,
    DelegatingComputerProvider,
    StealthLoop,
    WorkflowMaturity,
    classify_risk,
)


def _capability() -> ComputerCapability:
    return ComputerCapability(
        name="test",
        enabled=True,
        allowed_modalities=frozenset(
            {
                ComputerModality.BROWSER,
                ComputerModality.DESKTOP,
                ComputerModality.VISION,
            }
        ),
        allowed_operations=frozenset(
            {
                "browser.read",
                "browser.click",
                "browser.navigate",
                "desktop.read",
                "vision.read",
                "ui.read",
                "ui.click",
            }
        ),
        max_risk=ComputerRisk.HIGH,
    )


def _manager() -> ComputerUseManager:
    manager = ComputerUseManager()
    manager.register(
        DelegatingComputerProvider(
            name="browser-structured",
            modality=ComputerModality.BROWSER,
            executor=lambda action: {"text": "browser result"},
        )
    )
    manager.register(
        DelegatingComputerProvider(
            name="desktop-accessibility",
            modality=ComputerModality.DESKTOP,
            executor=lambda action: {"text": "desktop result"},
        )
    )
    manager.register(
        DelegatingComputerProvider(
            name="vision-last-resort",
            modality=ComputerModality.VISION,
            executor=lambda action: {"text": "vision result"},
        )
    )
    return manager


def test_generic_action_uses_evidence_before_vision_last_resort() -> None:
    browser_action = ComputerAction(
        operation="ui.read",
        target="invoice",
        context={"active_url": "https://example.com"},
    )
    desktop_action = ComputerAction(
        operation="ui.click",
        target="Save",
        context={"active_application": "Editor"},
    )
    vision_action = ComputerAction(operation="ui.read", target="invoice")

    assert browser_action.resolved_modality() == ComputerModality.BROWSER
    assert desktop_action.resolved_modality() == ComputerModality.DESKTOP
    assert vision_action.resolved_modality() == ComputerModality.VISION


def test_risk_classification_marks_sensitive_and_destructive_actions() -> None:
    assert classify_risk("browser.read", "invoice", {}) == ComputerRisk.LOW
    assert classify_risk("browser.navigate", "https://example.com", {}) == ComputerRisk.HIGH
    assert classify_risk("browser.read", "password vault", {}) == ComputerRisk.HIGH
    assert classify_risk("desktop.type", "editor", {"text": "api token"}) == ComputerRisk.HIGH


def test_unavailable_preferred_provider_falls_back_safely() -> None:
    manager = ComputerUseManager()
    manager.register(DelegatingComputerProvider(name="desktop-offline", modality=ComputerModality.DESKTOP))
    manager.register(
        DelegatingComputerProvider(
            name="browser-structured",
            modality=ComputerModality.BROWSER,
            executor=lambda action: {"ok": True},
        )
    )
    manager.register(
        DelegatingComputerProvider(
            name="vision-last-resort",
            modality=ComputerModality.VISION,
            executor=lambda action: {"ok": True},
        )
    )
    action = ComputerAction(
        operation="ui.click",
        target="Save",
        context={"active_application": "Editor"},
    )

    plan = manager.plan(action, _capability(), WorkflowMaturity.VALIDATING)

    assert plan.executable is True
    assert plan.modality == ComputerModality.BROWSER
    assert plan.provider == "browser-structured"
    assert "vision-last-resort" in plan.fallbacks


def test_low_risk_read_can_execute_for_trusted_maturity_with_approval_gate() -> None:
    manager = _manager()
    action = ComputerAction(operation="browser.read", target="invoice")
    plan = manager.plan(action, _capability(), WorkflowMaturity.AUTONOMOUS)

    assert plan.approval_required is False
    receipt = manager.execute(plan, _capability())
    assert receipt["ok"] is True
    assert receipt["result"] == {"text": "browser result"}

    untrusted = manager.plan(action, _capability(), WorkflowMaturity.VALIDATING)
    assert untrusted.approval_required is True
    assert manager.execute(untrusted, _capability())["ok"] is False


def test_high_risk_action_requires_matching_unexpired_approval() -> None:
    manager = _manager()
    action = ComputerAction(operation="browser.navigate", target="https://example.com")
    plan = manager.plan(action, _capability(), WorkflowMaturity.AUTONOMOUS)

    assert plan.approval_required is True
    assert manager.execute(plan, _capability())["ok"] is False
    wrong = ComputerApproval(approved_by="operator", action_id="other-action")
    assert manager.execute(plan, _capability(), wrong)["ok"] is False
    expired = ComputerApproval(
        approved_by="operator",
        action_id=action.action_id,
        granted_at=time.time() - 10,
        expires_at=time.time() - 1,
    )
    assert manager.execute(plan, _capability(), expired)["ok"] is False
    approval = ComputerApproval(approved_by="operator", action_id=action.action_id)
    receipt = manager.execute(plan, _capability(), approval)
    assert receipt["ok"] is True
    assert receipt["idempotency_key"] == action.idempotency_key


def test_disabled_capability_denies_plans_and_receipts() -> None:
    manager = _manager()
    action = ComputerAction(operation="browser.read", target="invoice")
    capability = ComputerCapability()

    plan = manager.plan(action, capability, WorkflowMaturity.AUTONOMOUS)

    assert plan.executable is False
    assert manager.execute(plan, capability)["ok"] is False


def test_loop_computer_use_preserves_approval_and_receipt_flow() -> None:
    loop = StealthLoop(computer_capability=_capability())
    loop.computer.register(
        DelegatingComputerProvider(
            name="test-browser",
            modality=ComputerModality.BROWSER,
            executor=lambda action: {"text": "loop result"},
        )
    )
    try:
        action = {"operation": "browser.read", "target": "invoice"}
        planned = loop.request_computer_use(action, workflow="invoice", dry_run=True)

        assert planned["ok"] is True
        assert planned["receipt"] is None
        assert planned["plan"]["provider"] == "test-browser"

        denied = loop.request_computer_use(
            {**action, "action_id": planned["plan"]["action"]["action_id"]}, workflow="invoice"
        )
        assert denied["ok"] is False
        approval = ComputerApproval(approved_by="operator", action_id=denied["plan"]["action"]["action_id"])
        executed = loop.request_computer_use(
            {**action, "action_id": denied["plan"]["action"]["action_id"]},
            workflow="invoice",
            approval=approval,
        )
        assert executed["ok"] is True
        assert executed["receipt"]["result"] == {"text": "loop result"}
    finally:
        loop.close()
