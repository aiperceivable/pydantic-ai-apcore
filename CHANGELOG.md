# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(nothing yet)

---

## [0.1.0] - 2026-08-25

Initial release. pydantic-ai integration for the apcore ecosystem, built
against apcore 0.26.0, apcore-toolkit 0.10.0, and pydantic-ai-slim 1.32.0.
All 53 tests pass.

The integration works in both directions: governed apcore modules become
agent tools, and the tools an agent already has become governed apcore
modules.

### Added

- **`ApcoreToolset`** — an `AbstractToolset` implementation that exposes
  registered apcore modules to a pydantic-ai agent, enforcing governance on
  every call. Module `input_schema` is passed through directly to
  `ToolDefinition.parameters_json_schema` rather than being re-derived, so the
  schema the registry validates against is the schema the model sees.

- **Annotation mapping** — apcore's `destructive`, `requires_approval`,
  `readonly`, `idempotent`, `open_world`, and `streaming` annotations are
  surfaced as pydantic-ai tool metadata and as warnings in the tool
  description, so the model is told what a call will do before it makes one.

- **Approval gating** — modules marked `requires_approval=True` emit
  `kind="unapproved"`, driving pydantic-ai's human-in-the-loop flow instead of
  executing. Demonstrated end-to-end in `examples/approval_demo/` and covered
  by `tests/test_approval_demo.py`.

- **Include/exclude filtering** — glob-style patterns select which apcore
  modules a given toolset exposes, so one registry can back several agents
  with different reach.

- **Per-call caller identity** — the calling principal is resolved from the
  agent run context and passed into apcore, so ACL rules can distinguish one
  agent from another rather than seeing every call as the same caller.
  Demonstrated in `examples/acl_demo/`, covered by `tests/test_acl_demo.py`.

- **Provider-safe tool names** — dotted apcore module IDs (`math.add`) are
  translated to names every major model provider accepts, and translated back
  on dispatch.

- **`register_toolset()` / `PydanticAIScanner`** — the reverse direction: scan
  the tools an agent already has and register them as apcore modules, so they
  gain schema validation, ACL, approval gates, and audit without being
  rewritten. Returns a `ScanResult` carrying the registered modules and a list
  of `SkippedTool` entries explaining, per tool, why it could not be
  registered. Covered by `tests/test_scanner_demo.py`.

- **`serve_mcp()` / `serve_cli()`** — surface helpers that project the
  registered modules onto other transports once they are governed: an MCP
  server (`pydantic-ai-apcore[mcp]`, apcore-mcp >= 0.17.2) or a command-line
  interface (`pydantic-ai-apcore[cli]`, apcore-cli >= 0.10.3). Both are
  optional extras; neither is needed for agent-side use.

### Notes on dependency floors

Each lower bound is the earliest version the test suite actually passes on,
not the earliest version that happens to expose the APIs used here:

- `apcore >= 0.26.0` — the code itself works from 0.13.0 (where `cacheable` /
  `paginated` arrive); the effective floor is raised to 0.26.0 by
  `apcore-toolkit`. Verified on 0.26.0 – 0.27.0.
- `apcore-toolkit >= 0.10.0` — the floor is kept at 0.10.0 to match the other
  `*-apcore` integrations, so installing several together cannot conflict.
  Verified on 0.6.0 – 0.10.1.
- `pydantic-ai-slim >= 1.32.0` — set by installability, not by API surface:
  `kind="unapproved"` needs 1.0.0 and `ToolDefinition.sequential` needs
  1.0.10, but releases before 1.32.0 pin an OpenTelemetry API that no longer
  resolves. Both major lines are verified — the suite passes on 1.32.0,
  1.66.0, 2.0.0, and 2.34.0.

