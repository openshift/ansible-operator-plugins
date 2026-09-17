# Architectural Boundaries

## Package Visibility and Dependency Direction

```text
cmd/                    Binary entrypoint only; delegates to internal/cmd/
  └─→ internal/         Runtime implementation (not importable by external consumers)
       └─→ pkg/         Public API surface (kubebuilder plugin, test utilities)

openshift/              Independent build overlay; mirrors upstream, does not
                        import upstream Go packages at build time

vendor/                 Committed dependency tree; leaf artifact, never hand-edited
testdata/               Generated sample projects; leaf artifact, never hand-edited
```

### Allowed Import Directions

| Source | May Import |
|---|---|
| `cmd/` | `internal/`, `pkg/`, stdlib, third-party |
| `internal/` | `pkg/`, stdlib, third-party, vendored |
| `pkg/` | stdlib, third-party, vendored |
| `openshift/` | Its own `go.mod` dependencies (separate module) |

### Forbidden Patterns

- `pkg/` must never import `internal/`. The plugin scaffolding package is a
  public API; it must not depend on runtime internals.
- `cmd/` should not contain business logic beyond CLI wiring.
- `openshift/` Go code does not import the root module's packages at build time
  (it has its own `go.mod`).

## Proxy Handler Chain Ordering

The handler chain in `proxy.go` is assembled inside-out and the ordering is
load-bearing. See `docs/domain/watches-and-contracts.md` for the contract.

Adding middleware that modifies request bodies must go between the
authorization-stripping and owner-injection layers, never outside the cache handler.
