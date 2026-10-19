# Ansible Operator Plugins

| Field | Value |
|---|---|
| Repository | https://github.com/openshift/ansible-operator-plugins |
| Development branch | `main` |
| Go module | `github.com/operator-framework/ansible-operator-plugins` (`go.mod:1`) |

## Purpose

Ansible operator runtime and Kubebuilder scaffolding plugin, with OpenShift base-image build artifacts.
Start with [the overview](README.md) and [downstream build/sync guidance](openshift/README.md).

## Critical Warnings

- Never hand-edit generated `testdata/`; change scaffolds/generators and use `make generate` (`Makefile:52`).
- Never run `make clean` casually: its removal command targets `BUILD_DIR`, whose default is `.` (`Makefile:18`, `Makefile:68`).
- Never assume all writes use server-side apply: CR metadata/status use Update; Ansible requests pass through a proxy (`internal/ansible/controller/reconcile.go:112`, `internal/ansible/proxy/proxy.go:96`).
- Never collapse the two Go modules: downstream dependencies live under `openshift/` (`openshift/README.md:20`).
- Do not change the proxy bind address from localhost. The proxy has no authentication of its own.
- Do not remove either `Authorization` header stripping call in the proxy handler chain. Both are required.
- Do not use `sync.Map` -- the codebase uses `sync.RWMutex` exclusively for concurrent data structures.
- Do not type-check a single Go file independently of its package. Always lint and test at the package level.
- Do not run E2E tests without Docker and Kind. E2E creates a cluster and builds images.

## Architecture at a Glance

| Surface | Start here |
|---|---|
| Runtime startup | `internal/cmd/ansible-operator/run/cmd.go:95` |
| Watch configuration | `internal/ansible/watches/watches.go:313` |
| CR reconciliation | `internal/ansible/controller/reconcile.go:68` |
| Ansible execution | `internal/ansible/runner/runner.go:182` |
| Scaffolding plugin | `pkg/plugins/ansible/v1/plugin.go:25` |

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

## Documentation Structure

```text
AGENTS.md / CLAUDE.md   Entry point (CLAUDE.md is a symlink)
REVIEW.md               Diff-oriented review rules
ai-docs/ARCHITECTURE.md Runtime contracts and source map
ai-docs/DEVELOPMENT.md  Build, generation, and downstream work
ai-docs/TESTING.md       Test commands, suites, and prerequisites
ai-docs/ENHANCEMENTS.md Historical design reference catalog
docs/decisions/          Architecture Decision Records (4 ADRs)
docs/patterns/README.md  Pattern index for common changes
```

## Key Files and Task Routing

- [Architecture and behavioral contracts](ai-docs/ARCHITECTURE.md): start here for runtime changes.
- [Development](ai-docs/DEVELOPMENT.md): generators, safe commands, CI, and release references.
- [Testing](ai-docs/TESTING.md): select checks before running cluster-dependent suites.
- [Review guidance](REVIEW.md): severity, evidence, and path-specific rules.
- [Design catalog](ai-docs/ENHANCEMENTS.md): historical proposal, not a current support commitment.
- [Requirements generation](openshift/hack/generate_requirements.md): downstream Python dependency workflow.

## Pattern References

- **New GVK watch**: follow the pattern in `internal/ansible/watches/watches.go` and `testdata/memcached-molecule-operator/watches.yaml`
- **Controller reconcile feature**: see `internal/ansible/controller/reconcile.go` as reference
- **Scaffold template change**: follow the pattern in `pkg/plugins/ansible/v1/scaffolds/internal/templates/`
- **Go dependency update**: see `go.mod` and `go.sum` as reference; run `go mod tidy && go mod vendor`, then `make verify`
- **Downstream carry patch**: follow the pattern in `openshift/Makefile` and `openshift/hack/rebase_upstream.sh`; prefix commits with `UPSTREAM: <carry>:`

See `docs/patterns/README.md` for the full pattern index.

## External References

- [Platform development guidance](https://github.com/openshift/enhancements/tree/master/dev-guide) is shared context, not proof of local implementation.
- [Platform conventions](https://github.com/openshift/enhancements/blob/master/CONVENTIONS.md); this repository uses `main`, not the historical branch example there.
- [openshift/README.md](openshift/README.md) -- downstream sync walkthrough
- [images/ansible-operator/README.md](images/ansible-operator/README.md) -- container image and Python conventions
