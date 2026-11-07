---
paths:
  - "openshift/**"
---

# Downstream (OpenShift) Module Rules

- The `openshift/` directory is an independent build overlay with its own `go.mod`, `vendor/`, `Makefile`, and `Dockerfile`.
- `openshift/` Go code does not import the root module's packages at build time (separate module).
- Commits during downstream rebases MUST use `UPSTREAM: <carry>:` or `UPSTREAM: <drop>:` prefix convention.
- DO NOT hand-edit `openshift/vendor/` or `openshift/release/ansible/ansible_collections/` -- these are generated.
- Downstream Make targets: `update-collections`, `generate-requirements`, `check-requirements`, `check-collections`.
- Dependency updates may need to happen in both `go.mod` and `openshift/go.mod`.
- Rebase workflow uses `openshift/hack/rebase_upstream.sh`.
- See `docs/references/downstream-sync.md` for the full rebase workflow.
