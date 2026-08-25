"""Integration test for the ACL demo (examples/acl_demo).

Exercises the full path: agent run -> identity_resolver -> Context.identity and
Context.call_chain -> Executor ACL check -> allow/deny, proving that the rules
in the demo's acl.yaml govern tool calls made from a pydantic-ai agent.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# examples/ lives at the repo root, outside the installed `src` package path.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

ACL_PATH = REPO_ROOT / "examples" / "acl_demo" / "acl.yaml"


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch):
    """A demo client whose Executor has the demo ACL applied."""
    monkeypatch.setenv("APCORE_ACL_PATH", str(ACL_PATH))

    from examples.acl_demo.app import (
        ApcoreToolset,
        create_demo_client,
        identity_from_deps,
    )

    client = create_demo_client()
    toolset = ApcoreToolset(
        client.registry, client.executor, identity_resolver=identity_from_deps
    )
    return toolset


@pytest.fixture
def identities():
    from examples.acl_demo.app import AgentIdentity

    return {
        "reader": AgentIdentity(caller_id="agent.research", roles=("reader",)),
        "admin": AgentIdentity(caller_id="agent.ops", roles=("data_admin",)),
    }


def _run(toolset, deps, tool: str) -> str:
    from examples.acl_demo.app import run_as

    return run_as(toolset, deps, tool, {"record_id": "C-7"})


def test_acl_file_exists_and_is_loaded(demo) -> None:
    # A missing or unreadable acl.yaml would leave the Executor ungoverned,
    # which the allow/deny tests below could not distinguish from "allow all".
    assert ACL_PATH.is_file()


def test_reader_can_read(demo, identities) -> None:
    assert "gold" in _run(demo, identities["reader"], "crm_read")


def test_admin_can_read(demo, identities) -> None:
    assert "gold" in _run(demo, identities["admin"], "crm_read")


def test_reader_cannot_delete(demo, identities) -> None:
    # Matches the callers pattern but not conditions.roles, so it falls through
    # to default_effect: deny.
    result = _run(demo, identities["reader"], "crm_delete")
    assert "ACLDeniedError" in result
    assert "agent.research" in result


def test_admin_can_delete(demo, identities) -> None:
    assert "'deleted': True" in _run(demo, identities["admin"], "crm_delete")


def test_denial_names_the_caller_not_none(demo, identities) -> None:
    # Regression guard: if the resolved identity stopped reaching
    # Context.call_chain, the ACL would see no caller and report "None ->".
    assert "None ->" not in _run(demo, identities["reader"], "crm_delete")
