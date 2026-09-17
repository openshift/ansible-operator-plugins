# Ansible Operator Plugins

[![sanity](https://github.com/openshift/ansible-operator-plugins/actions/workflows/test-sanity.yml/badge.svg)](https://github.com/openshift/ansible-operator-plugins/actions/workflows/test-sanity.yml) [![unit](https://github.com/openshift/ansible-operator-plugins/actions/workflows/unit.yml/badge.svg)](https://github.com/openshift/ansible-operator-plugins/actions/workflows/unit.yml)

A plugin that provides Ansible-based operator functionality for the [Operator SDK](https://github.com/operator-framework/operator-sdk). This project contains the core Ansible operator implementation that enables developers to build Kubernetes operators using Ansible playbooks and roles.

## Overview

This project provides the Ansible plugin for Operator SDK, allowing you to:
- Build Kubernetes operators using Ansible playbooks and roles
- Manage custom resources with Ansible automation
- Handle operator lifecycle events through Ansible tasks
- Leverage the full ecosystem of Ansible modules and collections

## Tech Stack

| Component | Version / Details |
|---|---|
| Go | 1.26.3 |
| Module path | `github.com/operator-framework/ansible-operator-plugins` |
| Kubernetes libs | k8s.io v0.33.x (`client-go`, `apimachinery`, `api`) |
| Controller framework | [controller-runtime](https://pkg.go.dev/sigs.k8s.io/controller-runtime) v0.21.0 |
| Scaffolding framework | [kubebuilder](https://pkg.go.dev/sigs.k8s.io/kubebuilder/v4) v4.6.0 |
| Operator utilities | [operator-lib](https://github.com/operator-framework/operator-lib) v0.19.0 |
| Metrics | [prometheus/client_golang](https://github.com/prometheus/client_golang) v1.23.2 |
| CLI | cobra v1.10.2, pflag, viper |
| Testing | Ginkgo v2 / Gomega, testify, envtest |
| Tool management | [bingo](https://github.com/bwplotka/bingo) (golangci-lint, goreleaser, kind, setup-envtest) |
| Container image | `quay.io/operator-framework/ansible-operator` |

## Project Structure

```
cmd/ansible-operator/           Single binary entrypoint (cobra CLI)
internal/
  ansible/
    controller/                 Controller setup + reconcile loop
    runner/                     ansible-runner subprocess management
    proxy/                      REST proxy intercepting Ansible's K8s API calls
    watches/                    watches.yaml loading and validation
    events/                     Ansible event logging
    metrics/                    Prometheus metric definitions
    apiserver/                  Metrics API server (localhost:5050)
  cmd/ansible-operator/run/     "run" subcommand (manager setup, proxy start)
  version/                      Build-time version variables (ldflags)
pkg/
  plugins/ansible/v1/           Kubebuilder plugin: scaffolding templates
  testutils/                    Public E2E test utilities
hack/                           Scripts for generation, linting, license checks
images/ansible-operator/        Dockerfile + Pipfile for operator image
openshift/                      Downstream OpenShift fork overlay
testdata/                       Generated sample operator projects (do not hand-edit)
```

## Building and Testing

```sh
# Bootstrap dev tools (idempotent, no cluster creation)
make setup

# Build the ansible-operator binary
make build

# Full non-cluster validation (sanity + unit)
make verify

# Unit tests only (uses envtest, skips E2E)
make test-unit

# Sanity checks: formatting, linting, vet, license headers, error message format
make test-sanity

# Full E2E suite (creates a Kind cluster, builds images)
make test-e2e

# Ansible-specific E2E only
make test-e2e-ansible

# Auto-fix: go mod tidy + go fmt + golangci-lint --fix
make fix

# Regenerate testdata after scaffold template changes
make generate
```

Cross-compile by setting `BUILD_GOOS` and `BUILD_GOARCH`:

```sh
BUILD_GOOS=linux BUILD_GOARCH=arm64 make build
```

Build the Docker image:

```sh
make image-build
```

### Vendoring

This project vendors all dependencies. After modifying `go.mod`:

```sh
go mod tidy
go mod vendor
```

Commit the updated `vendor/` directory. The `make test-sanity` target will fail if the working tree is dirty after generation.

## Upstream/Downstream Synchronization

The `openshift/` directory contains an independent build overlay for the OpenShift downstream fork. See [openshift/README.md](openshift/README.md) for the rebase walkthrough and [docs/references/downstream-sync.md](docs/references/downstream-sync.md) for the `UPSTREAM: <carry|drop>:` commit convention.

## Further Documentation

| Document | Description |
|---|---|
| [AGENTS.md](AGENTS.md) | Component overview, AI agent routing, critical patterns |
| [docs/domain/](docs/domain/) | watches.yaml schema, API contracts, generated artifact rules |
| [docs/architecture/](docs/architecture/) | Reconcile flow, runner, proxy, error handling, performance |
| [docs/decisions/](docs/decisions/) | ADRs for upstream/downstream, vendor policy, release workflow |
| [docs/AOP_DEVELOPMENT.md](docs/AOP_DEVELOPMENT.md) | Build, validation matrix, code conventions, common mistakes |
| [docs/AOP_TESTING.md](docs/AOP_TESTING.md) | Ginkgo/testify conventions, envtest, E2E infrastructure |
| [docs/references/](docs/references/) | Ecosystem links, downstream sync, security rules |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Trust boundaries and threat analysis (draft) |

## Security

For security vulnerabilities, please see [THREAT_MODEL.md](THREAT_MODEL.md) for the trust boundary analysis and [docs/references/security.md](docs/references/security.md) for codebase security conventions.

# Releasing Guide

## Pre-Requisites
- Push access to this repository
- Forked repository and local clone of fork
- Remote ref named `upstream` that points to this repository

## Release Prep (Applies to all releases)
Since this project is currently consumed as a library there are some manual steps that need to take
place prior to creating a release. They are as follows:
1. Checkout the `main` branch:
```sh
git checkout main
```
2. Ensure the `main` branch is up to date:
```sh
git fetch upstream && git pull upstream main
```
3. Checkout a new branch for release prep work:
```sh
git checkout -b release/prep-vX.Y.Z
```
4. Update the `ImageVersion` variable in `internal/version/version.go` to be the version you are prepping for release
5. Update the line with `export IMAGE_VERSION` in `Makefile` to be the version you are prepping for release
6. Regenerate the testdata:
```sh
make generate
```
7. Commit and push your changes to your fork
8. Create a PR against the `main` branch

## Creating Major/Minor Releases
1. Ensure the steps in [Release Prep](#release-prep-applies-to-all-releases) have been completed. Do **NOT** progress past this point until the release prep PR has merged.
2. Checkout the `main` branch:
```sh
git checkout main
```
3. Ensure your local branch is up to date:
```sh
git fetch upstream && git pull upstream main
```
4. Checkout a new branch for the new release following the pattern `release-vX.Y`. In this example we will create a branch for a `v0.2.0` release:
```sh
git checkout -b release-v0.2
```
5. Push the newly created release branch:
```sh
git push -u upstream release-v0.2
```
6. Create a new release tag:
```sh
git tag -a -s -m "ansible-operator-plugins release v0.2.0" v0.2.0
```
7. Push the new tag:
```sh
git push upstream v0.2.0
```

## Creating Patch Releases
1. Ensure the steps in [Release Prep](#release-prep-applies-to-all-releases) have been completed. Do **NOT** progress past this point until the release prep PR has merged.
2. Cherry pick the merged release prep PR to the proper major/minor branch by commenting the following on the PR:
```
/cherry-pick release-vX.Y
```
where X is the major version and Y is the minor version. An example of cherry picking for a `v0.2.1` release would be:
```
/cherry-pick release-v0.2
```
3. A bot will have created the cherry pick PR. Merge this. Do **NOT** progress past this point until the cherry pick PR has merged.
4. Checkout the appropriate release branch. In this example we will be "creating" a `v0.2.1` release:
```sh
git checkout release-v0.2
```
5. Ensure it is up to date:
```sh
git fetch upstream && git pull upstream release-v0.2
```
6. Create a new release tag:
```sh
git tag -a -s -m "ansible-operator-plugins release v0.2.1" v0.2.1
```
7. Push the new tag:
```sh
git push upstream v0.2.1
```

> [!NOTE]
> While the release process is automated once the tag is pushed it can occasionally timeout.
> If this happens, re-running the action will re-run the release process and typically succeed.
