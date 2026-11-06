# Ansible Operator Plugins

| Field | Value |
|---|---|
| Repository | https://github.com/openshift/ansible-operator-plugins |
| Development branch | `main` |
| Go module | `github.com/operator-framework/ansible-operator-plugins` (`go.mod`) |

## Purpose

Ansible operator runtime and Kubebuilder scaffolding plugin, with OpenShift base-image build artifacts.
Start with [the overview](README.md) and [downstream build/sync guidance](openshift/README.md).

## Critical Warnings

- Never hand-edit generated `testdata/`; change scaffolds/generators and use `make generate` (`Makefile`).
- Never run `make clean` casually: its removal command targets `BUILD_DIR`, whose default is `.` (`Makefile`).
- Never assume all writes use server-side apply: CR metadata/status use Update; Ansible requests pass through a proxy (`internal/ansible/controller/reconcile.go`, `internal/ansible/proxy/proxy.go`).
- Never collapse the two Go modules: downstream dependencies live under `openshift/` (`openshift/README.md`).

## Architecture at a Glance

| Surface | Start here |
|---|---|
| Runtime startup | `internal/cmd/ansible-operator/run/cmd.go` |
| Watch configuration | `internal/ansible/watches/watches.go` |
| CR reconciliation | `internal/ansible/controller/reconcile.go` |
| Ansible execution | `internal/ansible/runner/runner.go` |
| Scaffolding plugin | `pkg/plugins/ansible/v1/plugin.go` |

## Documentation Structure

```text
AGENTS.md / CLAUDE.md   Entry point (CLAUDE.md is a symlink)
REVIEW.md              Diff-oriented review rules
ai-docs/ARCHITECTURE.md Runtime contracts and source map
ai-docs/DEVELOPMENT.md  Build, generation, and downstream work
ai-docs/TESTING.md      Test commands, suites, and prerequisites
```

## Key Files and Task Routing

- [Architecture and behavioral contracts](ai-docs/ARCHITECTURE.md): start here for runtime changes.
- [Development](ai-docs/DEVELOPMENT.md): generators, safe commands, CI, and release references.
- [Testing](ai-docs/TESTING.md): select checks before running cluster-dependent suites.
- [Review guidance](REVIEW.md): severity, evidence, and path-specific rules.
- [Requirements generation](openshift/hack/generate_requirements.md): downstream Python dependency workflow.

## External References

- [Platform development guidance](https://github.com/openshift/enhancements/tree/master/dev-guide) is shared context, not proof of local implementation.
- [Platform conventions](https://github.com/openshift/enhancements/blob/master/CONVENTIONS.md); this repository uses `main`, not the historical branch example there.
