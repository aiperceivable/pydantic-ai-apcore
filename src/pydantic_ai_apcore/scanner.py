"""Register existing pydantic-ai tools as governed apcore modules.

This is the direction that mirrors the other framework integrations: take the
tools an application already has and put them behind the apcore execution
boundary, so they gain schema validation, ACL, approval gates, and audit -- and
so they can then be projected onto other surfaces (MCP, CLI, A2A) without being
rewritten.

:class:`~pydantic_ai_apcore.toolset.ApcoreToolset` goes the other way, exposing
registered modules to an agent. The two compose: tools scanned here become
modules that any surface can serve.

Scanning produces ``apcore_toolkit.ScannedModule`` values, so the ecosystem's
metadata pipeline applies -- in particular the enhancer chain, which matters
here because pydantic-ai does not require parameter descriptions
(``require_parameter_descriptions`` defaults to ``False``) and an undocumented
tool reaches a model with nothing but parameter names to go on.

Registration does not go through ``RegistryWriter``: that resolves a callable
from ``ScannedModule.target`` by import path, which cannot reach a tool defined
inside a function -- a common shape in pydantic-ai, where tools close over
dependencies. The callables are held from the scan instead, so closures
register on equal footing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from apcore import Registry, module
from apcore_toolkit import BaseScanner, Enhancer, ScannedModule
from pydantic_ai.toolsets.function import FunctionToolset

__all__ = ["PydanticAIScanner", "ScanResult", "SkippedTool", "register_toolset"]


@dataclass(frozen=True)
class SkippedTool:
    """A tool that could not be registered, and why."""

    name: str
    reason: str


@dataclass(frozen=True)
class ScanResult:
    """What a scan registered, and what it left behind."""

    registered: list[str]
    skipped: list[SkippedTool]
    modules: list[ScannedModule]


class PydanticAIScanner(BaseScanner):
    """Read tools out of a pydantic-ai toolset as ``ScannedModule`` values."""

    def __init__(
        self,
        toolset: FunctionToolset,
        *,
        prefix: str = "",
        version: str = "1.0.0",
        tags: list[str] | None = None,
    ) -> None:
        self._toolset = toolset
        self._prefix = prefix
        self._version = version
        self._tags = tags or []
        self._callables: dict[str, Callable[..., Any]] = {}
        self._skipped: list[SkippedTool] = []

    def get_source_name(self) -> str:
        return "pydantic-ai"

    @property
    def skipped(self) -> list[SkippedTool]:
        """Tools the last scan declined to convert."""
        return list(self._skipped)

    def callable_for(self, module_id: str) -> Callable[..., Any] | None:
        """The function behind a scanned module, held from the scan itself."""
        return self._callables.get(module_id)

    def scan(self, **kwargs: Any) -> list[ScannedModule]:
        """Convert every eligible tool into a ``ScannedModule``."""
        self._callables.clear()
        self._skipped.clear()
        scanned: list[ScannedModule] = []

        for name, tool in self._toolset.tools.items():
            if getattr(tool, "takes_ctx", False):
                self._skipped.append(
                    SkippedTool(
                        name=name,
                        reason="takes a RunContext, which apcore cannot supply",
                    )
                )
                continue

            function = getattr(tool, "function", None)
            if function is None:
                self._skipped.append(
                    SkippedTool(name=name, reason="no underlying function")
                )
                continue

            module_id = f"{self._prefix}{name}"
            self._callables[module_id] = function
            scanned.append(self._to_scanned_module(module_id, name, tool, function))

        return self.deduplicate_ids(scanned)

    def _to_scanned_module(
        self,
        module_id: str,
        name: str,
        tool: Any,
        function: Callable[..., Any],
    ) -> ScannedModule:
        schema = getattr(tool.function_schema, "json_schema", None) or {}
        target = f"{function.__module__}:{function.__qualname__}"

        warnings: list[str] = []
        if "<locals>" in function.__qualname__:
            warnings.append(
                f"{name} is defined inside another scope; its target is not "
                "importable, so writers that resolve targets by path cannot "
                "reach it."
            )
        missing = [
            field
            for field, spec in schema.get("properties", {}).items()
            if not spec.get("description")
        ]
        if missing:
            warnings.append(
                f"{name} has no description for: {', '.join(missing)}. "
                "A model sees only the parameter names."
            )

        annotations: dict[str, Any] = {}
        if getattr(tool, "requires_approval", False):
            annotations["requires_approval"] = True

        return ScannedModule(
            module_id=module_id,
            description=tool.description or "",
            input_schema=schema,
            output_schema={},
            tags=list(self._tags),
            target=target,
            version=self._version,
            annotations=annotations or None,
            warnings=warnings,
        )


def register_toolset(
    toolset: FunctionToolset,
    registry: Registry,
    *,
    prefix: str = "",
    version: str = "1.0.0",
    tags: list[str] | None = None,
    enhancers: list[Enhancer] | None = None,
) -> ScanResult:
    """Register every eligible tool of ``toolset`` as an apcore module.

    Schemas are derived by apcore from each function's signature and docstring,
    the same way a hand-written module would be, so the resulting modules are
    not second-class. A tool's ``requires_approval`` flag carries over to the
    apcore annotation of the same name, which means the approval semantics
    survive the trip in both directions.

    Tools that take a ``RunContext`` are skipped: apcore invokes a module
    without one, and silently passing ``None`` would hand the function a broken
    context rather than fail honestly.

    Args:
        toolset: The pydantic-ai toolset to read tools from.
        registry: The apcore Registry to register into.
        prefix: Prepended to each tool name to form the module ID, e.g.
            ``"billing."`` turns ``send_invoice`` into ``billing.send_invoice``.
        version: Module version recorded for every registered module.
        tags: Optional tags applied to every registered module.
        enhancers: Metadata enhancers applied to the scan before registration,
            e.g. ``apcore_toolkit.AIEnhancer`` to fill in missing descriptions.
            Each tool's own gaps are listed in ``ScannedModule.warnings``.

    Returns:
        A :class:`ScanResult` naming what was registered, what was skipped, and
        the scanned modules themselves -- whose ``warnings`` flag metadata a
        model would find thin.
    """
    scanner = PydanticAIScanner(toolset, prefix=prefix, version=version, tags=tags)
    scanned = scanner.scan()

    for enhancer in enhancers or []:
        scanned = enhancer.enhance(scanned)

    registered: list[str] = []
    for scanned_module in scanned:
        function = scanner.callable_for(scanned_module.module_id)
        if function is None:  # pragma: no cover - only if an enhancer renames one
            continue

        module(
            id=scanned_module.module_id,
            description=scanned_module.description or None,
            documentation=scanned_module.documentation,
            annotations=_annotations_dict(scanned_module),
            tags=scanned_module.tags or None,
            version=scanned_module.version,
            registry=registry,
        )(function)
        registered.append(scanned_module.module_id)

    return ScanResult(
        registered=registered, skipped=scanner.skipped, modules=list(scanned)
    )


def _annotations_dict(scanned_module: ScannedModule) -> dict[str, Any] | None:
    """ScannedModule carries annotations as an object; apcore takes a dict."""
    annotations = scanned_module.annotations
    if annotations is None:
        return None
    if isinstance(annotations, dict):
        return annotations or None

    as_dict = {
        field: getattr(annotations, field)
        for field in ("readonly", "destructive", "idempotent", "requires_approval")
        if getattr(annotations, field, None)
    }
    return as_dict or None
