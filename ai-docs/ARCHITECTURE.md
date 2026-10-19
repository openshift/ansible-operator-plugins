# Architecture

## Repository Layout

This repository combines the Ansible runtime, a scaffolding library, and downstream
image inputs; do not treat it as one installed cluster operator.
See [the project overview](../README.md) and [downstream overview](../openshift/README.md).

```text
cmd/ansible-operator/           Runtime CLI, not the Operator SDK CLI
internal/cmd/ansible-operator/  run/version command implementation
internal/ansible/              Watch, reconcile, runner, proxy, and event logic
pkg/plugins/ansible/v1/        Kubebuilder plugin and scaffold templates
pkg/testutils/                 Reusable sample and e2e helpers
hack/generate/samples/         Sample generation drivers
test/e2e/                     Integration scenarios against a cluster
testdata/                     Generated sample projects; change generators instead
images/ansible-operator/       Base-image inputs
openshift/                    Downstream image, module, and collection inputs
vendor/                       Root-module dependencies
openshift/vendor/             Downstream-module dependencies
```

The two vendor trees serve distinct modules; downstream layout is documented in
`openshift/README.md`. Sample regeneration is wired in `Makefile`.

## Key Domain Concepts

### Two entry surfaces

The runtime binary exposes `run` and `version`; it does not expose `init` or
`create api` (`cmd/ansible-operator/main.go`).
The separate `Plugin` implements Kubebuilder initialization and API creation
(`pkg/plugins/ansible/v1/plugin.go`).

The plugin identifies itself as `base.ansible` plus the default name qualifier,
has plugin version 1, and supports project configuration v3
(`pkg/plugins/ansible/v1/plugin.go`).
Do not infer the module's import path from the OpenShift repository URL:
the module identity remains Operator Framework (`go.mod`).

### End-to-end runtime flow

1. Cobra invokes the run command (`cmd/ansible-operator/main.go`).
2. Startup obtains Kubernetes configuration and creates manager options
   (`internal/cmd/ansible-operator/run/cmd.go`).
3. `watches.Load` reads configuration and builds watches
   (`internal/ansible/watches/watches.go`).
4. Startup creates a runner/controller for each configured watch
   (`internal/cmd/ansible-operator/run/cmd.go`).
5. `Reconcile` fetches the unstructured primary object, prepares status and
   runner credentials (`internal/ansible/controller/reconcile.go`).
6. The runner executes `ansible-runner` and exposes job events
   (`internal/ansible/runner/runner.go`).
7. Reconciliation consumes events, rereads the primary object, and finishes
   finalizer/status handling (`internal/ansible/controller/reconcile.go`).

## Component/Controller Details

### Startup boundaries

`run.NewCmd` validates that `--metrics-require-rbac` is not used with insecure
metrics (`internal/cmd/ansible-operator/run/cmd.go`).
Startup rejects using both legacy and replacement leader-election flags, and
both legacy and replacement metrics-address flags
(`internal/cmd/ansible-operator/run/cmd.go`).

`OPERATOR_NAME` is deprecated; an explicit `--leader-election-id` takes
precedence (`internal/cmd/ansible-operator/run/cmd.go`).
Namespace selection is translated into manager cache options by
`configureWatchNamespaces` (`internal/cmd/ansible-operator/run/cmd.go`).

### Watch-to-controller mapping

| Operation | Implementation and consequence |
|---|---|
| Load YAML | `watches.Load` expands environment references before unmarshalling (`internal/ansible/watches/watches.go`). |
| Reject ambiguity | Duplicate GVKs are rejected by the loader (`internal/ansible/watches/watches.go`). |
| Validate execution | Watch role/playbook and finalizer configuration are checked by `Watch.Validate` (`internal/ansible/watches/watches.go`). |
| Register type | `controller.Add` registers an unstructured type when absent (`internal/ansible/controller/controller.go`). |
| Name controller | Lowercase kind and version form the controller name (`internal/ansible/controller/controller.go`). |
| Select events | Generation/no-generation predicates form the default filter (`internal/ansible/controller/controller.go`). |
| Select labels | `parsePredicateSelector` adds the configured label-selector predicate (`internal/ansible/controller/controller.go`). |

### Shared utilities

| Symbol | Contract and location |
|---|---|
| `paramconv.MapToSnake` | Recursively converts map keys, including maps nested in arrays (`internal/ansible/paramconv/paramconv.go`). |
| `paramconv.MapToCamel` | Uses the same recursive traversal with `ToCamel` (`internal/ansible/paramconv/paramconv.go`). |
| `events.NewLoggingEventHandler` | Constructs a handler with a mutex (`internal/ansible/events/log_events.go`). |
| `events.GetVerbosity` | Positive CR annotation overrides positive `ANSIBLE_VERBOSITY`; otherwise zero (`internal/ansible/events/log_events.go`). |

The logging handler's `Tasks`, `Everything`, and `Nothing` modes differ:
`Nothing` returns immediately, `Tasks` branches on task events, and `Everything`
logs event data (`internal/ansible/events/log_events.go`).
This is separate from runner verbosity selection; do not conflate output filtering
with the arguments sent to Ansible (`internal/ansible/runner/runner.go`).

## Resource Management

### Writes are not uniform

| Writer | Method and boundary |
|---|---|
| CR finalizer | `Client.Update` on the primary object (`internal/ansible/controller/reconcile.go`). |
| Runtime CR status | `Client.Status().Update` (`internal/ansible/controller/reconcile.go`). |
| Ansible-managed resources | HTTP proxy forwards requests; middleware can inject owner information (`internal/ansible/proxy/proxy.go`, `internal/ansible/proxy/inject_owner.go`). |

Do not describe this runtime as an SSA-only reconciler. Ansible task/module
choices and proxy request handling are a different layer from primary-CR updates.
Trace both when changing lifecycle behavior (`internal/ansible/controller/reconcile.go`).

### Ownership and dependent watches

The proxy installs owner-injection middleware only when `OwnerInjection` is true
(`internal/ansible/proxy/proxy.go`).
The injection handler asks `k8sutil.SupportsOwnerReference` whether to use an
owner reference; its alternate path adds owner annotations
(`internal/ansible/proxy/inject_owner.go`).
Dependent-watch registration occurs through `addWatchToController`
(`internal/ansible/proxy/inject_owner.go`).

The proxy strips the incoming authorization header before its forwarding path
adds authentication (`internal/ansible/proxy/proxy.go`).
Do not assume runner-facing credentials are the same as direct API credentials:
reconciliation creates a kubeconfig pointing at `http://localhost:8888`
(`internal/ansible/controller/reconcile.go`).

### Image inputs

`IMAGE_REPO`, `IMAGE_TAG`, and the `image/%` build recipe belong to the root
image-build workflow (`Makefile`).
Downstream image build inputs live under `openshift/`; use its own build and
requirements documentation rather than assuming the root image recipe is identical
([downstream overview](../openshift/README.md), [requirements guide](../openshift/hack/generate_requirements.md)).

## Feature Gates

Watch options, rather than a platform FeatureGate lookup, control the behaviors
listed here; their defaults are defined in `internal/ansible/watches/watches.go`.

| Watch option | Default | Runtime use |
|---|---|---|
| `manageStatus` | true | Gates status calls in `Reconcile` (`internal/ansible/controller/reconcile.go`). |
| `watchDependentResources` | true | Passed at controller-map setup (`internal/cmd/ansible-operator/run/cmd.go`). |
| `watchClusterScopedResources` | false | Passed at controller-map setup (`internal/cmd/ansible-operator/run/cmd.go`). |
| `watchAnnotationsChanges` | false | Adds an annotation-change predicate (`internal/ansible/controller/controller.go`). |
| `snakeCaseParameters` | true | Selects spec-key conversion (`internal/ansible/runner/runner.go`). |
| `markUnsafe` | false | Wraps parameter strings before execution (`internal/ansible/runner/runner.go`). |

`watches.Load` supplies command-line concurrency/verbosity defaults before
decoding watches (`internal/ansible/watches/watches.go`).
Per-GVK concurrency environment settings are handled by
`getIntegerEnvMaxReconcile`, with the newer setting preferred over legacy workers
(`internal/ansible/watches/watches.go`).

## Error Classification

| Situation | Result |
|---|---|
| Missing runner executable | `Run` returns the `exec.LookPath` error (`internal/ansible/runner/runner.go`). |
| Missing primary CR | NotFound is handled without a retry error (`internal/ansible/controller/reconcile.go`). |
| No stats event | Returns `did not receive playbook_on_stats event` (`internal/ansible/controller/reconcile.go`). |
| Unignored, unrescued failed task | Collected into failure messages (`internal/ansible/controller/reconcile.go`). |
| Failed run | Returns an error whether or not status management is enabled (`internal/ansible/controller/reconcile.go`). |
| Deletion starts during execution and a finalizer is configured | Requeues after five seconds for finalization (`internal/ansible/controller/reconcile.go`). |

Status helpers are `markRunning`, `markError`, and `markDone`; they operate on
the CR status, not a ClusterOperator object
(`internal/ansible/controller/reconcile.go`).

## OpenShift Integration Points

| Integration | Local evidence and scope |
|---|---|
| Downstream base image | `openshift/README.md` describes the OpenShift image purpose. |
| CI build root | `.ci-operator.yaml` selects the release Go builder image. |
| Vendored downstream build tooling | `openshift/Makefile` includes build-machinery dependency targets. |
| Kubernetes clients | Root dependencies are declared in `go.mod`. |
| Kubebuilder plugin | Plugin interfaces are imported in `pkg/plugins/ansible/v1/plugin.go`. |

These are integration boundaries, not evidence that this repository implements
CVO, CNO, or OLM reconciliation. Follow the runtime startup map before adding
component-specific claims (`internal/cmd/ansible-operator/run/cmd.go`).

## Generated Code Inventory

| Output | Source / regeneration |
|---|---|
| `testdata/` samples | NEVER hand-edit; `make generate` removes and recreates them (`Makefile`). |
| `vendor/` | Root module dependencies; see downstream layout (`openshift/README.md`). |
| `openshift/vendor/` | Downstream module dependencies (`openshift/README.md`). |
| Downstream requirements files | Use `make -f openshift/Makefile generate-requirements` (`openshift/Makefile`). |
| `openshift/release/ansible/ansible_collections/` | Use `make -f openshift/Makefile update-collections` (`openshift/Makefile`). |

The root generator also invokes `go generate ./...`; inspect directives when
adding generation steps rather than inventing a new target (`Makefile`).

## API Behavioral Contracts

`runner.makeParameters` starts from the CR spec, optionally converts keys,
and then adds `ansible_operator_meta` plus raw-object/raw-spec variables
(`internal/ansible/runner/runner.go`).
Watch variables overwrite preceding parameters; finalizer variables overwrite
them again only during a matching finalizer run
(`internal/ansible/runner/runner.go`).

The reconcile-period annotation is parsed as a duration and overrides the watch
period (`internal/ansible/controller/reconcile.go`).
Do not remove the post-run APIReader fetch: the code explicitly rereads the
primary CR after Ansible before finalizer/status changes
(`internal/ansible/controller/reconcile.go`).
Finalizer removal requires a successful run in the deletion path
(`internal/ansible/controller/reconcile.go`).

## Form Factor Behavior

The startup path selects watched namespaces and configures a manager cache
(`internal/cmd/ansible-operator/run/cmd.go`).
No topology-specific guarantees are asserted here for SNO, hosted control planes,
or MicroShift; this document's runtime contracts concern configured watches.

## Design References

### Keep runtime and scaffolding separate

The binary runs projects while the plugin scaffolds them. Preserve this split
when locating a change: a new CLI template belongs to the plugin, not the runtime
command (`cmd/ansible-operator/main.go`, `pkg/plugins/ansible/v1/plugin.go`).
The public [overview](../README.md) explains the Operator SDK relationship.

### Preserve downstream build inputs independently

The public [downstream guide](../openshift/README.md) describes a mirror plus
downstream artifacts. Root and downstream dependency trees are separate inputs
(`openshift/README.md`); changes must follow the relevant module/build path.
The [requirements guide](../openshift/hack/generate_requirements.md) covers Python inputs.

## Platform Documentation

- [Development guides](https://github.com/openshift/enhancements/tree/master/dev-guide)
- [Enhancement process](https://github.com/openshift/enhancements/tree/master/guidelines)
- [Shared conventions](https://github.com/openshift/enhancements/blob/master/CONVENTIONS.md)

## SME Review Recommended

Maintainers should assess downstream release policy and supported topology matrices;
source tracing here is not a support commitment or a replacement for release guidance.
