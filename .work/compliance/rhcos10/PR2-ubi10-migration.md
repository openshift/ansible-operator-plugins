# RHCOS10 UBI10 Migration

## Summary

Migrate all container base images from UBI9/RHEL9 to UBI10/RHEL10 for native RHCOS10 compatibility.
Also moves the registry from `registry.access.redhat.com` to `registry.redhat.io`.

```text
registry.access.redhat.com  →  registry.redhat.io
```

## Image Changes

| Dockerfile                                         | Before                                                              | After                                              |
| -------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------------------------- |
| `images/ansible-operator/Dockerfile` (basebuilder) | `registry.access.redhat.com/ubi9/ubi-minimal:9.7`                  | `registry.redhat.io/ubi10/ubi-minimal:10.1`        |
| `images/ansible-operator/Dockerfile` (base)        | `registry.access.redhat.com/ubi9/ubi-minimal:9.7`                  | `registry.redhat.io/ubi10/ubi-minimal:10.1`        |
| `images/ansible-operator/pipfile.Dockerfile`       | `registry.access.redhat.com/ubi9/ubi-minimal:9.7`                  | `registry.redhat.io/ubi10/ubi-minimal:10.1`        |
| `openshift/Dockerfile` (builder)                   | `registry.ci.openshift.org/ocp/builder:rhel-9-golang-*`            | `registry.redhat.io/ubi10/go-toolset:10.1`         |
| `openshift/Dockerfile` (runtime)                   | `registry.ci.openshift.org/ocp/4.22:base-rhel9`                    | `registry.redhat.io/ubi10/ubi:10.1`                |
| `openshift/Dockerfile.requirements`                | `registry.ci.openshift.org/ocp/4.22:base-rhel9`                    | `registry.redhat.io/ubi10/ubi:10.1`                |
| `openshift/release/ansible/Dockerfile.collections` | `registry.ci.openshift.org/ocp/4.22:base-rhel9`                    | `registry.redhat.io/ubi10/ubi:10.1`                |

## Exclusions

- `openshift/ci/dockerfiles/ansible-e2e.Dockerfile` — builds `FROM openshift-ansible-operator-plugins` (CI-internal); no base image to change.
- `testdata/memcached-molecule-operator/Dockerfile` — uses `quay.io/operator-framework/ansible-operator:dev`; not in scope.

## Prerequisite

PR1 (`rhcos10-ubi9-compat-test`) should pass CI on RHCOS10 nodes before merging this.

## Test Checklist

- [ ] `e2e-ansible`
- [ ] `e2e-ansible-fips`
- [ ] `e2e-ansible-rhcos10`
- [ ] `e2e-ansible-rhcos10-fips`

## CI Image References

```text
registry.access.redhat.com/ubi9/ubi-minimal:9.7
→
registry.redhat.io/ubi10/ubi-minimal:10.1

registry.ci.openshift.org/ocp/builder:rhel-9-golang-1.25-openshift-4.22
→
registry.redhat.io/ubi10/go-toolset:10.1

registry.ci.openshift.org/ocp/4.22:base-rhel9
→
registry.redhat.io/ubi10/ubi:10.1
```
