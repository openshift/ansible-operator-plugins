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

## Architecture at a Glance

| Surface | Start here |
|---|---|
| Runtime startup | `internal/cmd/ansible-operator/run/cmd.go:95` |
| Watch configuration | `internal/ansible/watches/watches.go:313` |
| CR reconciliation | `internal/ansible/controller/reconcile.go:68` |
| Ansible execution | `internal/ansible/runner/runner.go:182` |
| Scaffolding plugin | `pkg/plugins/ansible/v1/plugin.go:25` |

## Documentation Structure

```text
AGENTS.md / CLAUDE.md   Entry point (CLAUDE.md is a symlink)
REVIEW.md              Diff-oriented review rules
ai-docs/ARCHITECTURE.md Runtime contracts and source map
ai-docs/DEVELOPMENT.md  Build, generation, and downstream work
ai-docs/TESTING.md      Test commands, suites, and prerequisites
ai-docs/ENHANCEMENTS.md Historical design reference catalog
```

## Key Files and Task Routing

- [Architecture and behavioral contracts](ai-docs/ARCHITECTURE.md): start here for runtime changes.
- [Development](ai-docs/DEVELOPMENT.md): generators, safe commands, CI, and release references.
- [Testing](ai-docs/TESTING.md): select checks before running cluster-dependent suites.
- [Review guidance](REVIEW.md): severity, evidence, and path-specific rules.
- [Design catalog](ai-docs/ENHANCEMENTS.md): historical proposal, not a current support commitment.
- [Requirements generation](openshift/hack/generate_requirements.md): downstream Python dependency workflow.

## External References

- [Platform development guidance](https://github.com/openshift/enhancements/tree/master/dev-guide) is shared context, not proof of local implementation.
- [Platform conventions](https://github.com/openshift/enhancements/blob/master/CONVENTIONS.md); this repository uses `main`, not the historical branch example there.
