"""Integration test for the scanner demo (examples/scanner_demo).

Covers the reverse direction end to end: plain pydantic-ai tools are registered
as apcore modules, and the demo's acl.yaml plus its approval gate then govern
them exactly as they would a hand-written module.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from apcore import ACLDeniedError, Context, Identity, Registry
from apcore.errors import ApprovalDeniedError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

ACL_PATH = REPO_ROOT / "examples" / "scanner_demo" / "acl.yaml"


@pytest.fixture
def scanned(monkeypatch: pytest.MonkeyPatch):
    """Register the demo's tools and return (result, executor)."""
    monkeypatch.setenv("APCORE_ACL_PATH", str(ACL_PATH))

    from examples.scanner_demo.app import build_billing_tools, build_executor

    from pydantic_ai_apcore import register_toolset

    registry = Registry()
    result = register_toolset(build_billing_tools("USD"), registry, prefix="billing.", tags=["billing"])
    return result, build_executor(registry)


def _call(executor: Any, target: str, inputs: dict, caller: str = "agent.ops") -> Any:
    context = Context.create(identity=Identity(id=caller, type="ai"))
    context.call_chain = [caller]
    return executor.call(target, inputs, context=context)


def test_plain_tools_are_registered(scanned) -> None:
    result, _ = scanned

    assert "billing.send_invoice" in result.registered
    assert "billing.refund" in result.registered


def test_context_taking_tool_is_skipped_with_a_reason(scanned) -> None:
    result, _ = scanned

    skipped = {s.name: s.reason for s in result.skipped}
    assert "recent_activity" in skipped
    assert "RunContext" in skipped["recent_activity"]


def test_undocumented_parameters_are_flagged(scanned) -> None:
    result, _ = scanned

    gaps = [w for m in result.modules if m.module_id == "billing.lookup" for w in m.warnings if "no description" in w]
    assert gaps and "q" in gaps[0] and "limit" in gaps[0]


def test_closure_target_is_flagged_but_still_runs(scanned) -> None:
    result, executor = scanned

    module = next(m for m in result.modules if m.module_id == "billing.send_invoice")
    assert "<locals>" in module.target
    assert any("not importable" in w for w in module.warnings)

    # `currency` comes from the enclosing scope, so the closure really executed
    # rather than being re-imported from its target path.
    out = _call(executor, "billing.send_invoice", {"customer_id": "C-7", "amount": 1.0})
    assert out["currency"] == "USD"


def test_module_absent_from_acl_is_denied(scanned) -> None:
    _, executor = scanned

    # billing.wire_transfer is deliberately not in acl.yaml.
    with pytest.raises(ACLDeniedError):
        _call(executor, "billing.wire_transfer", {"account": "X-1", "amount": 9000.0})


def test_inherited_requires_approval_is_enforced(scanned) -> None:
    _, executor = scanned

    # The annotation came from the pydantic-ai tool, not from a hand-written
    # apcore module -- this is the round trip the demo claims.
    with pytest.raises(ApprovalDeniedError):
        _call(executor, "billing.refund", {"payment_id": "P-1"})


def test_confirmed_call_passes_the_approval_gate(scanned) -> None:
    _, executor = scanned

    out = _call(executor, "billing.refund", {"payment_id": "P-1", "confirmed": True})

    assert out["refunded"] is True
