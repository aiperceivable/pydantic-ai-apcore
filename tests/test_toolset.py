"""Tests for ApcoreToolset."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from apcore import (
    Context,
    Executor,
    Identity,
    ModuleAnnotations,
    Registry,
    module,
)
from apcore.registry.types import ModuleDescriptor


def _make_descriptor(
    module_id: str = "test.module",
    description: str = "A test module",
    annotations: ModuleAnnotations | None = None,
    input_schema: dict[str, Any] | None = None,
) -> ModuleDescriptor:
    return ModuleDescriptor(
        module_id=module_id,
        name=module_id,
        description=description,
        documentation=None,
        input_schema=input_schema or {"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        annotations=annotations,
    )


class TestDescriptorToToolDef:
    """Test _descriptor_to_tool_def conversion."""

    def test_basic_conversion(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        desc = _make_descriptor()
        tool_def = _descriptor_to_tool_def(desc)

        assert tool_def.name == "test.module"
        assert tool_def.description == "A test module"
        assert tool_def.kind == "function"
        assert tool_def.metadata is None

    def test_destructive_annotation_adds_warning(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        desc = _make_descriptor(
            annotations=ModuleAnnotations(destructive=True),
        )
        tool_def = _descriptor_to_tool_def(desc)

        assert "DESTRUCTIVE" in tool_def.description
        assert tool_def.metadata is not None
        assert tool_def.metadata["destructive"] is True

    def test_requires_approval_sets_unapproved_kind(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        desc = _make_descriptor(
            annotations=ModuleAnnotations(requires_approval=True),
        )
        tool_def = _descriptor_to_tool_def(desc)

        assert tool_def.kind == "unapproved"
        assert "REQUIRES APPROVAL" in tool_def.description

    def test_readonly_annotation_metadata(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        desc = _make_descriptor(
            annotations=ModuleAnnotations(readonly=True, idempotent=True),
        )
        tool_def = _descriptor_to_tool_def(desc)

        assert tool_def.kind == "function"
        assert tool_def.metadata["readonly"] is True
        assert tool_def.metadata["idempotent"] is True

    def test_input_schema_passthrough(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "User name"},
            },
            "required": ["name"],
        }
        desc = _make_descriptor(input_schema=schema)
        tool_def = _descriptor_to_tool_def(desc)

        assert tool_def.parameters_json_schema == schema


class TestApcoreToolsetFiltering:
    """Test include/exclude filtering."""

    def test_should_include_no_filters(self) -> None:
        from pydantic_ai_apcore.toolset import ApcoreToolset

        registry = MagicMock(spec=Registry)
        executor = MagicMock(spec=Executor)
        ts = ApcoreToolset(registry, executor)

        assert ts._should_include("any.module") is True

    def test_should_include_with_include_pattern(self) -> None:
        from pydantic_ai_apcore.toolset import ApcoreToolset

        registry = MagicMock(spec=Registry)
        executor = MagicMock(spec=Executor)
        ts = ApcoreToolset(registry, executor, include=["api.*"])

        assert ts._should_include("api.users") is True
        assert ts._should_include("admin.users") is False

    def test_should_include_with_exclude_pattern(self) -> None:
        from pydantic_ai_apcore.toolset import ApcoreToolset

        registry = MagicMock(spec=Registry)
        executor = MagicMock(spec=Executor)
        ts = ApcoreToolset(registry, executor, exclude=["internal.*"])

        assert ts._should_include("api.users") is True
        assert ts._should_include("internal.debug") is False

    def test_exclude_takes_precedence(self) -> None:
        from pydantic_ai_apcore.toolset import ApcoreToolset

        registry = MagicMock(spec=Registry)
        executor = MagicMock(spec=Executor)
        ts = ApcoreToolset(
            registry, executor,
            include=["api.*"],
            exclude=["api.internal"],
        )

        assert ts._should_include("api.users") is True
        assert ts._should_include("api.internal") is False


class TestApcoreToolsetIntegration:
    """Integration tests with real Registry and Executor."""

    def _setup_registry(self) -> tuple[Registry, Executor]:
        registry = Registry()
        executor = Executor(registry=registry)

        @module(id="math.add", registry=registry)
        def add(a: int, b: int) -> dict:
            """Add two numbers.

            Args:
                a: First number.
                b: Second number.
            """
            return {"result": a + b}

        return registry, executor

    @pytest.mark.asyncio
    async def test_get_tools_returns_registered_modules(self) -> None:
        from pydantic_ai_apcore.toolset import ApcoreToolset

        registry, executor = self._setup_registry()
        ts = ApcoreToolset(registry, executor)

        ctx = MagicMock()
        tools = await ts.get_tools(ctx)

        assert "math.add" in tools
        tool = tools["math.add"]
        assert tool.tool_def.name == "math.add"
        assert "Add two numbers" in (tool.tool_def.description or "")

    @pytest.mark.asyncio
    async def test_call_tool_executes_module(self) -> None:
        from pydantic_ai_apcore.toolset import ApcoreToolset

        registry, executor = self._setup_registry()
        ts = ApcoreToolset(registry, executor)

        ctx = MagicMock()
        tools = await ts.get_tools(ctx)
        tool = tools["math.add"]

        result = await ts.call_tool(
            "math.add", {"a": 3, "b": 5}, ctx, tool
        )
        assert result == {"result": 8}
