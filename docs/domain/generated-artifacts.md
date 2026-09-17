# Generated and Vendored Artifacts

This document lists all generated artifacts in the repository, their regeneration
commands, and rules for when they must be updated.

## Artifact Inventory

| Artifact | Location | Regeneration Command | Hand-Edit? |
|---|---|---|---|
| Sample operator projects | `testdata/` | `make generate` | Never |
| Go dependencies | `vendor/` | `go mod tidy && go mod vendor` | Never |
| Scaffold templates output | `testdata/` (via templates in `pkg/plugins/`) | `make generate` | Never (edit templates instead) |
| Downstream ansible collections | `openshift/release/ansible/ansible_collections/` | `openshift/hack/rebase_upstream.sh` | Never |
| Downstream vendor | `openshift/vendor/` | `cd openshift && go mod tidy && go mod vendor` | Never |
| Downstream requirements | `openshift/release/ansible/requirements.yml` | `openshift/Makefile` targets | Never |

## Rules

1. **`testdata/`** is entirely generated. After any change to scaffolding
   templates in `pkg/plugins/ansible/v1/scaffolds/`, run `make generate` and
   commit the updated testdata. The `make test-sanity` target will fail
   (`git diff --exit-code`) if testdata is stale.

2. **`vendor/`** is committed. After modifying `go.mod`, always run:
   ```sh
   go mod tidy
   go mod vendor
   ```
   The `make fix` target runs `go mod tidy` but does **not** run
   `go mod vendor`. The sanity check catches dirty vendor via `git diff`.

3. **Scaffold templates** live in `pkg/plugins/ansible/v1/scaffolds/internal/templates/`.
   Edit templates, not their output in `testdata/`. After template changes,
   `make generate` rebuilds the binary and re-runs
   `hack/generate/samples/generate_testdata.go`.

4. **Downstream artifacts** under `openshift/` have their own generation
   pipeline. See [docs/references/downstream-sync.md](../references/downstream-sync.md)
   for the rebase workflow and `UPSTREAM: <carry|drop>:` commit convention.

