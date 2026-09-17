# Ansible Operator Plugins -- Testing Guide

## Test Frameworks and Assertion Libraries

This repository uses two testing approaches side by side:

- **Ginkgo/Gomega (BDD style):** Used for handler tests, flags, metrics, proxy,
  version, and all E2E tests. Packages using Ginkgo dot-import both `ginkgo/v2`
  and `gomega`.
- **Standard `testing` + `testify/assert`:** Used for controller reconcile tests,
  watches, runner, paramconv, k8sutil, and status utilities.
- **Do not mix** Ginkgo and testify within the same package.

## Suite Files

Every Ginkgo package requires a `*_suite_test.go` file named
`<concern>_suite_test.go`. The suite file must define a `TestXxx(t *testing.T)`
function that calls `RegisterFailHandler(Fail)` then `RunSpecs`.

## Short Mode and Test Skipping

Unit tests run with `-short` flag via `make test-unit`. Tests requiring a live
cluster must guard with:

- Standard tests: `if testing.Short() { t.Skip("...") }`
- Ginkgo specs: `if testing.Short() { Skip("...") }` inside the `It` block
- E2E tests are excluded from `test-unit` via package path filtering (`grep -v test/`)

## Table-Driven Tests

Standard-library tests use table-driven patterns with named test cases.
Always include a `Name` field. Use `ShouldError bool` for error expectation
fields, matching existing convention.

## Fake Runner

Use `internal/ansible/runner/fake.Runner` to stub the Ansible runner interface:

- `JobEvents []eventapi.JobEvent` -- events returned from `Run()`
- `Error error` -- makes `Run()` return this error
- `Finalizer string` -- returned by `GetFinalizer()`
- `Stdout string` -- stdout content for the run result

Do not create new runner mock implementations; use and extend this fake.

## Fake Client (controller-runtime)

Use `sigs.k8s.io/controller-runtime/pkg/client/fake` for unit-testing reconcilers.
When checking status subresource updates, register objects with `WithStatusSubresource`.

## envtest

The `handler` package uses `envtest.Environment` for integration tests. Start in
`BeforeSuite`, stop in `AfterSuite`.

## Logging in Tests

Handler tests capture log output to a shared `bytes.Buffer` set via
`zap.New(zap.WriteTo(&logBuffer), zap.UseDevMode(true))`. Reset before each
assertion. Verify content using `MatchRegexp`.

## Test Data

Static fixtures live in `testdata/` directories adjacent to test files:

- `internal/ansible/watches/testdata/` -- YAML fixtures for watch loading
- `internal/ansible/runner/testdata/` -- playbooks and roles for runner tests
- `testdata/memcached-molecule-operator/` -- full sample operator for E2E

Template-based fixtures are rendered at test time and cleaned up with `defer os.Remove`.

## E2E Test Infrastructure

### Test Utilities (`pkg/testutils/`)

- `command.CommandContext` -- wraps exec with dir/env/stdin
- `kubernetes.Kubectl` -- kubectl command interface
- `sample.Sample` -- scaffolded operator project interface
- `e2e/operator` -- BuildOperatorImage, DeployOperator, UndeployOperator, InstallCRDs
- `e2e/kind` -- Kind cluster detection and image loading
- `e2e/prometheus` -- Prometheus operator install/uninstall
- `e2e/metrics` -- metrics scraping and verification

### E2E Test Lifecycle

1. `BeforeSuite`: generate sample project, configure kubectl, build and load operator image
2. `BeforeEach`: install CRDs, deploy operator
3. `It`: apply CRs, poll with `Eventually`, check logs/status/metrics
4. `AfterEach`: delete CRs, undeploy operator
5. `AfterSuite`: uninstall Prometheus, remove docker image, remove test directory

## Key Conventions

1. In Ginkgo tests, structure as `Describe` > `Context`/`When` > `It`. Use `BeforeEach` for per-spec setup.
2. Use `By("description")` in Ginkgo specs for test step documentation.
3. Unstructured objects in reconciler tests must include `apiVersion`, `kind`, and `metadata`.
4. Clean up env var changes with `defer os.Unsetenv` or `t.Setenv`.
5. E2E tests check `api-resources` for `servicemonitors` to avoid duplicate Prometheus installs.
