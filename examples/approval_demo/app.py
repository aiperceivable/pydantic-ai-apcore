"""Two approval checkpoints, and the order they fire in.

A module annotated ``requires_approval`` is gated twice, by two different
systems, for two different reasons:

* **pydantic-ai** suspends the agent run and hands back ``DeferredToolRequests``
  -- may the model make this call at all?
* **apcore** runs its approval gate when the sanctioned call reaches the
  execution pipeline -- does policy allow this particular call?

They are in series, not duplicated. This demo shows that ordering, and that the
apcore gate has not run while the run is still suspended.

Run it::

    python examples/approval_demo/app.py

Runs offline: ``FunctionModel`` drives the tool calls, so no model provider or
API key is involved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apcore import ACL, APCore, Identity
from apcore.approval import ApprovalRequest, ApprovalResult, CallbackApprovalHandler
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from pydantic_ai_apcore import ApcoreToolset

os.environ.setdefault("APCORE_ACL_PATH", str(Path(__file__).parent / "acl.yaml"))

apcore_gate_log: list[str] = []


@dataclass
class AgentIdentity:
    caller_id: str
    roles: tuple[str, ...]


def create_demo_client() -> APCore:
    """One plain module, one gated on human approval."""
    client = APCore()

    @client.module(id="crm.read", description="Read a single CRM record")
    def crm_read(record_id: str) -> dict:
        return {"record_id": record_id, "tier": "gold"}

    @client.module(
        id="crm.delete",
        description="Delete a CRM record",
        annotations={"requires_approval": True, "destructive": True},
    )
    def crm_delete(record_id: str) -> dict:
        return {"record_id": record_id, "deleted": True}

    client.executor.set_acl(ACL.load(os.environ["APCORE_ACL_PATH"]))

    async def review(request: ApprovalRequest) -> ApprovalResult:
        caller = (
            request.context.identity.id if request.context.identity else "anonymous"
        )
        apcore_gate_log.append(caller)
        return ApprovalResult(status="approved", approved_by="policy-gate")

    client.executor.set_approval_handler(CallbackApprovalHandler(review))
    return client


def scripted_model(tool_name: str, args: dict[str, Any]) -> FunctionModel:
    state = {"called": False}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if state["called"]:
            return ModelResponse(parts=[TextPart("done")])
        state["called"] = True
        return ModelResponse(parts=[ToolCallPart(tool_name, args)])

    return FunctionModel(respond)


def tool_outcome(messages: list[ModelMessage]) -> str:
    for message in messages:
        for part in getattr(message, "parts", []):
            if type(part).__name__ in ("ToolReturnPart", "RetryPromptPart"):
                return f"{type(part).__name__}: {str(part.content)[:70]}"
    return "no tool result"


def main() -> None:
    client = create_demo_client()
    toolset: ApcoreToolset = ApcoreToolset(
        client.registry,
        client.executor,
        identity_resolver=lambda ctx: Identity(
            id=ctx.deps.caller_id, type="ai", roles=ctx.deps.roles
        ),
    )
    ops = AgentIdentity(caller_id="agent.ops", roles=("data_admin",))

    print("Annotation -> tool contract")
    print("-" * 74)
    print("  requires_approval=True on the apcore module becomes kind='unapproved'")
    print("  on the pydantic-ai ToolDefinition, so the agent run suspends and")
    print("  returns DeferredToolRequests. No extra wiring, no MCP elicitation.")
    print()

    print("A module without the annotation runs straight through")
    print("-" * 74)
    agent = Agent(
        scripted_model("crm_read", {"record_id": "C-7"}),
        toolsets=[toolset],
        deps_type=AgentIdentity,
        output_type=[str, DeferredToolRequests],
    )
    plain = agent.run_sync("read it", deps=ops)
    print(f"  crm.read: {tool_outcome(plain.all_messages())}")
    print()

    print("Two checkpoints, in order")
    print("-" * 74)
    apcore_gate_log.clear()
    agent = Agent(
        scripted_model("crm_delete", {"record_id": "C-9"}),
        toolsets=[toolset],
        deps_type=AgentIdentity,
        output_type=[str, DeferredToolRequests],
    )
    first = agent.run_sync("delete it", deps=ops)
    print(f"  1. agent run suspended         : {type(first.output).__name__}")
    print(f"     apcore approval gate calls  : {len(apcore_gate_log)}")

    approvals = DeferredToolResults()
    for call in first.output.approvals:
        approvals.approvals[call.tool_call_id] = True

    second = agent.run_sync(
        "continue",
        deps=ops,
        message_history=first.all_messages(),
        deferred_tool_results=approvals,
    )
    print(f"  2. after the human approved    : {len(apcore_gate_log)} gate call(s)")
    print(f"     result                      : {tool_outcome(second.all_messages())}")
    print()

    print("Reading the results")
    print("-" * 74)
    print("  The apcore gate had not run while the agent was suspended: pydantic-ai")
    print("  asks whether the model may make the call at all, and apcore then")
    print("  applies policy to the call a human already sanctioned. Defence in")
    print("  depth, not a duplicated prompt.")
    print()
    print("  Note the ACL runs before either gate. A module the ACL rejects never")
    print("  reaches an approval decision -- see acl_demo.")


if __name__ == "__main__":
    main()
