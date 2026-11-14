# RHCOS10 UBI9 Compatibility Test

## Purpose

Validate that the existing UBI9-based container images used by `ansible-operator-plugins`
run correctly on RHCOS10 cluster nodes **without any changes**.

RHCOS10 ships with RHEL10 as its host OS. This PR triggers CI against an RHCOS10 cluster
to confirm UBI9 containers remain compatible before committing to a base image migration.

No Dockerfile changes. This is a baseline/smoke test only.

## Scope

Product images currently use `registry.access.redhat.com/ubi9/ubi-minimal:9.7` as their
final base image. CI/release images use `registry.ci.openshift.org/ocp/4.22:base-rhel9`
as their base.

| Image / Dockerfile                            | Current Base Image                                                 |
| --------------------------------------------- | ------------------------------------------------------------------ |
| `images/ansible-operator/Dockerfile`          | `registry.access.redhat.com/ubi9/ubi-minimal:9.7` (2 stages)      |
| `images/ansible-operator/pipfile.Dockerfile`  | `registry.access.redhat.com/ubi9/ubi-minimal:9.7`                 |
| `openshift/Dockerfile`                        | `registry.ci.openshift.org/ocp/builder:rhel-9-golang-*` (builder) |
|                                               | `registry.ci.openshift.org/ocp/4.22:base-rhel9` (runtime)         |
| `openshift/Dockerfile.requirements`           | `registry.ci.openshift.org/ocp/4.22:base-rhel9`                   |
| `openshift/release/ansible/Dockerfile.collections` | `registry.ci.openshift.org/ocp/4.22:base-rhel9`              |

## Expected Outcome

- All CI jobs pass on RHCOS10 nodes with UBI9 images unchanged.
- Confirms backward compatibility and green baseline before migration.

## Follow-up

If CI passes → PR2 (`rhcos10-ubi10-migration`) migrates all base images from UBI9/RHEL9 to UBI10/RHEL10.
