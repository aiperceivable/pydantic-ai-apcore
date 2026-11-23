# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(nothing yet)

---

## [0.2.0] - 2026-11-23

Reverse registration now preserves per-tool execution budgets. All 62 tests
pass.

### Added

- **`register_toolset(resources=...)`** accepts per-tool apcore `resources`
  blocks keyed by tool name or fully-prefixed module ID. The full module ID is
  matched first, and the explicit block is merged over any derived value.
  Entries that match no registered tool emit a warning instead of being
  silently ignored.
- **A pydantic-ai tool's `timeout` (seconds) is translated automatically** to
  apcore's millisecond `resources["timeout"]` when the tool is reverse
  registered. A `ToolDefinition`/`Tool` timeout of `2.5`, for example, becomes
  `{"timeout": 2500}`, so the governed module cannot outlive the budget the
  agent already declared. The lookup uses `getattr`, so pydantic-ai releases
  without the field remain compatible.

### Notes

- Tool callables and schemas are unchanged; this only affects the resources
  passed to `apcore.module()`.

---

## [0.1.2] - 2026-11-23

Dependency uplift to the aligned apcore 0.33.0 / apcore-toolkit 0.15.0 /
apcore-mcp 0.23.4 / apcore-cli 0.14.1 train. All 57 tests pass.

### Changed

- **Dependency floors raised** — `apcore >= 0.33.0` (was `>= 0.32.2`),
  `apcore-toolkit >= 0.15.0` (was `>= 0.14.1`), `apcore-mcp >= 0.23.4`
  (the `mcp` extra, was `>= 0.23.3`), and `apcore-cli >= 0.14.1`
  (the `cli` extra, was `>= 0.12.6`).
- The CI `minimum-versions` job now pins the same floors instead of the
  previous 0.32.2 / 0.14.1 / 0.23.3 / 0.12.6 set, and the README dependency
  table is updated to match.

### Notes

- No code change was required for apcore 0.33.0's `resources` block and
  `MODULE_TIMEOUT` retryability change, or for apcore-toolkit 0.15.0's opt-in
  effective-parameter OpenAPI scanning: this integration uses registry and
  executor surfaces whose signatures are unchanged.

---

## [0.1.1] - 2026-11-03

Dependency uplift to the aligned apcore 0.32.2 / apcore-toolkit 0.14.1 /
apcore-mcp 0.23.3 / apcore-cli 0.12.6 train. All 57 tests pass.

### Changed

- **Dependency floors raised** — `apcore >= 0.32.2`,
  `apcore-toolkit >= 0.14.1`, `apcore-mcp >= 0.23.3` (the `mcp` extra), and
  `apcore-cli >= 0.12.6` (the `cli` extra). These match the versions the other
  `*-apcore` integrations declare for the same release train, so installing
  several together cannot conflict.

### Fixed

- **`serve_cli()` now builds its CLI through `apcore_cli.create_cli()`.** It
  previously looked for a top-level `main` / `run` / `serve` / `cli` entry
  point on `apcore_cli`; none exists (the `cli` attribute is the *module*
  `apcore_cli.cli`, not a callable), so the helper raised `RuntimeError` on
  every call. It now passes the registry — and the executor, when one is given
  — to `create_cli()` and invokes the resulting Click group, mirroring how
  `apcore-cli`'s own entry point runs. A filesystem path is accepted too and
  forwarded as `extensions_dir`.

### Notes on dependency floors

`apcore` 0.32 added canonical name helpers, governance projection, and the
`discoverable` / `extra` annotations; `apcore-toolkit` 0.14 tightened binding
validation; `apcore-mcp` 0.23 isolated stdio diagnostics. None of these change
the APIs this integration consumes — the suite passes against the new floors
with no further source changes beyond the `serve_cli()` fix above.
`apcore-a2a` 0.8.5 is not a dependency of this package (A2A is served by
`apcore-a2a` directly), so that release required no change here.

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
