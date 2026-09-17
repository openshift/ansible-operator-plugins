# Error Handling

## Reconciler Error Contract

The `Reconcile` method returns `(reconcile.Result, error)` to controller-runtime.

1. **Not-found on initial Get is not an error.** Return `(Result{}, nil)` when
   `apierrors.IsNotFound(err)` on the primary resource fetch.

2. **The return value is branch-specific, not one universal rule.** Which
   result/error pair is returned depends on where in `Reconcile` the error
   originates:

   | Branch | Returns |
   |---|---|
   | Initial `Client.Get` — not found | `reconcile.Result{}, nil` |
   | Initial `Client.Get` — other error | `reconcile.Result{}, err` |
   | Reconcile-period annotation parse, finalizer update, kubeconfig, or `Runner.Run` errors | `reconcileResult, err` (after attempting `markError`) |
   | `markRunning` failure (`ManageStatus=true`) | `reconcileResult, errmark` |
   | Event JSON marshal/unmarshal error | `reconcile.Result{}, err` (bypasses `reconcileResult`) |
   | Post-run `APIReader.Get` — not found | `reconcile.Result{}, nil` |
   | Post-run `APIReader.Get` — other error | `reconcile.Result{}, err` |
   | Missing `playbook_on_stats` event | `reconcileResult, errors.New("did not receive playbook_on_stats event")` |
   | `markDone` (`ManageStatus=true`), task failures present | `reconcileResult, errors.New("event runner on failed")` |
   | `markDone` (`ManageStatus=true`), success | `reconcileResult, errmark` (the status-update error, if any) |
   | `ManageStatus=false`, task failures present | `reconcileResult, errors.New("received failed task event")` |

   Only the branches that call `markError`/`markRunning`/`markDone` use the
   pre-computed `reconcileResult` (with `RequeueAfter`); the initial and
   post-run API reads intentionally return a bare `reconcile.Result{}`.

3. **Ansible run failures produce `errors.New` sentinel strings, not wrapped
   errors.** Two distinct messages:
   - `"event runner on failed"` (ManageStatus=true)
   - `"received failed task event"` (ManageStatus=false)

   These are intentionally flat strings. Do not change them to `fmt.Errorf` with `%w`.

4. **Missing `playbook_on_stats` is a reconciliation error.** If the event
   stream ends without a stats event, return
   `errors.New("did not receive playbook_on_stats event")`.

## Status Marking Pattern

Every reconciler error must attempt a corresponding status update before
returning. The pattern uses paired variables (`err` / `errmark`):

Rules:
- Always return the **original** error to controller-runtime, never the status-update error.
- Log the status-update error separately if it fails.
- `markError` calls `metrics.ReconcileFailed` immediately, so metrics are recorded even if the status update fails.
- In `markError` and `markDone`, treat `apierrors.IsNotFound` as a no-op (resource was deleted).
- **Exception:** `markRunning` does not follow the `err`/`errmark` pairing above.
  There is no separate "original" error to preserve at that point in the flow,
  so its own return value (`errmark`) is returned directly to controller-runtime
  on failure. Similarly, on the successful path through `markDone`
  (`ManageStatus=true`, no task failures), `errmark` is also returned directly
  since there is no prior error to prioritize over it.

## Metric Panic Recovery

`recoverMetricPanic()` uses `defer` to catch panics in Prometheus metric operations.
All exported metric functions (`ReconcileSucceeded`, `ReconcileFailed`,
`ReconcileTimer`) must use `defer recoverMetricPanic()` as their first statement.

## Error Wrapping

This codebase uses `%w` wrapping sparingly:
- `watches.go`: `fmt.Errorf("invalid GVK: %s: %w", gvk, err)`
- `internal/util/k8sutil/api.go`: wraps file I/O errors

When adding new errors:
- Use `%w` when the caller needs `errors.Is` or `errors.As`.
- Use `errors.New` or `%v` for human-readable messages that will only be logged.

## Kubernetes API Error Handling

Use the `apierrors` package for API server errors. The only type check in the
codebase is `apierrors.IsNotFound`. Use `runtime.IsNotRegisteredError` for
scheme registration checks.

## HTTP Handler Error Patterns

### Proxy Handlers

Two strategies depending on severity:

1. **Return an HTTP error and stop:** When failure would cause incorrect behavior
   (e.g., missing owner reference prevents garbage collection):
   ```go
   log.Error(err, m)
   http.Error(w, m, http.StatusInternalServerError)
   return
   ```

2. **Log and fall through to API server:** When the cache might not have data:
   ```go
   log.Error(err, "Cache miss, can not find in rest mapper")
   break  // falls through to c.next.ServeHTTP(w, req)
   ```

The `break` vs. `return` distinction is critical.

### Event API Handler

HTTP status codes: `404` (path not found), `405` (wrong method), `415` (wrong content type),
`400` (bad JSON), `410 Gone` (receiver stopped), `500` (read failure or channel timeout),
`204 No Content` (success).

### Metrics API Server

Metric validation errors return `400 Bad Request`. Use `log.Info(err.Error())`
(not `log.Error`) for client-caused errors.

## Runner Error Handling

- Missing `ansible-runner` binary: return `exec.LookPath` error directly.
- Async goroutine errors are logged but not returned (the `Run` method has already returned).
- `http.ErrServerClosed` from the event API is explicitly ignored as a clean shutdown signal.
- Use `errors.Is(err, os.ErrNotExist)` for artifact symlink checks.

## Status Condition Types

Three condition types track reconciliation state:
- `Running` -- set to True when reconciliation starts
- `Failure` -- set to True on error
- `Successful` -- set to True on successful completion

When one becomes True, the others are set to False.
