---
paths:
  - "internal/ansible/runner/**"
---

# Runner Module Rules

- `ansible-runner` must be on `$PATH`. Detected via `exec.LookPath` at run time, not startup.
- Input directory layout: `/tmp/ansible-operator/runner/<group>/<version>/<kind>/<namespace>/<name>/`.
- Parameters in `env/extravars` are snake_cased from the CR spec. The `markUnsafe` feature wraps strings as `{"__ansible_unsafe": "<value>"}`.
- Each reconcile creates a Unix socket at `/tmp/ansibleoperator-<ident>` for the event API HTTP server.
- Events channel is buffered with capacity 1000 and a 10-second write timeout to prevent blocking.
- Status events (those without a UUID) are silently dropped; only JobEvents with a UUID are forwarded.
- After each run, a `latest` symlink is created under `artifacts/`.
- Use `sync.RWMutex` for concurrent data structures; never use `sync.Map`.
- Validate at package level: `go test ./internal/ansible/runner/ -short`.
