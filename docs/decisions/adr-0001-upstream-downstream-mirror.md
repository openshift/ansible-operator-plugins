# ADR-0001: Upstream/Downstream Mirror Architecture

## Status

Accepted

## Context

This repository (`openshift/ansible-operator-plugins`) is the downstream mirror
of the upstream Ansible operator source at
`operator-framework/ansible-operator-plugins`. The root tree mirrors upstream
unmodified; the `openshift/` directory adds an independent build overlay,
downstream-only dependencies, and Ansible collections. The two trees must stay
synchronized without polluting each other's histories.

## Decision

The `openshift/` directory at the root of this repository contains the
downstream overlay as a self-contained subtree with its own `go.mod`,
`vendor/`, `Makefile`, and `Dockerfile`. This allows:

1. The root tree to remain a clean mirror of upstream, free of OpenShift-specific build concerns.
2. Downstream maintainers to rebase from upstream tags using
   `openshift/hack/rebase_upstream.sh`.
3. Commits introduced during rebase to use the `UPSTREAM: <carry|drop>:`
   prefix convention to signal intent during future rebases.

The downstream overlay does **not** import upstream Go packages at build time.
It has its own module path and dependency tree.

We chose to keep the overlay as a separate module tree instead of a shared Go
workspace because downstream CVE backports and release cadence must not
block on upstream merges (or vice versa). A shared workspace would tie both
trees to the same dependency graph and release timeline.

## Consequences

- Contributors must understand which directory to modify based on whether a
  change is upstream (root) or downstream-only (`openshift/`).
- Dependency updates may need to happen in two places (`go.mod` and `openshift/go.mod`).
- The `UPSTREAM: <carry>:` / `UPSTREAM: <drop>:` convention must be followed
  during downstream rebases to preserve the correct commit history.
- See [docs/references/downstream-sync.md](../references/downstream-sync.md)
  for the full rebase workflow.
