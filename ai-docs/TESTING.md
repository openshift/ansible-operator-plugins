# Testing

## Command Map

The root Makefile defines the test graph; prefer these entry points over
inventing a blanket `go test ./...` invocation (`Makefile:107`).

| Command | Scope |
|---|---|
| `make test-unit` | Short Go tests, excluding the e2e package prefix (`Makefile:131`, `Makefile:133`). |
| `make test-sanity` | Generation, formatting fixes, diff checks, license checks, vet, lint (`Makefile:115`). |
| `make test-static` | Sanity and unit prerequisites (`Makefile:112`). |
| `make test-e2e-ansible` | Cluster-based Go/Ginkgo e2e suite (`Makefile:163`). |
| `make test-e2e-ansible-molecule` | Generated sample and shell-driven molecule workflow (`Makefile:165`). |
| `make test-all` | Static checks and e2e target (`Makefile:109`). |

## Unit Environment

`test-unit` obtains API-server test assets through the Bingo-managed
`SETUP_ENVTEST` executable (`Makefile:132`).
`ENVTEST_VERSION` is calculated from `k8s.io/client-go`, not from the
separately exported kind-node `K8S_VERSION` (`Makefile:130`).

The recipe sets `KUBEBUILDER_ASSETS` and invokes Go with `-short`,
`-coverprofile=coverage.out`, and `-covermode=count` (`Makefile:133`).
Allow for tool and envtest downloads when planning a first run.
Do not mistake these tests for a prerequisite-free compiler check.

GitHub's unit job runs `make test-unit` after selecting Go from `go.mod`
(`.github/workflows/unit.yml:15`).
Use the Makefile's package exclusion when narrowing a failure; the e2e suite
has a different environment (`Makefile:131`).

## Source-Test Pairing

| Change | Start with |
|---|---|
| Watch loading and defaults | `internal/ansible/watches/watches_test.go:1` |
| Runner parameters and invocation | `internal/ansible/runner/runner_test.go:1` |
| Reconcile/status/finalizers | `internal/ansible/controller/reconcile_test.go:1` |
| Controller setup and selectors | `internal/ansible/controller/controller_test.go:1` |
| Proxy request handling | `internal/ansible/proxy/proxy_test.go:1` |
| Owner injection | `internal/ansible/proxy/inject_owner_test.go:1` |
| Case conversion | `internal/ansible/paramconv/paramconv_test.go:1` |

The parameter-conversion tests use standard table-driven `testing` functions;
`TestToSnake` includes acronym handling (`internal/ansible/paramconv/paramconv_test.go:135`).
Proxy tests also have a Ginkgo/Gomega suite bootstrap
(`internal/ansible/proxy/proxy_suite_test.go:17`).
Match the neighboring suite instead of requiring one framework for all packages.

## Behavioral Regression Checklist

For watch-loader changes, preserve duplicate-GVK rejection and validation
after decoding (`internal/ansible/watches/watches.go:345`).
For parameter changes, check spec conversion, runtime metadata, watch overrides,
and finalizer overrides (`internal/ansible/runner/runner.go:336`).
For lifecycle changes, check a missing CR, errors without stats events,
and successful finalizer removal (`internal/ansible/controller/reconcile.go:68`).
For ownership changes, exercise both owner-reference and owner-annotation paths
(`internal/ansible/proxy/inject_owner.go:143`).
For event filtering, preserve generation predicates and the optional annotation
predicate (`internal/ansible/controller/controller.go:105`).

These are change-driven review checks, not a claim that every branch above
already has complete regression coverage.

## Cluster-Based Suites

The e2e setup builds the binary, installs kubectl, and creates or reuses a kind
cluster named by `KIND_CLUSTER` (`Makefile:139`, `Makefile:142`).
`cluster-create` exports that cluster's kubeconfig (`Makefile:147`).
Run only in an environment where changing the active kubeconfig is acceptable.

The Ansible target builds an image and invokes
`go test ./test/e2e/ansible -v -ginkgo.v` (`Makefile:163`).
The molecule target additionally installs the binary, generates a molecule
sample, and runs `hack/tests/e2e-ansible-molecule.sh` (`Makefile:165`).
The root image recipe uses Docker buildx (`Makefile:100`).

The GitHub molecule job installs Python 3.12 and `ansible-core~=2.17.4`
before invoking the target (`.github/workflows/test-ansible.yml:32`, `.github/workflows/test-ansible.yml:37`).
Those are workflow prerequisites, not an assertion about the downstream
image's Python/Ansible versions.

Teardown is explicit: `make test-e2e-teardown` deletes the kind cluster and
removes the configured kubeconfig path (`Makefile:155`).
Review that path before running teardown against an existing environment.

## Generated Samples and Sanity

`make generate` deletes `testdata/` before recreating samples (`Makefile:52`).
Change generators/templates first; inspect all sample diffs before committing.
`test-sanity` expects generator and fix output to leave no diff (`Makefile:115`, `Makefile:116`).
It is unsuitable for preserving unrelated unstaged edits.

## Documentation-Only Changes

There is no working root documentation-link target in this checkout: `test-docs`
names missing legacy inputs (`Makefile:124`).
Use available documentation validation, parse `.coderabbit.yaml`, resolve local
references, check external links, and run `git diff --check` for doc-only edits.
Go compilation and cluster suites do not exercise Markdown content.

For generic development practices, use the
[platform guides](https://github.com/openshift/enhancements/tree/master/dev-guide).
For build/generator caveats, see [DEVELOPMENT.md](DEVELOPMENT.md).
