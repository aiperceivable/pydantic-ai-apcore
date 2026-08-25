"""Put the tools an agent already has behind the apcore execution boundary.

The reverse of `acl_demo` and `approval_demo`: instead of exposing apcore
modules to an agent, this takes plain pydantic-ai tools and registers them as
governed modules, so they gain ACL and approval semantics and can be served on
other surfaces without being rewritten.

Run it::

    python examples/scanner_demo/app.py

Runs offline -- no model provider is involved.
"""

from __future__ import annotations

import os
from pathlib import Path

from apcore import ACL, ACLDeniedError, Context, Executor, Identity, Registry
from apcore.approval import ApprovalRequest, ApprovalResult, CallbackApprovalHandler
from apcore.errors import ApprovalDeniedError
from pydantic_ai import RunContext
from pydantic_ai.toolsets.function import FunctionToolset

from pydantic_ai_apcore import register_toolset

os.environ.setdefault("APCORE_ACL_PATH", str(Path(__file__).parent / "acl.yaml"))


def build_billing_tools(currency: str) -> FunctionToolset:
    """Tools defined inside a scope, closing over a dependency.

    This shape is common in pydantic-ai and is why registration holds the
    callables from the scan rather than resolving them by import path.
    """
    toolset = FunctionToolset()

    @toolset.tool
    def send_invoice(customer_id: str, amount: float) -> dict:
        """Send an invoice to a customer.

        Args:
            customer_id: Who to bill.
            amount: How much to bill them.
        """
        return {"customer_id": customer_id, "amount": amount, "currency": currency}

    @toolset.tool(requires_approval=True)
    def refund(payment_id: str, confirmed: bool = False) -> dict:
        """Refund a payment in full.

        Args:
            payment_id: The payment to reverse.
            confirmed: Whether the caller has confirmed the reversal.
        """
        return {"payment_id": payment_id, "refunded": True, "currency": currency}

    @toolset.tool
    def wire_transfer(account: str, amount: float) -> dict:
        """Move money to an external account.

        Args:
            account: Destination account.
            amount: How much to send.
        """
        return {"account": account, "sent": amount}

    @toolset.tool
    def lookup(q: str, limit: int) -> dict:  # no docstring on purpose
        return {"q": q, "limit": limit}

    @toolset.tool
    def recent_activity(ctx: RunContext, customer_id: str) -> dict:
        """Needs the agent run context, so apcore cannot invoke it.

        Args:
            customer_id: Whose activity to read.
        """
        return {"customer_id": customer_id}

    return toolset


def build_executor(registry: Registry) -> Executor:
    """acl.yaml plus an approval gate that wants explicit confirmation."""
    executor = Executor(registry=registry)
    executor.set_acl(ACL.load(os.environ["APCORE_ACL_PATH"]))

    async def review(request: ApprovalRequest) -> ApprovalResult:
        if request.arguments.get("confirmed") is True:
            return ApprovalResult(status="approved", approved_by="policy-gate")
        return ApprovalResult(
            status="rejected",
            approved_by="policy-gate",
            reason="caller did not confirm the reversal",
        )

    executor.set_approval_handler(CallbackApprovalHandler(review))
    return executor


def main() -> None:
    registry = Registry()
    result = register_toolset(
        build_billing_tools("USD"), registry, prefix="billing.", tags=["billing"]
    )

    print("Registered")
    print("-" * 74)
    for module_id in result.registered:
        print(f"  {module_id}")
    for skipped in result.skipped:
        print(f"  skipped {skipped.name}: {skipped.reason}")
    print()

    print("What the scan flagged")
    print("-" * 74)
    unimportable = [
        m for m in result.modules if any("not importable" in w for w in m.warnings)
    ]
    if unimportable:
        # One line rather than one per tool: every closure trips this, and on a
        # real toolset it would bury the warnings that need action.
        print(f"  {len(unimportable)} tools are defined inside another scope, so their")
        print("  targets are not importable. They still register and execute here.")
    for module in result.modules:
        for warning in module.warnings:
            if "no description" in warning:
                print(f"  {module.module_id}: {warning}")
    print("  Missing descriptions are the ones worth acting on -- pass")
    print("  enhancers=[AIEnhancer()] to fill them in before registration.")
    print()

    print("Governance now applies to what were plain functions")
    print("-" * 74)
    executor = build_executor(registry)

    def call_as(caller: str, target: str, inputs: dict) -> str:
        context = Context.create(identity=Identity(id=caller, type="ai"))
        context.call_chain = [caller]
        try:
            return str(executor.call(target, inputs, context=context))
        except ACLDeniedError as exc:
            return f"ACLDeniedError: {exc}"
        except ApprovalDeniedError as exc:
            return f"ApprovalDeniedError: {exc.reason}"

    print(
        "  allowed by ACL    :",
        call_as(
            "agent.ops", "billing.send_invoice", {"customer_id": "C-7", "amount": 42.0}
        ),
    )
    print(
        "  blocked by ACL    :",
        call_as(
            "agent.ops", "billing.wire_transfer", {"account": "X-1", "amount": 9000.0}
        ),
    )
    # The ACL runs before the approval gate, so a tool has to pass the ACL first
    # for its requires_approval annotation to matter at all.
    print(
        "  approval refused  :",
        call_as("agent.ops", "billing.refund", {"payment_id": "P-1"}),
    )
    print(
        "  approval granted  :",
        call_as(
            "agent.ops", "billing.refund", {"payment_id": "P-1", "confirmed": True}
        ),
    )
    print()

    print("What this buys")
    print("-" * 74)
    print("  requires_approval came across from the pydantic-ai tool and is now")
    print("  enforced by the apcore gate -- the annotation survived the trip.")
    print("  These are ordinary apcore modules: the same registry can be served")
    print("  over MCP (serve_mcp, [mcp] extra) or the command line (serve_cli,")
    print("  [cli] extra), and acl.yaml applies on every one of those surfaces.")


if __name__ == "__main__":
    main()
