# Ansible Operator Plugins -- Development Guide

## Quick Start

### Prerequisites

- Go 1.26.3 (CI reads the version from `go.mod`)
- Docker with buildx support (for image builds)
- make
- Ansible and ansible-runner (for E2E tests only)

Tool binaries are managed via [bingo](https://github.com/bwplotka/bingo) --
no manual tool installation needed.

### Build and Run

```bash
# Bootstrap dev tools (idempotent, no cluster creation)
make setup

# Build the ansible-operator binary
make build

# Full non-cluster validation (sanity + unit tests)
make verify

# Lint only (no auto-fix)
make lint

# Auto-fix: go mod tidy + go fmt + golangci-lint --fix
make fix

# Regenerate testdata after scaffold template changes
make generate

# Build Docker image
make image-build
```

## Validation Command Matrix

| Change Type | Minimum Validation | Full PR Validation |
|---|---|---|
| Go package code | `go fmt ./path/to/pkg`, `go test ./path/to/pkg`, `go vet ./path/to/pkg` | `make verify` |
| Scaffold/plugin templates | `make generate` + `git diff --exit-code` | `make verify` |
| Go dependencies | `go mod tidy && go mod vendor` | `make verify` |
| Documentation only | Markdown link/render review | `make test-sanity` (for license/format if touching Go-adjacent files) |
| Downstream (openshift/) | `openshift/Makefile` targets | `check-requirements`, `check-collections` |

## Single-File / Focused Change Validation

Go is compiled and type-checked at the **package** level, not the file level.
You cannot validate a single `.go` file in isolation. Always work with the
package containing the file:

```bash
# Format the file (applied to all files in the package)
go fmt ./internal/ansible/controller/

# Run a specific test
go test ./internal/ansible/controller/ -run TestReconcile

# Vet the package
go vet ./internal/ansible/controller/

# Lint the package
golangci-lint run ./internal/ansible/controller/
```

### When Repo-Wide Checks Are Mandatory

- Scaffold template changes (`pkg/plugins/`) -- must run `make generate`
- `go.mod` changes -- must run `go mod tidy && go mod vendor`
- Import path changes in `internal/` or `pkg/`
- Anything touching `hack/generate/`

### Ansible/Python Changes

Molecule test artifacts (`__pycache__/`, `.pytest_cache/`) are gitignored.
E2E molecule tests require `ansible-core` installed:

```bash
pip3 install ansible-core~=2.17.4
make test-e2e-ansible-molecule
```

## Safe Validation Behavior

- `make test-sanity` runs `generate` and `fix` **before** checks, then
  asserts `git diff --exit-code`. This means it may modify files and then
  fail if the working tree becomes dirty.
- E2E tests (`make test-e2e-ansible`) require Docker and Kind. They create a
  cluster, build images, and take several minutes.
- Unit tests run with `-short` flag via `make test-unit`. Tests requiring a
  live cluster are skipped in short mode.

## Code Conventions

### License Header

Every `.go` file must have an Apache 2.0 license header. Enforced by
`hack/check-license.sh` during `make test-sanity`.

### Error and Log Message Formatting

Enforced by `hack/check-error-log-msg-format.sh`:
- Log messages (Error, Fatal, Info, Warn) must begin with an uppercase letter.
- Error messages (`errors.New`, `fmt.Errorf`) must begin with a lowercase letter.
- Error messages must not end with a period.

### Import Ordering

Three groups separated by blank lines:
1. Standard library
2. Third-party and Kubernetes libraries
3. Internal packages (`github.com/operator-framework/ansible-operator-plugins/...`)

### Logging

Use `logf "sigs.k8s.io/controller-runtime/pkg/log"` with `logf.Log.WithName("...")`.
Verbosity: V(0) for reconciliation lifecycle, V(1) for handler events,
V(2) for request bodies and status events.

### Naming Conventions

- Controllers: `<kind>-<version>-controller` (lowercased)
- Env var overrides: `<SETTING>_<KIND>_<GROUP>` (dots → underscores, uppercased)
- Annotations: prefix `ansible.sdk.operatorframework.io/`
- File permissions: `DirMode = 0755`, `FileMode = 0644`, `ExecFileMode = 0755`

## Vendoring

This project vendors all dependencies. After modifying `go.mod`:

```bash
go mod tidy
go mod vendor
```

Commit the updated `vendor/`. The `make fix` target runs `go mod tidy` but
does not run `go mod vendor`.

## Release Process

Releases are tag-driven. See [docs/decisions/adr-0003-release-rebase-workflow.md](decisions/adr-0003-release-rebase-workflow.md) for the full workflow.

1. Update `ImageVersion` in `internal/version/version.go`
2. Update `IMAGE_VERSION` in `Makefile`
3. Run `make generate`
4. Merge the prep PR, then tag

## Downstream / OpenShift

See [docs/references/downstream-sync.md](references/downstream-sync.md) for
the full rebase workflow, `UPSTREAM: <carry|drop>:` convention, and downstream
Make targets.

