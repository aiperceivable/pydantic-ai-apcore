# pydantic-ai-apcore

[pydantic-ai](https://ai.pydantic.dev/) integration for [apcore](https://github.com/aiperceivable/apcore-python).

Works in both directions:

- **`ApcoreToolset`** — expose governed apcore modules to a pydantic-ai agent
- **`register_toolset()`** — register the tools an agent already has as apcore
  modules, so they gain schema validation, ACL, approval gates, and audit, and
  can then be served over MCP, CLI, or A2A without being rewritten

## Features

- **AbstractToolset implementation** — drop-in toolset for pydantic-ai agents
- **Schema passthrough** — apcore `input_schema` mapped directly to `ToolDefinition.parameters_json_schema`
- **Annotation mapping** — `destructive`, `requires_approval`, `readonly`, `idempotent`, `open_world`, `streaming` annotations surfaced as tool metadata and description warnings
- **Include/exclude filtering** — glob-style patterns to select which apcore modules to expose
- **Approval gating** — modules with `requires_approval=True` emit `kind="unapproved"` for pydantic-ai's human-in-the-loop flow
- **Per-call caller identity** — resolve the calling principal from the agent run context so apcore ACL rules can tell agents apart
- **Provider-safe tool names** — dotted module IDs are translated to names the major model providers accept
- **Reverse registration** — existing pydantic-ai tools become governed apcore modules, ready for MCP/CLI/A2A

## Requirements

- Python >= 3.10
- apcore >= 0.26.0
- apcore-toolkit >= 0.10.0
- pydantic-ai-slim >= 1.32.0

Both lower bounds are the earliest versions the test suite actually passes on,
not the earliest version that happens to expose the APIs used here:

| | Verified | Fails on | Why |
|---|---|---|---|
| apcore | 0.26.0 – 0.27.0 | 0.12.0 | the code itself works from 0.13.0, where `cacheable` / `paginated` arrive; the effective floor is raised to 0.26.0 by `apcore-toolkit` |
| apcore-toolkit | 0.6.0 – 0.10.1 | — | floor kept at 0.10.0 to match the other `*-apcore` integrations, so installing several together cannot conflict |
| pydantic-ai-slim | 1.32.0 – 2.33.0 | 1.31.0 | earlier releases pin an OpenTelemetry API that no longer resolves |

`ToolDefinition.sequential` needs 1.0.10 and `kind="unapproved"` needs 1.0.0, so
the pydantic-ai floor is set by installability rather than by API surface. The
2.x line is supported — no changes were required for it.

## Installation

```bash
pip install pydantic-ai-apcore

# Optionally project registered modules onto other surfaces
pip install "pydantic-ai-apcore[mcp]"   # serve them as an MCP server
pip install "pydantic-ai-apcore[cli]"   # expose them on the command line
pip install "pydantic-ai-apcore[all]"
```

## Quick Start

```python
from apcore import Registry, Executor, module
from pydantic_ai import Agent

from pydantic_ai_apcore import ApcoreToolset

# 1. Set up apcore registry and modules
registry = Registry()
executor = Executor(registry=registry)

@module(id="math.add", registry=registry)
def add(a: int, b: int) -> dict:
    """Add two numbers."""
    return {"result": a + b}

# 2. Create agent with ApcoreToolset
agent = Agent(
    "openai:gpt-4o",
    toolsets=[ApcoreToolset(registry, executor)],
)

# 3. Run
result = agent.run_sync("What is 3 + 5?")
print(result.output)
```

## API

### `ApcoreToolset`

```python
ApcoreToolset(
    registry: Registry,
    executor: Executor,
    *,
    identity: Identity | None = None,
    identity_resolver: Callable[[RunContext[AgentDepsT]], Identity | None] | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    toolset_id: str | None = None,
    max_retries: int = 1,
    sanitize_tool_names: bool = True,
)
```

| Parameter | Description |
|-----------|-------------|
| `registry` | apcore `Registry` containing discovered modules |
| `executor` | apcore `Executor` for running modules |
| `identity` | Fixed `Identity` used for every call — suitable when the whole agent runs as one principal |
| `identity_resolver` | Derives the `Identity` per call from the run context; takes precedence over `identity` |
| `include` | Glob-style patterns to include (e.g. `["api.*"]`) |
| `exclude` | Glob-style patterns to exclude (e.g. `["internal.*"]`) |
| `toolset_id` | Optional unique ID for this toolset instance |
| `max_retries` | Retries pydantic-ai allows per tool call |
| `sanitize_tool_names` | Translate dotted module IDs into provider-safe tool names |

### Caller identity and ACL

apcore matches ACL `callers` patterns against `Context.call_chain[-1]`, and
`conditions.roles` against the `Context` identity. This toolset writes the
resolved identity to **both**, so a rule like the following matches as written:

```python
ACLRule(
    callers=["agent.*"],
    targets=["crm.delete"],
    effect="allow",
    conditions={"roles": ["data_admin"]},
)
```

Use `identity_resolver` when one toolset serves several principals — typically
reading whatever the surrounding application already knows from `ctx.deps`:

```python
@dataclass
class AgentIdentity:
    caller_id: str
    roles: tuple[str, ...]

toolset = ApcoreToolset(
    registry, executor,
    identity_resolver=lambda ctx: Identity(
        id=ctx.deps.caller_id, type="ai", roles=ctx.deps.roles
    ),
)
```

With neither `identity` nor `identity_resolver`, calls reach apcore without a
caller, and a default-deny ACL will reject them.

### Tool naming

apcore module IDs are dotted by convention (`executor.crm.read`), but the major
model providers accept only `[a-zA-Z0-9_-]` in a tool name. Names are therefore
translated (`executor_crm_read`) before being offered to a model, and the
original module ID travels in `ToolDefinition.metadata["apcore_module_id"]` so
execution still targets the right module. Two IDs that translate to the same
name get a numeric suffix. Pass `sanitize_tool_names=False` to offer IDs
verbatim.

### Filtering

```python
# Only expose api.* modules, but not api.internal
toolset = ApcoreToolset(
    registry, executor,
    include=["api.*"],
    exclude=["api.internal"],
)
```

Exclude takes precedence over include.

### Annotation Handling

apcore `ModuleAnnotations` are mapped to pydantic-ai as follows:

| Annotation | Effect |
|------------|--------|
| `destructive=True` | Adds `WARNING: DESTRUCTIVE` to the description, and sets `sequential=True` so the call does not overlap with other tool calls |
| `requires_approval=True` | Sets `kind="unapproved"` + adds `REQUIRES APPROVAL` to description |
| `readonly`, `idempotent`, `open_world`, `streaming`, `cacheable`, `paginated` | Surfaced in `ToolDefinition.metadata` |
| `discoverable=False` | Excluded — `Registry.list()` omits these modules |

Other descriptor fields also reach the model: `documentation` and up to three
`examples` are appended to the description, and a `sunset_date` becomes a
`DEPRECATED` notice. `version` and `tags` travel in `metadata`.

### Registering existing tools

The reverse direction: take the tools an agent already has and put them behind
the apcore execution boundary.

```python
from apcore import Registry
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai_apcore import register_toolset

toolset = FunctionToolset()

@toolset.tool
def send_invoice(customer_id: str, amount: float) -> dict:
    """Send an invoice to a customer.

    Args:
        customer_id: Who to bill.
        amount: How much, in USD.
    """
    return {"customer_id": customer_id, "sent": True}

registry = Registry()
result = register_toolset(toolset, registry, prefix="billing.")
# result.registered -> ["billing.send_invoice"]
```

Schemas are derived by apcore from each function's signature and docstring, the
same way a hand-written module would be, so the results are not second-class. A
tool's `requires_approval` flag carries over to the apcore annotation of the
same name — approval semantics survive the trip in both directions.

Tools that take a `RunContext` are **skipped**, and reported in
`result.skipped` with the reason. apcore invokes a module without a pydantic-ai
run context, and passing `None` would hand the function a broken context rather
than fail honestly.

#### Metadata gaps get flagged

pydantic-ai does not require parameter descriptions
(`require_parameter_descriptions` defaults to `False`), so a tool can reach a
model with nothing but parameter names. Scanning produces
`apcore_toolkit.ScannedModule` values whose `warnings` say where that happened:

```python
for m in result.modules:
    for w in m.warnings:
        print(m.module_id, w)
# undocumented has no description for: x, y. A model sees only the parameter names.
```

Pass `enhancers=` to fill the gaps before registration — for instance
`apcore_toolkit.AIEnhancer`, which uses a local SLM and is off unless
`APCORE_AI_ENABLED` is set:

```python
from apcore_toolkit import AIEnhancer

register_toolset(toolset, registry, enhancers=[AIEnhancer()])
```

#### Closures register on equal footing

Registration deliberately does **not** go through `apcore_toolkit.RegistryWriter`.
That writer resolves a callable from `ScannedModule.target` by import path,
which cannot reach a tool defined inside a function — a common shape in
pydantic-ai, where tools close over dependencies. The callables are held from
the scan instead, so such tools register and execute normally; their
`target` is still recorded, with a warning that it is not importable.

Once registered, they are ordinary apcore modules — anything that serves a
registry can serve them:

```python
from pydantic_ai_apcore import serve_mcp   # needs the [mcp] extra

serve_mcp(registry)
```

`serve_mcp` / `serve_cli` are thin forwards to `apcore-mcp` and `apcore-cli`,
kept behind extras so the base install stays minimal. Calling one without its
extra installed raises an `ImportError` naming the command to fix it.

### Two approval checkpoints

`requires_approval` produces a tool the agent run suspends on, returning
`DeferredToolRequests`. That is pydantic-ai asking whether the model may make
the call at all. The apcore approval gate is separate and runs later, once the
sanctioned call reaches the execution pipeline — the two are in series, not
duplicated. See [`examples/governance_comparison.py`](examples/governance_comparison.py),
which demonstrates the ordering and runs offline without a model provider.

## Examples

Each demo is a self-contained directory with its own `README.md` and `acl.yaml`,
following the same layout as the other `*-apcore` integrations. All of them run
offline — `FunctionModel` drives the tool calls, so no model provider or API key
is involved.

| Demo | Shows |
|------|-------|
| [`acl_demo`](examples/acl_demo/) | ACL rules loaded from YAML via `APCORE_ACL_PATH`, and how `identity_resolver` gets the caller into the fields those rules match against. |
| [`approval_demo`](examples/approval_demo/) | The two approval checkpoints — pydantic-ai's and apcore's — and the order they fire in. |
| [`scanner_demo`](examples/scanner_demo/) | The reverse direction: existing agent tools registered as governed apcore modules, then denied by ACL and gated on approval. |

```bash
python examples/acl_demo/app.py
python examples/approval_demo/app.py
python examples/scanner_demo/app.py
```

Each demo's ACL lives in its own `acl.yaml`, so the policy can be changed and
re-run without touching code:

```yaml
default_effect: deny
rules:
  - description: Only data-admin agents may delete
    callers: ["agent.*"]      # matched against Context.call_chain[-1]
    targets: ["crm.delete"]   # module-id glob patterns
    effect: allow
    conditions:
      roles: ["data_admin"]
```

## Development

```bash
git clone https://github.com/aiperceivable/pydantic-ai-apcore.git
cd pydantic-ai-apcore
pip install -e ".[dev]"
pytest
```

## License

Apache-2.0
