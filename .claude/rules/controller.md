---
paths:
  - "internal/ansible/controller/**"
---

# Controller Module Rules

- Reconcile loop must update status conditions on every exit path (Running, Failure, or Successful).
- Use `APIReader` (direct API reads, bypassing cache) for status updates to prevent stale writes.
- Controllers are named `<kind>-<version>-controller` (lowercased), registered via `controller.New`.
- Finalizer lifecycle: added on first reconcile if configured, removed only after a successful finalizer run on deletion.
- The reconciler requires a `playbook_on_stats` event somewhere in the event stream (recorded as seen, then verified after the stream closes); if missing, reconciliation fails.
- `SetCondition` is a no-op when Type/Status/Reason are unchanged, except `FailureConditionType` which always updates.
- Per-CR reconcile period override via annotation: `ansible.sdk.operatorframework.io/reconcile-period: <duration>`.
- Validate at package level: `go test ./internal/ansible/controller/ -short`, `go vet ./internal/ansible/controller/`.
