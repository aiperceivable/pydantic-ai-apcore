# pydantic-ai + apcore ACL demo

Shows how a pydantic-ai agent's tool calls are governed by an **apcore Access
Control List** loaded from YAML, with the calling agent's identity resolved per
run.

## What it demonstrates

- Loading an ACL from YAML via `APCORE_ACL_PATH` and `ACL.load()`.
- Mapping an agent run's dependencies (`ctx.deps`) to an apcore
  `Identity(roles=...)` through `ApcoreToolset(identity_resolver=...)`.
- Role-based `allow`/`deny` enforced by the Executor before a module runs, with
  denied calls surfacing as `ACLDeniedError`.
- Why the resolved identity has to reach **both** `Context.identity` and
  `Context.call_chain`: the ACL matches `conditions.roles` against the first and
  `callers` against the second.

## Files

| File | Purpose |
|------|---------|
| `acl.yaml` | ACL rules: any `agent.*` may read; only `data_admin` agents may delete; everything else is denied by `default_effect: deny`. |
| `app.py` | Two ACL-protected modules (`crm.read`, `crm.delete`) reached through an agent, with two identities to compare. |

## Run it

```bash
python examples/acl_demo/app.py
```

Runs offline — `FunctionModel` drives the tool calls, so no model provider or
API key is involved.

```
  reader reads    (agent.research, roles=['reader'])
      -> {'record_id': 'C-7', 'tier': 'gold'}
  admin reads     (agent.ops, roles=['data_admin'])
      -> {'record_id': 'C-7', 'tier': 'gold'}
  reader deletes  (agent.research, roles=['reader'])
      -> ACLDeniedError: [ACL_DENIED] Access denied: agent.research -> crm.delete
  admin deletes   (agent.ops, roles=['data_admin'])
      -> {'record_id': 'C-7', 'deleted': True}
```

Both identities read fine; only the `data_admin` one deletes. Edit `acl.yaml`
and re-run — no code changes.

## How the pieces connect

```
agent run (deps = AgentIdentity)
  └─ ApcoreToolset.call_tool
       └─ identity_resolver(ctx) -> Identity(id, roles)
            └─ Context.identity   = Identity        (matched by conditions.roles)
               Context.call_chain = [identity.id]   (matched by callers)
                 └─ Executor checks ACL (first-match-wins)
                      ├─ allow → module runs
                      └─ deny  → ACLDeniedError
```

The ACL guards **apcore module calls** (the Executor), not the agent loop — so
the same rules apply whether a module is invoked from a pydantic-ai agent (as
here), from an MCP client via `serve_mcp()`, or from the generated CLI.

Without an identity — no `identity=` and no `identity_resolver=` — calls arrive
with an empty `call_chain`, every `callers` pattern misses, and a default-deny
ACL rejects everything.

## ACL rule format

```yaml
default_effect: deny          # fallback when no rule matches
rules:
  - description: Only data-admin agents may delete
    callers: ["agent.*"]      # matched against Context.call_chain[-1]
    targets: ["crm.delete"]   # module-id glob patterns
    effect: allow             # allow | deny
    conditions:               # optional: roles | identity_types | max_call_depth
      roles: ["data_admin"]
```

See [Caller identity and ACL](../../README.md#caller-identity-and-acl) for how
`identity_resolver` populates the two fields these rules match against.

## Test

The end-to-end behaviour is covered by [`tests/test_acl_demo.py`](../../tests/test_acl_demo.py).

```bash
pytest tests/test_acl_demo.py
```

## Related demos

| Demo | Shows |
|------|-------|
| [`approval_demo`](../approval_demo/) | The two approval checkpoints — pydantic-ai's and apcore's — and the order they fire in. |
| [`scanner_demo`](../scanner_demo/) | The reverse direction: existing agent tools registered as governed apcore modules. |
