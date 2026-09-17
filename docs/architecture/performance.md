# Performance

Rules and conventions for concurrency, resource management, and throughput.

## 1. Event Channel Buffering

The event API channel is created with a fixed buffer of 1000 in
`internal/ansible/runner/eventapi/eventapi.go`. Do not change this buffer
size without load-testing. Every write uses a `select` with a 10-second
`time.NewTimer` timeout. Always stop timers after use.

## 2. EventReceiver Lifecycle

`EventReceiver.Close()` performs: sets `stopped = true` under a write lock,
closes the HTTP server, removes the unix socket, and closes the Events channel.

Any new handler paths that touch the Events channel must acquire RLock and
check `stopped` first. `Close()` must always be called after ansible-runner exits.

## 3. MaxConcurrentReconciles

Default is `runtime.NumCPU()`. Each concurrent reconcile spawns an
ansible-runner subprocess, a unix-socket HTTP server, and a goroutine.
Budget roughly `3 * MaxConcurrentReconciles` goroutines plus one subprocess each.

Per-GVK override via `MAX_CONCURRENT_RECONCILES_<KIND>_<GROUP>` takes
precedence over the CLI flag. Values <= 0 are replaced with the default.

## 4. Cache Establishment Timeout

Hardcoded as `cacheEstablishmentTimeout = 6 * time.Second` in `proxy.go`.
Applies to every `informerCache.Get` and `informerCache.List` call. Not
configurable at runtime. Increasing it delays fallback to the API server.

## 5. RWMutex Locking Patterns

Three distinct usages:

### ControllerMap and WatchMap (`controllermap.go`)
- `sync.RWMutex` embedded in struct. `Get` takes RLock; `Store`/`Delete` take full Lock.
- Read on every proxied GET and owner-ref POST. Keep critical sections minimal.

### apiResources (`proxy.go`)
- `*sync.RWMutex` (pointer). Lock-upgrade pattern: RLock for cache hit, full Lock
  for discovery refresh via `ServerGroupsAndResources`. Cache miss blocks all concurrent checks.

### EventReceiver (`eventapi.go`)
- Protects only the `stopped` boolean. Channel is closed only when `stopped == true`.

**General rule:** prefer `sync.RWMutex`. Do not use `sync.Map`.

## 6. Goroutine Launch Patterns

| Location | Purpose | Lifecycle |
|---|---|---|
| `runner.go` Run() | Runs ansible-runner subprocess, closes receiver | Until subprocess exits |
| `eventapi.go` New() | Serves event HTTP on unix socket | Until `receiver.Close()` |
| `proxy.go` Run() | Starts informer cache; serves proxy | Process lifetime |
| `reconcile.go` Reconcile() | Fire-and-forget event handler dispatch | No join |
| `cache_response.go` | Recovers dependent watches | No join |

Only the runner goroutine cleans up the EventReceiver. Event handlers must be
goroutine-safe and must not modify the `unstructured.Unstructured` object.

## 7. Resource Cleanup

- **Unix sockets**: Created at `/tmp/ansibleoperator-<ident>`, removed in `EventReceiver.Close()`.
- **Kubeconfig temp files**: Created per reconcile, removed via `defer os.Remove(kc.Name())`.
- **Runner artifacts**: Controlled by `maxRunnerArtifacts` (default 20). A `latest` symlink is maintained.

## 8. Error Channel Pattern

The runner creates `make(chan error, 1)`. The buffer size of 1 prevents the
HTTP server's `Serve` goroutine from blocking. Use this same pattern for any
new background error communication.

