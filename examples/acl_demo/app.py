"""pydantic-ai + apcore ACL demo.

Shows how an agent's tool calls are governed by an apcore Access Control List
loaded from YAML, with the calling agent's identity resolved per run.

How it works
------------
1. ``APCORE_ACL_PATH`` points apcore at ``acl.yaml``; the app loads it with
   ``ACL.load()`` and applies it with ``executor.set_acl(acl)``.
2. Each agent run carries an ``AgentIdentity`` in its dependencies, standing in
   for whatever the surrounding application already knows about the caller.
3. ``ApcoreToolset(identity_resolver=...)`` turns those dependencies into an
   apcore ``Identity`` and writes it to both ``Context.identity`` and
   ``Context.call_chain`` -- the ACL matches ``callers`` against the latter and
   ``conditions.roles`` against the former.
4. The Executor checks the ACL before the module runs. A denied call raises
   ``ACLDeniedError``.

Run it::

    python examples/acl_demo/app.py

Runs offline: ``FunctionModel`` drives the tool calls, so no model provider or
API key is involved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apcore import ACL, ACLDeniedError, APCore, Identity
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from pydantic_ai_apcore import ApcoreToolset

# Point apcore at this demo's ACL file unless the caller already set one.
os.environ.setdefault("APCORE_ACL_PATH", str(Path(__file__).parent / "acl.yaml"))


@dataclass
class AgentIdentity:
    """Whatever the surrounding application already knows about the caller."""

    caller_id: str
    roles: tuple[str, ...]


def identity_from_deps(ctx: RunContext[AgentIdentity]) -> Identity:
    """Map the agent run's dependencies onto an apcore Identity."""
    return Identity(id=ctx.deps.caller_id, type="ai", roles=ctx.deps.roles)


def create_demo_client() -> APCore:
    """Register two ACL-protected modules and apply acl.yaml to the Executor."""
    client = APCore()

    @client.module(id="crm.read", description="Read a single CRM record")
    def crm_read(record_id: str) -> dict:
        return {"record_id": record_id, "tier": "gold"}

    @client.module(id="crm.delete", description="Delete a CRM record")
    def crm_delete(record_id: str) -> dict:
        return {"record_id": record_id, "deleted": True}

    acl = ACL.load(os.environ["APCORE_ACL_PATH"])
    client.executor.set_acl(acl)
    return client


def scripted_model(tool_name: str, args: dict[str, Any]) -> FunctionModel:
    """A model that calls one tool, then stops."""
    state = {"called": False}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if state["called"]:
            return ModelResponse(parts=[TextPart("done")])
        state["called"] = True
        return ModelResponse(parts=[ToolCallPart(tool_name, args)])

    return FunctionModel(respond)


def run_as(toolset: ApcoreToolset, deps: AgentIdentity, tool: str, args: dict) -> str:
    """Run one agent turn and report what the governance pipeline decided."""
    agent = Agent(
        scripted_model(tool, args),
        toolsets=[toolset],
        deps_type=AgentIdentity,
    )
    try:
        result = agent.run_sync("do it", deps=deps)
    except ACLDeniedError as exc:
        return f"ACLDeniedError: {exc}"

    for message in result.all_messages():
        for part in getattr(message, "parts", []):
            if type(part).__name__ == "ToolReturnPart":
                return str(part.content)
    return "no tool result"


def main() -> None:
    client = create_demo_client()
    toolset: ApcoreToolset = ApcoreToolset(
        client.registry, client.executor, identity_resolver=identity_from_deps
    )

    analyst = AgentIdentity(caller_id="agent.research", roles=("reader",))
    admin = AgentIdentity(caller_id="agent.ops", roles=("data_admin",))

    print(f"ACL loaded from {os.environ['APCORE_ACL_PATH']}")
    print("=" * 74)
    print()

    cases = [
        ("reader reads   ", analyst, "crm_read", {"record_id": "C-7"}),
        ("admin reads    ", admin, "crm_read", {"record_id": "C-7"}),
        ("reader deletes ", analyst, "crm_delete", {"record_id": "C-7"}),
        ("admin deletes  ", admin, "crm_delete", {"record_id": "C-7"}),
    ]
    for label, deps, tool, args in cases:
        print(f"  {label} ({deps.caller_id}, roles={list(deps.roles)})")
        print(f"      -> {run_as(toolset, deps, tool, args)}")
    print()

    print("Why", "=" * 70)
    print("  crm.read is allowed for any agent.* caller, so both identities pass.")
    print("  crm.delete adds conditions.roles: [data_admin]; the reader agent")
    print("  matches the caller pattern but not the role, so it falls through to")
    print("  default_effect: deny. Change acl.yaml and re-run -- no code edits.")


if __name__ == "__main__":
    main()
