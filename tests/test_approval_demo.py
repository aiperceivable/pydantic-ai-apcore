"""Integration test for the approval demo (examples/approval_demo).

Pins the ordering the demo exists to show: pydantic-ai suspends the run first,
and the apcore approval gate only runs once a human has sanctioned the call.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

ACL_PATH = REPO_ROOT / "examples" / "approval_demo" / "acl.yaml"


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch):
    """Toolset, ops identity, and a cleared gate log."""
    monkeypatch.setenv("APCORE_ACL_PATH", str(ACL_PATH))

    from examples.approval_demo import app as demo_app

    demo_app.apcore_gate_log.clear()
    client = demo_app.create_demo_client()
    from apcore import Identity

    toolset = demo_app.ApcoreToolset(
        client.registry,
        client.executor,
        identity_resolver=lambda ctx: Identity(id=ctx.deps.caller_id, type="ai", roles=ctx.deps.roles),
    )
    ops = demo_app.AgentIdentity(caller_id="agent.ops", roles=("data_admin",))
    return demo_app, toolset, ops


def _agent(demo_app, toolset, tool: str, args: dict) -> Agent:
    return Agent(
        demo_app.scripted_model(tool, args),
        toolsets=[toolset],
        deps_type=demo_app.AgentIdentity,
        output_type=[str, DeferredToolRequests],
    )


def test_plain_module_runs_without_suspending(demo) -> None:
    demo_app, toolset, ops = demo
    agent = _agent(demo_app, toolset, "crm_read", {"record_id": "C-7"})

    result = agent.run_sync("read it", deps=ops)

    assert not isinstance(result.output, DeferredToolRequests)
    assert "gold" in demo_app.tool_outcome(result.all_messages())


def test_annotated_module_suspends_the_run(demo) -> None:
    demo_app, toolset, ops = demo
    agent = _agent(demo_app, toolset, "crm_delete", {"record_id": "C-9"})

    result = agent.run_sync("delete it", deps=ops)

    # requires_approval became kind="unapproved" on the ToolDefinition.
    assert isinstance(result.output, DeferredToolRequests)
    assert result.output.approvals


def test_apcore_gate_has_not_run_while_suspended(demo) -> None:
    demo_app, toolset, ops = demo
    agent = _agent(demo_app, toolset, "crm_delete", {"record_id": "C-9"})

    agent.run_sync("delete it", deps=ops)

    # The whole point of the demo: the two checkpoints are in series.
    assert demo_app.apcore_gate_log == []


def test_apcore_gate_runs_after_human_approval(demo) -> None:
    demo_app, toolset, ops = demo
    agent = _agent(demo_app, toolset, "crm_delete", {"record_id": "C-9"})
    first = agent.run_sync("delete it", deps=ops)

    approvals = DeferredToolResults()
    for call in first.output.approvals:
        approvals.approvals[call.tool_call_id] = True
    second = agent.run_sync(
        "continue",
        deps=ops,
        message_history=first.all_messages(),
        deferred_tool_results=approvals,
    )

    assert demo_app.apcore_gate_log == ["agent.ops"]
    assert "'deleted': True" in demo_app.tool_outcome(second.all_messages())
