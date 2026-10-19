# ADR-0003: Release and Rebase Workflow

## Status

Accepted

## Context

Releases are tag-driven and automated via goreleaser. The downstream OpenShift
fork periodically rebases onto upstream release tags, introducing
downstream-specific commits that must be tracked across rebases.

## Decision

### Upstream Release

1. Update `ImageVersion` in `internal/version/version.go` and `IMAGE_VERSION`
   in `Makefile`.
2. Run `make generate` to regenerate testdata.
3. Merge the release prep PR, then tag (e.g., `v1.42.3`).
4. The goreleaser GitHub Actions workflow builds multi-arch binaries and Docker
   images, pushing to `quay.io/operator-framework/ansible-operator`.

### Downstream Rebase

1. Fetch the new upstream tag.
2. Run `openshift/hack/rebase_upstream.sh` which:
   - Rebases the downstream branch onto the upstream tag
   - Runs `go mod tidy && go mod vendor` with an `UPSTREAM: <drop>:` commit
   - Updates ansible collections with an `UPSTREAM: <carry>:` commit
   - Updates downstream requirements with an `UPSTREAM: <carry>:` commit
3. Resolve any Cachito conflicts manually.
4. Push the rebased branch for CI validation.

## Consequences

- The release process is simple for upstream: prep PR → tag → automated build.
- Downstream rebases require manual intervention for conflict resolution.
- The `UPSTREAM:` commit prefix convention must be preserved for future rebases.
