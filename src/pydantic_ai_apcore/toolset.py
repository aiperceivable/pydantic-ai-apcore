"""ApcoreToolset -- AbstractToolset that exposes apcore modules as pydantic-ai tools."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from apcore import Context, Executor, Identity, Registry
from apcore.registry.types import ModuleDescriptor
from pydantic_ai import RunContext, ToolDefinition
from pydantic_ai.toolsets.abstract import AbstractToolset, AgentDepsT, ToolsetTool


class ApcoreToolset(AbstractToolset[AgentDepsT]):
    """Expose apcore registry modules as pydantic-ai tools.

    Each registered apcore module becomes a tool with its input_schema
    as parameters, annotations mapped to ToolDefinition metadata, and
    execution delegated to the apcore Executor pipeline.

    Args:
        registry: The apcore Registry containing discovered modules.
        executor: The apcore Executor for running modules.
        identity: Optional Identity for ACL checks during execution.
        include: Optional list of module ID patterns to include (glob-style).
        exclude: Optional list of module ID patterns to exclude (glob-style).
        toolset_id: Optional unique ID for this toolset instance.
    """

    def __init__(
        self,
        registry: Registry,
        executor: Executor,
        *,
        identity: Identity | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        toolset_id: str | None = None,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._identity = identity
        self._include = include
        self._exclude = exclude
        self._toolset_id = toolset_id

    @property
    def id(self) -> str | None:
        return self._toolset_id

    async def get_tools(
        self, ctx: RunContext[AgentDepsT]
    ) -> dict[str, ToolsetTool[AgentDepsT]]:
        """Convert all matching apcore modules into pydantic-ai tools."""
        tools: dict[str, ToolsetTool[AgentDepsT]] = {}
        validator = TypeAdapter(dict[str, Any]).validator

        for module_id in self._registry.list():
            if not self._should_include(module_id):
                continue

            descriptor = self._registry.get_definition(module_id)
            if descriptor is None:
                continue

            tool_def = _descriptor_to_tool_def(descriptor)

            tools[tool_def.name] = ToolsetTool(
                toolset=self,
                tool_def=tool_def,
                max_retries=1,
                args_validator=validator,
            )

        return tools

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDepsT],
        tool: ToolsetTool[AgentDepsT],
    ) -> Any:
        """Execute an apcore module via the Executor pipeline."""
        context = Context.create(
            executor=self._executor,
            identity=self._identity,
        )
        return await self._executor.call_async(name, tool_args, context)

    def _should_include(self, module_id: str) -> bool:
        """Check if a module matches include/exclude filters."""
        from apcore.utils import match_pattern

        if self._exclude:
            for pattern in self._exclude:
                if match_pattern(pattern, module_id):
                    return False

        if self._include:
            for pattern in self._include:
                if match_pattern(pattern, module_id):
                    return True
            return False

        return True


def _descriptor_to_tool_def(descriptor: ModuleDescriptor) -> ToolDefinition:
    """Convert an apcore ModuleDescriptor to a pydantic-ai ToolDefinition."""
    annotations = descriptor.annotations
    description = descriptor.description or ""

    if annotations is not None:
        warnings: list[str] = []
        if annotations.destructive:
            warnings.append(
                "WARNING: DESTRUCTIVE - This operation may irreversibly "
                "modify or delete data. Confirm with user before calling."
            )
        if annotations.requires_approval:
            warnings.append(
                "REQUIRES APPROVAL: Human confirmation is required."
            )
        if warnings:
            description = description + "\n\n" + "\n".join(warnings)

    kind: str = "function"
    if annotations is not None and annotations.requires_approval:
        kind = "unapproved"

    metadata: dict[str, Any] | None = None
    if annotations is not None:
        metadata = {
            "readonly": annotations.readonly,
            "destructive": annotations.destructive,
            "idempotent": annotations.idempotent,
            "open_world": annotations.open_world,
            "streaming": annotations.streaming,
        }

    return ToolDefinition(
        name=descriptor.module_id,
        description=description,
        parameters_json_schema=descriptor.input_schema,
        kind=kind,
        metadata=metadata,
    )
