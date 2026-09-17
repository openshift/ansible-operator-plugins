# Ansible Operator Plugins - Agentic Documentation

**Component**: Ansible Operator Plugins (AOP)
**Repository**: openshift/ansible-operator-plugins (downstream mirror of operator-framework/ansible-operator-plugins)

> **AI agents**: Read `docs/domain/` first for API contracts and watches.yaml schema,
> then `docs/architecture/` for reconcile/runner/proxy implementation patterns.
> Check `docs/decisions/` before making architectural changes.

## What is Ansible Operator Plugins?

A Go library and binary that bridges Ansible automation with Kubernetes controllers via controller-runtime. Part of the Operator SDK ecosystem, consumed as a standalone `ansible-operator` binary and as a library by downstream projects (notably the OpenShift fork under `openshift/`).

**Core loop**: a `watches.yaml` file maps Kubernetes GVKs to Ansible playbooks or roles. For each watch entry, a controller-runtime controller is created. On reconcile, the controller shells out to `ansible-runner`, consumes job events via a Unix-domain-socket HTTP API, and updates the CR's status conditions.

## Core Components

| Component | Location | Purpose |
|---|---|---|
| Controller | `internal/ansible/controller/` | Controller setup, reconcile loop, status conditions |
| Runner | `internal/ansible/runner/` | ansible-runner subprocess management, event API |
| Proxy | `internal/ansible/proxy/` | REST proxy intercepting Ansible's K8s API calls |
| Watches | `internal/ansible/watches/` | watches.yaml loading and validation |
| Metrics | `internal/ansible/metrics/`, `internal/ansible/apiserver/` | Prometheus metrics, user-metric API (port 5050) |
| Plugin/Scaffold | `pkg/plugins/ansible/v1/` | Kubebuilder plugin: scaffolding templates |
| Test utilities | `pkg/testutils/` | Public E2E helpers (Kind, kubectl, operator lifecycle) |
| Downstream | `openshift/` | OpenShift fork overlay (separate go.mod, vendor, Makefile) |
| Testdata | `testdata/` | Generated sample operator projects (do not hand-edit) |

## Critical Patterns

1. **DO NOT hand-edit** `testdata/`, `vendor/`, or generated scaffold output. Run `make generate` after scaffold/plugin changes; run `go mod tidy && go mod vendor` after dependency changes.
2. **DO NOT type-check a single Go file independently** of its package. Always lint and test at the package level: `go test ./internal/ansible/controller/`.
3. **DO NOT run E2E tests** without Docker and Kind. E2E creates a cluster and builds images.
4. **DO NOT change the proxy bind address** from localhost. The proxy has no authentication of its own.
5. **DO NOT remove either `Authorization` header stripping call** in the proxy handler chain. Both are required.
6. **DO NOT use `sync.Map`** -- the codebase uses `sync.RWMutex` exclusively for concurrent data structures.

## Design Rationale (selected)

- `openshift/` uses a separate `go.mod` and vendor tree instead of a Go
  workspace, because downstream CVE backports and release cadence must not
  block on upstream merges (`docs/decisions/adr-0001-upstream-downstream-mirror.md`).
- Ansible job events are consumed over a Unix-domain-socket HTTP API rather
  than parsed from stdout, because structured JSON events are the only
  reliable way to drive status conditions (`docs/architecture/components.md`).

## Single-File Verification

Go is type-checked at the **package** level. Always validate the enclosing package:

| Task | Command |
|---|---|
| Lint one package | `golangci-lint run ./internal/ansible/controller/` |
| Type check (vet) | `go vet ./internal/ansible/controller/` |
| Run one test | `go test ./internal/ansible/controller/ -run TestReconcile` |
| Format | `go fmt ./internal/ansible/controller/` |
| Shell check | `shellcheck path/to/script.sh` |
| YAML lint | `yamllint path/to/file.yaml` |

## Documentation Structure

```text
docs/
├── domain/
│   ├── watches-and-contracts.md     # watches.yaml schema, status conditions, annotations, ports
│   └── generated-artifacts.md       # testdata, vendor, scaffold output rules
├── architecture/
│   ├── components.md                # Reconcile flow, runner, proxy, event handlers, metrics
│   ├── error-handling.md            # Reconciler error contract, status marking, HTTP errors
│   ├── performance.md               # Channel buffering, concurrency, mutexes, goroutines
│   └── boundaries.md                # Package visibility, dependency direction
├── decisions/
│   ├── adr-0001-upstream-downstream-mirror.md
│   ├── adr-0002-generated-vendor-artifact-policy.md
│   ├── adr-0003-release-rebase-workflow.md
│   ├── adr-0004-openapi-not-applicable.md
│   └── adr-template.md
├── references/
│   ├── ecosystem.md                 # Links to operator-sdk, enhancements, platform patterns
│   ├── downstream-sync.md           # UPSTREAM: carry/drop, rebase workflow, openshift/ targets
│   └── security.md                  # Proxy auth, kubeconfig, RBAC, input validation, file perms
├── AOP_DEVELOPMENT.md               # Build, setup, verify, validation matrix, common mistakes
└── AOP_TESTING.md                   # Ginkgo/testify conventions, envtest, E2E, short mode
```

**AI Agent Path**: `docs/domain/` → `docs/architecture/` → `docs/decisions/` → `docs/AOP_DEVELOPMENT.md` or `docs/AOP_TESTING.md` (as relevant)

## Quick Reference

| Action | Command |
|---|---|
| Bootstrap tools | `make setup` |
| Full non-cluster validation | `make verify` |
| Build binary | `make build` |
| Unit tests (envtest) | `make test-unit` |
| Sanity (lint, vet, license) | `make test-sanity` |
| E2E (Ansible) | `make test-e2e-ansible` |
| Auto-fix formatting | `make fix` |
| Regenerate testdata | `make generate` |
| Build Docker image | `make image-build` |

**Framework**: controller-runtime v0.21.0 | **Go**: 1.26.3 | **Module**: `github.com/operator-framework/ansible-operator-plugins`

## Pattern References

- **New GVK watch**: follow the pattern in `internal/ansible/watches/watches.go` and `testdata/memcached-molecule-operator/watches.yaml`
- **Controller reconcile feature**: see `internal/ansible/controller/reconcile.go` as reference
- **Scaffold template change**: follow the pattern in `pkg/plugins/ansible/v1/scaffolds/internal/templates/`
- **Go dependency update**: see `go.mod` and `go.sum` as reference; run `go mod tidy && go mod vendor`, then `make verify`
- **Downstream carry patch**: follow the pattern in `openshift/Makefile` and `openshift/hack/rebase_upstream.sh`; prefix commits with `UPSTREAM: <carry>:`

See `docs/patterns/README.md` for the full pattern index and `examples/` for a runnable sample operator.

## Knowledge Graph

```text
                       [AGENTS.md] ← Start here
                            │
            ┌───────────────┼───────────────┐
            │               │               │
  [docs/domain/]    [docs/architecture/]  [docs/decisions/]
   watches.yaml       Reconcile flow        ADR history
   API contracts      Runner/Proxy          (4 ADRs)
   Generated files    Error handling
            │               │               │
            └───────────────┼───────────────┘
                            │
              [docs/AOP_DEVELOPMENT.md]
              [docs/AOP_TESTING.md]
                            │
              [docs/references/]
                 Ecosystem links
                 Downstream sync
                 Security rules
```

## External References

- [openshift/README.md](openshift/README.md) -- downstream sync walkthrough
- [images/ansible-operator/README.md](images/ansible-operator/README.md) -- container image and Python conventions
