# pydantic-ai-apcore

[pydantic-ai](https://ai.pydantic.dev/) integration for [apcore](https://github.com/aipartnerup/apcore-python) — expose apcore modules as pydantic-ai tools via the `AbstractToolset` interface.

## Features

- **AbstractToolset implementation** — drop-in toolset for pydantic-ai agents
- **Schema passthrough** — apcore `input_schema` mapped directly to `ToolDefinition.parameters_json_schema`
- **Annotation mapping** — `destructive`, `requires_approval`, `readonly`, `idempotent`, `open_world`, `streaming` annotations surfaced as tool metadata and description warnings
- **Include/exclude filtering** — glob-style patterns to select which apcore modules to expose
- **Approval gating** — modules with `requires_approval=True` emit `kind="unapproved"` for pydantic-ai's human-in-the-loop flow

## Requirements

- Python >= 3.10
- apcore >= 0.7.0
- pydantic-ai-slim >= 0.2.0

## Installation

```bash
pip install pydantic-ai-apcore
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
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    toolset_id: str | None = None,
)
```

| Parameter | Description |
|-----------|-------------|
| `registry` | apcore `Registry` containing discovered modules |
| `executor` | apcore `Executor` for running modules |
| `identity` | Optional `Identity` for ACL checks during execution |
| `include` | Glob-style patterns to include (e.g. `["api.*"]`) |
| `exclude` | Glob-style patterns to exclude (e.g. `["internal.*"]`) |
| `toolset_id` | Optional unique ID for this toolset instance |

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
| `destructive=True` | Adds `WARNING: DESTRUCTIVE` to tool description |
| `requires_approval=True` | Sets `kind="unapproved"` + adds `REQUIRES APPROVAL` to description |
| `readonly`, `idempotent`, `open_world`, `streaming` | Surfaced in `ToolDefinition.metadata` dict |

## Development

```bash
git clone https://github.com/aipartnerup/pydantic-ai-apcore.git
cd pydantic-ai-apcore
pip install -e ".[dev]"
pytest
```

## License

Apache-2.0
