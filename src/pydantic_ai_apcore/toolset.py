"""ApcoreToolset -- AbstractToolset that exposes apcore modules as pydantic-ai tools."""

from __future__ import annotations

import re
from typing import Any, Callable

from pydantic import TypeAdapter

from apcore import Context, Executor, Identity, Registry
from apcore.registry.types import ModuleDescriptor
from pydantic_ai import RunContext, ToolDefinition
from pydantic_ai.toolsets.abstract import AbstractToolset, AgentDepsT, ToolsetTool

__all__ = ["ApcoreToolset"]

# Tool names reach model providers directly, and the major ones accept only
# [a-zA-Z0-9_-]. apcore module IDs are dotted by convention ("executor.crm.read"),
# so they are translated before being offered to a model.
_INVALID_TOOL_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")

# Key under which the original module ID travels in ToolDefinition.metadata.
# Carrying it on the tool definition keeps this toolset stateless: call_tool
# recovers the module ID from the tool it was handed, with no lookup table to
# keep in sync across concurrent runs.
_MODULE_ID_KEY = "apcore_module_id"


class ApcoreToolset(AbstractToolset[AgentDepsT]):
    """Expose apcore registry modules as pydantic-ai tools.

    Each registered module becomes a tool whose parameters are the module's
    ``input_schema``, whose annotations map onto ``ToolDefinition`` metadata, and
    whose execution goes through the apcore ``Executor`` pipeline -- so schema
    validation, ACL, approval gates, middleware, and audit all still apply.

    Arguments are validated by the apcore pipeline rather than a second time
    here, so the tool's own validator stays permissive; a bad argument surfaces
    as an apcore validation error rather than a locally-generated retry.

    Args:
        registry: The apcore Registry containing discovered modules.
        executor: The apcore Executor for running modules.
        identity: Fixed Identity used for every call. Suitable when the whole
            agent runs as one principal. Ignored for a given call when
            ``identity_resolver`` returns an Identity for it.
        identity_resolver: Called with the run context to derive the Identity for
            each call, so one toolset can serve several principals -- typically
            reading from ``ctx.deps``. Takes precedence over ``identity``.
        include: Optional list of module ID patterns to include (glob-style).
        exclude: Optional list of module ID patterns to exclude (glob-style).
        toolset_id: Optional unique ID for this toolset instance.
        max_retries: Retries pydantic-ai allows per tool call.
        sanitize_tool_names: Translate dotted module IDs into provider-safe tool
            names. Set to ``False`` to offer module IDs verbatim, which most
            providers reject.

    Note:
        The resolved Identity is written to both ``Context.identity`` and
        ``Context.call_chain``. apcore matches ACL ``callers`` patterns against
        ``call_chain[-1]`` and ``conditions.roles`` against the Identity, so a
        rule keyed on a caller pattern only matches when both are populated.
    """

    def __init__(
        self,
        registry: Registry,
        executor: Executor,
        *,
        identity: Identity | None = None,
        identity_resolver: Callable[[RunContext[AgentDepsT]], Identity | None]
        | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        toolset_id: str | None = None,
        max_retries: int = 1,
        sanitize_tool_names: bool = True,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._identity = identity
        self._identity_resolver = identity_resolver
        self._include = include
        self._exclude = exclude
        self._toolset_id = toolset_id
        self._max_retries = max_retries
        self._sanitize_tool_names = sanitize_tool_names

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

            tool_def = _descriptor_to_tool_def(
                descriptor, self._tool_name(module_id, tools)
            )

            tools[tool_def.name] = ToolsetTool(
                toolset=self,
                tool_def=tool_def,
                max_retries=self._max_retries,
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
        module_id = _module_id_of(tool, fallback=name)
        context = self._build_context(ctx)
        return await self._executor.call_async(module_id, tool_args, context)

    def _build_context(self, ctx: RunContext[AgentDepsT]) -> Context:
        """Create the apcore Context carrying the caller's identity."""
        identity = self._resolve_identity(ctx)
        context = Context.create(identity=identity)
        if identity is not None:
            # ACL `callers` patterns are matched against call_chain[-1]; without
            # this the caller reads as absent and caller-keyed rules never match.
            context.call_chain = [identity.id]
        return context

    def _resolve_identity(self, ctx: RunContext[AgentDepsT]) -> Identity | None:
        if self._identity_resolver is not None:
            resolved = self._identity_resolver(ctx)
            if resolved is not None:
                return resolved
        return self._identity

    def _tool_name(self, module_id: str, taken: dict[str, Any]) -> str:
        """Provider-safe, collision-free tool name for a module ID."""
        if not self._sanitize_tool_names:
            return module_id

        name = _INVALID_TOOL_NAME_CHARS.sub("_", module_id)
        if name not in taken:
            return name

        # Two module IDs can sanitize to the same name ("a.b" and "a_b").
        suffix = 2
        while f"{name}_{suffix}" in taken:
            suffix += 1
        return f"{name}_{suffix}"

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


def _module_id_of(tool: ToolsetTool[Any], *, fallback: str) -> str:
    """Recover the apcore module ID that a tool was built from."""
    metadata = tool.tool_def.metadata or {}
    module_id = metadata.get(_MODULE_ID_KEY)
    return module_id if isinstance(module_id, str) else fallback


def _build_description(descriptor: ModuleDescriptor) -> str:
    """Assemble the text a model sees, including governance warnings."""
    parts: list[str] = []
    if descriptor.description:
        parts.append(descriptor.description)
    if descriptor.documentation:
        parts.append(descriptor.documentation)

    if descriptor.sunset_date:
        parts.append(
            f"DEPRECATED: this module is scheduled for removal on "
            f"{descriptor.sunset_date}. Prefer a supported alternative."
        )

    annotations = descriptor.annotations
    if annotations is not None:
        warnings: list[str] = []
        if annotations.destructive:
            warnings.append(
                "WARNING: DESTRUCTIVE - This operation may irreversibly "
                "modify or delete data. Confirm with user before calling."
            )
        if annotations.requires_approval:
            warnings.append("REQUIRES APPROVAL: Human confirmation is required.")
        if warnings:
            parts.append("\n".join(warnings))

    for example in descriptor.examples[:3]:
        inputs = getattr(example, "input", None) or getattr(example, "inputs", None)
        if inputs:
            label = getattr(example, "description", None) or "Example"
            parts.append(f"{label}: {inputs}")

    return "\n\n".join(parts)


def _descriptor_to_tool_def(
    descriptor: ModuleDescriptor, tool_name: str
) -> ToolDefinition:
    """Convert an apcore ModuleDescriptor to a pydantic-ai ToolDefinition."""
    annotations = descriptor.annotations

    kind: str = "function"
    sequential = False
    metadata: dict[str, Any] = {
        _MODULE_ID_KEY: descriptor.module_id,
        "version": descriptor.version,
    }
    if descriptor.tags:
        metadata["tags"] = list(descriptor.tags)

    if annotations is not None:
        if annotations.requires_approval:
            kind = "unapproved"
        # A destructive call should not overlap with other tool calls.
        sequential = bool(annotations.destructive)
        metadata.update(
            {
                "readonly": annotations.readonly,
                "destructive": annotations.destructive,
                "idempotent": annotations.idempotent,
                "open_world": annotations.open_world,
                "streaming": annotations.streaming,
                "cacheable": annotations.cacheable,
                "paginated": annotations.paginated,
            }
        )

    return ToolDefinition(
        name=tool_name,
        description=_build_description(descriptor),
        parameters_json_schema=descriptor.input_schema,
        kind=kind,
        sequential=sequential,
        metadata=metadata,
    )
