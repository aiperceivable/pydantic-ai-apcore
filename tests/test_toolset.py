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
from pydantic_ai import RunContext
from pydantic_ai.toolsets.function import FunctionToolset


def _make_descriptor(
    module_id: str = "test.module",
    description: str = "A test module",
    annotations: ModuleAnnotations | None = None,
    input_schema: dict[str, Any] | None = None,
    sunset_date: str | None = None,
) -> ModuleDescriptor:
    return ModuleDescriptor(
        module_id=module_id,
        name=module_id,
        description=description,
        documentation=None,
        input_schema=input_schema or {"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        annotations=annotations,
        sunset_date=sunset_date,
    )


class TestDescriptorToToolDef:
    """Test _descriptor_to_tool_def conversion."""

    def test_basic_conversion(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        desc = _make_descriptor()
        tool_def = _descriptor_to_tool_def(desc, desc.module_id.replace(".", "_"))

        assert tool_def.name == "test_module"
        assert tool_def.description == "A test module"
        assert tool_def.kind == "function"
        # Metadata always carries the originating module ID so call_tool can
        # recover it without a lookup table.
        assert tool_def.metadata is not None
        assert tool_def.metadata["apcore_module_id"] == "test.module"

    def test_destructive_annotation_adds_warning(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        desc = _make_descriptor(
            annotations=ModuleAnnotations(destructive=True),
        )
        tool_def = _descriptor_to_tool_def(desc, desc.module_id.replace(".", "_"))

        assert "DESTRUCTIVE" in tool_def.description
        assert tool_def.metadata is not None
        assert tool_def.metadata["destructive"] is True

    def test_requires_approval_sets_unapproved_kind(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        desc = _make_descriptor(
            annotations=ModuleAnnotations(requires_approval=True),
        )
        tool_def = _descriptor_to_tool_def(desc, desc.module_id.replace(".", "_"))

        assert tool_def.kind == "unapproved"
        assert "REQUIRES APPROVAL" in tool_def.description

    def test_readonly_annotation_metadata(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        desc = _make_descriptor(
            annotations=ModuleAnnotations(readonly=True, idempotent=True),
        )
        tool_def = _descriptor_to_tool_def(desc, desc.module_id.replace(".", "_"))

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
        tool_def = _descriptor_to_tool_def(desc, desc.module_id.replace(".", "_"))

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
            registry,
            executor,
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

        assert "math_add" in tools
        tool = tools["math_add"]
        assert tool.tool_def.name == "math_add"
        assert "Add two numbers" in (tool.tool_def.description or "")

    @pytest.mark.asyncio
    async def test_call_tool_executes_module(self) -> None:
        from pydantic_ai_apcore.toolset import ApcoreToolset

        registry, executor = self._setup_registry()
        ts = ApcoreToolset(registry, executor)

        ctx = MagicMock()
        tools = await ts.get_tools(ctx)
        tool = tools["math_add"]

        result = await ts.call_tool("math_add", {"a": 3, "b": 5}, ctx, tool)
        assert result == {"result": 8}


class _CapturingExecutor:
    """Stand-in Executor that records the Context each call was given."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], Context]] = []

    async def call_async(self, module_id: str, inputs: dict[str, Any], context: Context) -> dict[str, Any]:
        self.calls.append((module_id, inputs, context))
        return {"ok": True}


def _toolset_with_capture(**kwargs: Any) -> tuple[Any, _CapturingExecutor]:
    from pydantic_ai_apcore.toolset import ApcoreToolset

    registry = Registry()

    @module(id="crm.delete", registry=registry)
    def crm_delete(record_id: str) -> dict:
        """Delete a record.

        Args:
            record_id: Record to delete.
        """
        return {"deleted": record_id}

    executor = _CapturingExecutor()
    return ApcoreToolset(registry, executor, **kwargs), executor


async def _call_once(toolset: Any, ctx: Any) -> None:
    tools = await toolset.get_tools(ctx)
    name = next(iter(tools))
    await toolset.call_tool(name, {"record_id": "C-1"}, ctx, tools[name])


class TestIdentityResolution:
    """Identity has to reach both Context.identity and Context.call_chain."""

    @pytest.mark.asyncio
    async def test_static_identity_populates_call_chain(self) -> None:
        identity = Identity(id="agent.ops", type="ai", roles=("data_admin",))
        ts, executor = _toolset_with_capture(identity=identity)

        await _call_once(ts, MagicMock())

        _, _, context = executor.calls[0]
        assert context.identity == identity
        # ACL matches `callers` against call_chain[-1]; leaving it empty makes
        # every caller-keyed rule miss.
        assert context.call_chain == ["agent.ops"]

    @pytest.mark.asyncio
    async def test_resolver_takes_precedence_over_static_identity(self) -> None:
        static = Identity(id="fallback", type="ai")
        resolved = Identity(id="agent.research", type="ai", roles=("reader",))
        ts, executor = _toolset_with_capture(identity=static, identity_resolver=lambda ctx: resolved)

        await _call_once(ts, MagicMock())

        _, _, context = executor.calls[0]
        assert context.identity == resolved
        assert context.call_chain == ["agent.research"]

    @pytest.mark.asyncio
    async def test_resolver_returning_none_falls_back_to_static(self) -> None:
        static = Identity(id="fallback", type="ai")
        ts, executor = _toolset_with_capture(identity=static, identity_resolver=lambda ctx: None)

        await _call_once(ts, MagicMock())

        _, _, context = executor.calls[0]
        assert context.identity == static
        assert context.call_chain == ["fallback"]

    @pytest.mark.asyncio
    async def test_resolver_reads_run_context_deps(self) -> None:
        ts, executor = _toolset_with_capture(identity_resolver=lambda ctx: Identity(id=ctx.deps.caller, type="ai"))

        ctx = MagicMock()
        ctx.deps.caller = "agent.from_deps"
        await _call_once(ts, ctx)

        _, _, context = executor.calls[0]
        assert context.call_chain == ["agent.from_deps"]

    @pytest.mark.asyncio
    async def test_no_identity_leaves_call_chain_empty(self) -> None:
        ts, executor = _toolset_with_capture()

        await _call_once(ts, MagicMock())

        _, _, context = executor.calls[0]
        assert context.identity is None
        assert not context.call_chain


class TestToolNameSanitization:
    """Dotted module IDs are not valid tool names at the major providers."""

    @pytest.mark.asyncio
    async def test_dots_become_underscores(self) -> None:
        ts, _ = _toolset_with_capture()

        tools = await ts.get_tools(MagicMock())

        assert "crm_delete" in tools
        assert "crm.delete" not in tools

    @pytest.mark.asyncio
    async def test_call_tool_recovers_original_module_id(self) -> None:
        ts, executor = _toolset_with_capture()

        await _call_once(ts, MagicMock())

        module_id, _, _ = executor.calls[0]
        assert module_id == "crm.delete"

    @pytest.mark.asyncio
    async def test_sanitization_can_be_disabled(self) -> None:
        ts, _ = _toolset_with_capture(sanitize_tool_names=False)

        tools = await ts.get_tools(MagicMock())

        assert "crm.delete" in tools

    def test_collisions_get_a_suffix(self) -> None:
        from pydantic_ai_apcore.toolset import ApcoreToolset

        ts = ApcoreToolset(Registry(), MagicMock())
        taken: dict[str, Any] = {}

        first = ts._tool_name("a.b", taken)
        taken[first] = object()
        second = ts._tool_name("a_b", taken)

        assert first == "a_b"
        assert second == "a_b_2"


class TestGovernanceMapping:
    """Annotations that change how a caller should treat the tool."""

    def test_sunset_date_is_surfaced_to_the_model(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        desc = _make_descriptor(sunset_date="2026-12-31")
        tool_def = _descriptor_to_tool_def(desc, "test_module")

        assert "DEPRECATED" in (tool_def.description or "")
        assert "2026-12-31" in (tool_def.description or "")

    def test_destructive_marks_the_tool_sequential(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        desc = _make_descriptor(annotations=ModuleAnnotations(destructive=True))
        tool_def = _descriptor_to_tool_def(desc, "test_module")

        # A destructive call should not overlap with other tool calls.
        assert tool_def.sequential is True

    def test_non_destructive_is_not_sequential(self) -> None:
        from pydantic_ai_apcore.toolset import _descriptor_to_tool_def

        desc = _make_descriptor(annotations=ModuleAnnotations(readonly=True))
        tool_def = _descriptor_to_tool_def(desc, "test_module")

        assert tool_def.sequential is False


class TestRegisterToolset:
    """Registering existing pydantic-ai tools as governed apcore modules."""

    def _toolset(self) -> Any:
        ts = FunctionToolset()

        def send_invoice(customer_id: str, amount: float) -> dict:
            """Send an invoice to a customer.

            Args:
                customer_id: Who to bill.
                amount: How much, in USD.
            """
            return {"customer_id": customer_id, "sent": True}

        def refund(payment_id: str) -> dict:
            """Refund a payment.

            Args:
                payment_id: Payment to refund.
            """
            return {"payment_id": payment_id, "refunded": True}

        def needs_ctx(ctx: RunContext, query: str) -> str:
            """Needs the run context.

            Args:
                query: Anything.
            """
            return query

        # add_function(takes_ctx=...) behaves the same on pydantic-ai 1.x and
        # 2.x; the .tool decorator does not (2.0 made it require RunContext).
        ts.add_function(send_invoice, takes_ctx=False)
        ts.add_function(refund, takes_ctx=False, requires_approval=True)
        ts.add_function(needs_ctx, takes_ctx=True)
        return ts

    def test_registers_plain_tools(self) -> None:
        from pydantic_ai_apcore import register_toolset

        registry = Registry()
        result = register_toolset(self._toolset(), registry)

        assert "send_invoice" in result.registered
        assert "refund" in result.registered

    def test_prefix_forms_the_module_id(self) -> None:
        from pydantic_ai_apcore import register_toolset

        registry = Registry()
        result = register_toolset(self._toolset(), registry, prefix="billing.")

        assert "billing.send_invoice" in result.registered
        assert registry.get_definition("billing.send_invoice") is not None

    def test_context_taking_tools_are_skipped_not_broken(self) -> None:
        from pydantic_ai_apcore import register_toolset

        registry = Registry()
        result = register_toolset(self._toolset(), registry)

        skipped = {s.name: s.reason for s in result.skipped}
        assert "needs_ctx" in skipped
        assert "RunContext" in skipped["needs_ctx"]
        assert "needs_ctx" not in result.registered

    def test_schema_is_derived_from_signature_and_docstring(self) -> None:
        from pydantic_ai_apcore import register_toolset

        registry = Registry()
        register_toolset(self._toolset(), registry)

        schema = registry.get_definition("send_invoice").input_schema
        assert set(schema["required"]) == {"customer_id", "amount"}
        assert schema["properties"]["amount"]["description"] == "How much, in USD."

    def test_requires_approval_survives_the_round_trip(self) -> None:
        from pydantic_ai_apcore import register_toolset

        registry = Registry()
        register_toolset(self._toolset(), registry)

        assert registry.get_definition("refund").annotations.requires_approval is True

    def test_registered_tools_are_subject_to_acl(self) -> None:
        from apcore import ACL, ACLDeniedError, ACLRule

        from pydantic_ai_apcore import register_toolset

        registry = Registry()
        register_toolset(self._toolset(), registry, prefix="billing.")
        executor = Executor(registry=registry)
        executor.set_acl(
            ACL(
                rules=[
                    ACLRule(
                        callers=["agent.*"],
                        targets=["billing.send_invoice"],
                        effect="allow",
                    )
                ],
                default_effect="deny",
            )
        )

        def call(target: str, args: dict[str, Any]) -> Any:
            ctx = Context.create(identity=Identity(id="agent.ops", type="ai"))
            ctx.call_chain = ["agent.ops"]
            return executor.call(target, args, context=ctx)

        assert call("billing.send_invoice", {"customer_id": "C-1", "amount": 1.0})

        # A plain Python function became a governed module: the ACL now applies
        # to it exactly as it would to a hand-written one.
        with pytest.raises(ACLDeniedError):
            call("billing.refund", {"payment_id": "P-1"})


class TestSurfaceHelpers:
    """Optional forwarding to the other apcore surfaces."""

    def test_missing_extra_names_the_install_command(self, monkeypatch) -> None:
        import builtins

        from pydantic_ai_apcore import surfaces

        real_import = builtins.__import__

        def blocked(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "apcore_mcp":
                raise ImportError("No module named 'apcore_mcp'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)

        with pytest.raises(ImportError) as exc:
            surfaces.serve_mcp(object())

        assert "pydantic-ai-apcore[mcp]" in str(exc.value)


class TestScannerMetadataPipeline:
    """Scanning produces ScannedModule, so the toolkit pipeline applies."""

    def _closure_toolset(self, rate: float) -> Any:
        """Tools defined inside a scope, closing over a dependency."""
        ts = FunctionToolset()

        def convert(amount: float) -> dict:
            """Convert an amount.

            Args:
                amount: Value to convert.
            """
            return {"converted": amount * rate}

        def undocumented(x: str, y: int) -> dict:
            return {"x": x}

        ts.add_function(convert, takes_ctx=False)
        ts.add_function(undocumented, takes_ctx=False)
        return ts

    def test_scan_yields_scanned_modules(self) -> None:
        from apcore_toolkit import ScannedModule

        from pydantic_ai_apcore import register_toolset

        result = register_toolset(self._closure_toolset(1.5), Registry())

        assert result.modules
        assert all(isinstance(m, ScannedModule) for m in result.modules)

    def test_missing_parameter_descriptions_are_flagged(self) -> None:
        from pydantic_ai_apcore import register_toolset

        result = register_toolset(self._closure_toolset(1.5), Registry())

        warnings = {m.module_id: m.warnings for m in result.modules}
        gaps = [w for w in warnings["undocumented"] if "no description for" in w]
        # pydantic-ai does not require parameter descriptions, so an
        # undocumented tool reaches a model with only parameter names.
        assert gaps and "x" in gaps[0] and "y" in gaps[0]

    def test_unimportable_target_is_flagged_but_still_registered(self) -> None:
        from pydantic_ai_apcore import register_toolset

        registry = Registry()
        result = register_toolset(self._closure_toolset(1.5), registry, prefix="fx.")

        module = next(m for m in result.modules if m.module_id == "fx.convert")
        assert "<locals>" in module.target
        assert any("not importable" in w for w in module.warnings)
        # RegistryWriter would fail to resolve this target; holding the callable
        # from the scan lets closures register on equal footing.
        assert "fx.convert" in result.registered

    def test_closure_tool_actually_executes(self) -> None:
        from pydantic_ai_apcore import register_toolset

        registry = Registry()
        register_toolset(self._closure_toolset(1.5), registry, prefix="fx.")
        executor = Executor(registry=registry)

        ctx = Context.create(identity=Identity(id="agent.ops", type="ai"))
        result = executor.call("fx.convert", {"amount": 10.0}, context=ctx)

        assert result == {"converted": 15.0}

    def test_enhancers_run_before_registration(self) -> None:
        from pydantic_ai_apcore import register_toolset

        class FillDescription:
            def enhance(self, modules: list[Any]) -> list[Any]:
                for m in modules:
                    if not m.description:
                        m.description = "Filled by enhancer"
                return modules

        registry = Registry()
        register_toolset(self._closure_toolset(1.5), registry, enhancers=[FillDescription()])

        assert registry.get_definition("undocumented").description == ("Filled by enhancer")

    def test_scanner_reports_its_source(self) -> None:
        from pydantic_ai_apcore import PydanticAIScanner

        scanner = PydanticAIScanner(self._closure_toolset(1.0))

        assert scanner.get_source_name() == "pydantic-ai"
