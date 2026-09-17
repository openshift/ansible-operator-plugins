# Add a Controller Reconcile Feature

## When to Use

When adding new behavior to the reconciliation loop, such as new status
conditions, event handling, or ansible-runner interaction patterns.

## Steps

1. **Identify the reconcile stage** where the feature belongs. The reconcile
   loop in `internal/ansible/controller/reconcile.go` follows this flow:
   - Read CR via `APIReader`
   - Check finalizer lifecycle
   - Start ansible-runner subprocess
   - Consume events from the event API
   - Update status conditions

2. **Implement the feature** in the appropriate file:
   - `reconcile.go` -- main reconcile logic
   - `status/` -- status condition management
   - `controller.go` -- controller setup and watches

3. **Add tests** alongside source in the same package:

```bash
go test ./internal/ansible/controller/ -run TestMyFeature -short
```

## Key Rules

- Reconcile loop MUST update status conditions on every exit path.
- Use `APIReader` for status updates to prevent stale writes from cached data.
- Three condition types: `Running`, `Failure`, `Successful` -- transition between them.
- Use `sync.RWMutex` for concurrent data structures; never `sync.Map`.
- Log messages: Error/Fatal/Info/Warn must begin with uppercase. Error messages
  (`errors.New`, `fmt.Errorf`) must begin with lowercase and not end with a period.
- Logging: use `logf.Log.WithName("...")`. V(0) for lifecycle, V(1) for events, V(2) for bodies.

## Reference Files

- Reconcile loop: `internal/ansible/controller/reconcile.go`
- Status management: `internal/ansible/controller/status/`
- Controller setup: `internal/ansible/controller/controller.go`

## Design Doc Enforcement

If this change affects reconcile flow, event handling, or component
boundaries, review and update the architecture doc in
`docs/architecture/components.md` in the same PR so the design stays
accurate for future agents.

## Validation

```bash
go vet ./internal/ansible/controller/
go test ./internal/ansible/controller/ -short
make verify
```
