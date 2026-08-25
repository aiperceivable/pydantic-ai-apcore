# pydantic-ai + apcore approval demo

A module annotated `requires_approval` is gated **twice**, by two different
systems, for two different reasons. This demo shows the ordering.

## What it demonstrates

- `requires_approval=True` on an apcore module becoming `kind="unapproved"` on
  the pydantic-ai `ToolDefinition` — no extra wiring, no MCP elicitation.
- The agent run suspending with `DeferredToolRequests` while the apcore
  approval gate has **not yet run**.
- The apcore gate firing only after a human approved, when the sanctioned call
  reaches the execution pipeline.

| Checkpoint | Asks | Runs when |
|------------|------|-----------|
| pydantic-ai | May the model make this call at all? | Before the call leaves the agent loop |
| apcore | Does policy allow this particular call? | When the call enters the Executor |

## Files

| File | Purpose |
|------|---------|
| `acl.yaml` | Deliberately permissive — an ACL denial would stop a call *before* the approval gate, which is the wrong thing to show here. |
| `app.py` | One plain module and one gated on approval, driven through a suspend/approve/resume cycle. |

## Run it

```bash
python examples/approval_demo/app.py
```

```
Two checkpoints, in order
  1. agent run suspended         : DeferredToolRequests
     apcore approval gate calls  : 0
  2. after the human approved    : 1 gate call(s)
     result                      : ToolReturnPart: {'record_id': 'C-9', 'deleted': True}
```

The `0` is the point: while the run is suspended, apcore has not been consulted
yet. Defence in depth, not a duplicated prompt.

## How the pieces connect

```
model wants to call crm.delete
  └─ tool_def.kind == 'unapproved'
       └─ agent run suspends -> DeferredToolRequests    ← checkpoint 1
            └─ human approves -> DeferredToolResults
                 └─ ApcoreToolset.call_tool -> Executor
                      ├─ ACL check                       ← runs first; see acl_demo
                      └─ apcore approval gate            ← checkpoint 2
                           └─ module runs
```

Note the ACL runs **before** either gate. A module the ACL rejects never reaches
an approval decision at all — so a tool has to pass the ACL first for its
`requires_approval` annotation to matter.

## Test

The end-to-end behaviour is covered by [`tests/test_approval_demo.py`](../../tests/test_approval_demo.py).

```bash
pytest tests/test_approval_demo.py
```

## Related demos

| Demo | Shows |
|------|-------|
| [`acl_demo`](../acl_demo/) | ACL rules from YAML, and how the caller identity reaches them. |
| [`scanner_demo`](../scanner_demo/) | `requires_approval` surviving the reverse trip, from a pydantic-ai tool into an apcore annotation. |
