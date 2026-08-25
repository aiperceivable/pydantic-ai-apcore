# pydantic-ai + apcore scanner demo

The reverse direction: take the tools an agent **already has** and register them
as governed apcore modules, so they gain ACL and approval semantics and can be
served on other surfaces without being rewritten.

## What it demonstrates

- `register_toolset()` turning plain pydantic-ai tools into apcore modules, with
  schemas derived from each function's signature and docstring.
- `requires_approval` carrying over to the apcore annotation of the same name —
  approval semantics survive the trip in both directions.
- Tools that take a `RunContext` being **skipped** with a reason, rather than
  registered with a broken context.
- `ScannedModule.warnings` flagging metadata a model would find thin, because
  pydantic-ai does not require parameter descriptions.
- Closures registering on equal footing, even though their target is not
  importable.

## Files

| File | Purpose |
|------|---------|
| `acl.yaml` | Rules targeting modules that began life as ordinary tools; `billing.wire_transfer` is deliberately absent, so `default_effect: deny` catches it. |
| `app.py` | Five tools defined inside a scope — one gated on approval, one taking a `RunContext`, one undocumented — registered and then called under governance. |

## Run it

```bash
python examples/scanner_demo/app.py
```

```
Registered
  billing.send_invoice
  billing.refund
  billing.wire_transfer
  billing.lookup
  skipped recent_activity: takes a RunContext, which apcore cannot supply

What the scan flagged
  4 tools are defined inside another scope, so their
  targets are not importable. They still register and execute here.
  billing.lookup: lookup has no description for: q, limit. ...

Governance now applies to what were plain functions
  allowed by ACL    : {'customer_id': 'C-7', 'amount': 42.0, 'currency': 'USD'}
  blocked by ACL    : ACLDeniedError: [ACL_DENIED] Access denied: agent.ops -> billing.wire_transfer
  approval refused  : ApprovalDeniedError: caller did not confirm the reversal
  approval granted  : {'payment_id': 'P-1', 'refunded': True, 'currency': 'USD'}
```

`currency` in that output comes from the enclosing scope, so the closure is
genuinely being executed rather than re-imported. `refund` goes through the
approval gate — an annotation it inherited from the pydantic-ai tool.

## How the pieces connect

```
FunctionToolset (tools defined in a scope)
  └─ PydanticAIScanner.scan() -> [ScannedModule]
       ├─ takes RunContext?  -> skipped, with a reason
       ├─ warnings: missing descriptions, unimportable target
       └─ enhancers (e.g. AIEnhancer) fill metadata gaps
            └─ registered into the apcore Registry
                 └─ Executor: ACL -> approval gate -> module runs
                      └─ also reachable via serve_mcp() / serve_cli()
```

Registration deliberately does **not** go through
`apcore_toolkit.RegistryWriter`: that resolves a callable from
`ScannedModule.target` by import path, which cannot reach a tool defined inside
a function. The callables are held from the scan instead.

## Filling metadata gaps

```python
from apcore_toolkit import AIEnhancer

register_toolset(toolset, registry, enhancers=[AIEnhancer()])
```

`AIEnhancer` uses a local SLM and is off unless `APCORE_AI_ENABLED` is set.

## Test

The end-to-end behaviour is covered by [`tests/test_scanner_demo.py`](../../tests/test_scanner_demo.py).

```bash
pytest tests/test_scanner_demo.py
```

## Related demos

| Demo | Shows |
|------|-------|
| [`acl_demo`](../acl_demo/) | The forward direction — apcore modules exposed to an agent, governed by the same kind of `acl.yaml`. |
| [`approval_demo`](../approval_demo/) | The two approval checkpoints and the order they fire in. |
