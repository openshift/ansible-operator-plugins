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
`openshift/README.md:15`. Sample regeneration is wired in `Makefile:52`.

## Key Domain Concepts

### Two entry surfaces

The runtime binary exposes `run` and `version`; it does not expose `init` or
`create api` (`cmd/ansible-operator/main.go:27`).
The separate `Plugin` implements Kubebuilder initialization and API creation
(`pkg/plugins/ansible/v1/plugin.go:34`).

The plugin identifies itself as `base.ansible` plus the default name qualifier,
has plugin version 1, and supports project configuration v3
(`pkg/plugins/ansible/v1/plugin.go:25`).
Do not infer the module's import path from the OpenShift repository URL:
the module identity remains Operator Framework (`go.mod:1`).

### End-to-end runtime flow

1. Cobra invokes the run command (`cmd/ansible-operator/main.go:37`).
2. Startup obtains Kubernetes configuration and creates manager options
   (`internal/cmd/ansible-operator/run/cmd.go:95`).
3. `watches.Load` reads configuration and builds watches
   (`internal/ansible/watches/watches.go:313`).
4. Startup creates a runner/controller for each configured watch
   (`internal/cmd/ansible-operator/run/cmd.go:171`).
5. `Reconcile` fetches the unstructured primary object, prepares status and
   runner credentials (`internal/ansible/controller/reconcile.go:68`).
6. The runner executes `ansible-runner` and exposes job events
   (`internal/ansible/runner/runner.go:182`).
7. Reconciliation consumes events, rereads the primary object, and finishes
   finalizer/status handling (`internal/ansible/controller/reconcile.go:170`).

## Component/Controller Details

### Startup boundaries

`run.NewCmd` validates that `--metrics-require-rbac` is not used with insecure
metrics (`internal/cmd/ansible-operator/run/cmd.go:78`).
Startup rejects using both legacy and replacement leader-election flags, and
both legacy and replacement metrics-address flags
(`internal/cmd/ansible-operator/run/cmd.go:128`).

`OPERATOR_NAME` is deprecated; an explicit `--leader-election-id` takes
precedence (`internal/cmd/ansible-operator/run/cmd.go:113`).
Namespace selection is translated into manager cache options by
`configureWatchNamespaces` (`internal/cmd/ansible-operator/run/cmd.go:337`).

### Watch-to-controller mapping

| Operation | Implementation and consequence |
|---|---|
| Load YAML | `watches.Load` expands environment references before unmarshalling (`internal/ansible/watches/watches.go:322`). |
| Reject ambiguity | Duplicate GVKs are rejected by the loader (`internal/ansible/watches/watches.go:345`). |
| Validate execution | Watch role/playbook and finalizer configuration are checked by `Watch.Validate` (`internal/ansible/watches/watches.go:264`). |
| Register type | `controller.Add` registers an unstructured type when absent (`internal/ansible/controller/controller.go:80`). |
| Name controller | Lowercase kind and version form the controller name (`internal/ansible/controller/controller.go:95`). |
| Select events | Generation/no-generation predicates form the default filter (`internal/ansible/controller/controller.go:105`). |
| Select labels | `parsePredicateSelector` adds the configured label-selector predicate (`internal/ansible/controller/controller.go:140`). |

### Shared utilities

| Symbol | Contract and location |
|---|---|
| `paramconv.MapToSnake` | Recursively converts map keys, including maps nested in arrays (`internal/ansible/paramconv/paramconv.go:171`). |
| `paramconv.MapToCamel` | Uses the same recursive traversal with `ToCamel` (`internal/ansible/paramconv/paramconv.go:206`). |
| `events.NewLoggingEventHandler` | Constructs a handler with a mutex (`internal/ansible/events/log_events.go:141`). |
| `events.GetVerbosity` | Positive CR annotation overrides positive `ANSIBLE_VERBOSITY`; otherwise zero (`internal/ansible/events/log_events.go:149`). |

The logging handler's `Tasks`, `Everything`, and `Nothing` modes differ:
`Nothing` returns immediately, `Tasks` branches on task events, and `Everything`
logs event data (`internal/ansible/events/log_events.go:54`).
This is separate from runner verbosity selection; do not conflate output filtering
with the arguments sent to Ansible (`internal/ansible/runner/runner.go:63`).

## Resource Management

### Writes are not uniform

| Writer | Method and boundary |
|---|---|
| CR finalizer | `Client.Update` on the primary object (`internal/ansible/controller/reconcile.go:112`, `internal/ansible/controller/reconcile.go:251`). |
| Runtime CR status | `Client.Status().Update` (`internal/ansible/controller/reconcile.go:321`, `internal/ansible/controller/reconcile.go:436`). |
| Ansible-managed resources | HTTP proxy forwards requests; middleware can inject owner information (`internal/ansible/proxy/proxy.go:96`, `internal/ansible/proxy/inject_owner.go:52`). |

Do not describe this runtime as an SSA-only reconciler. Ansible task/module
choices and proxy request handling are a different layer from primary-CR updates.
Trace both when changing lifecycle behavior (`internal/ansible/controller/reconcile.go:146`).

### Ownership and dependent watches

The proxy installs owner-injection middleware only when `OwnerInjection` is true
(`internal/ansible/proxy/proxy.go:148`).
The injection handler asks `k8sutil.SupportsOwnerReference` whether to use an
owner reference; its alternate path adds owner annotations
(`internal/ansible/proxy/inject_owner.go:143`).
Dependent-watch registration occurs through `addWatchToController`
(`internal/ansible/proxy/inject_owner.go:181`).

The proxy strips the incoming authorization header before its forwarding path
adds authentication (`internal/ansible/proxy/proxy.go:145`).
Do not assume runner-facing credentials are the same as direct API credentials:
reconciliation creates a kubeconfig pointing at `http://localhost:8888`
(`internal/ansible/controller/reconcile.go:146`).

### Image inputs

`IMAGE_REPO`, `IMAGE_TAG`, and the `image/%` build recipe belong to the root
image-build workflow (`Makefile:36`, `Makefile:90`).
Downstream image build inputs live under `openshift/`; use its own build and
requirements documentation rather than assuming the root image recipe is identical
([downstream overview](../openshift/README.md), [requirements guide](../openshift/hack/generate_requirements.md)).

## Feature Gates

Watch options, rather than a platform FeatureGate lookup, control the behaviors
listed here; their defaults are defined in `internal/ansible/watches/watches.go:71`.

| Watch option | Default | Runtime use |
|---|---|---|
| `manageStatus` | true | Gates status calls in `Reconcile` (`internal/ansible/controller/reconcile.go:131`). |
| `watchDependentResources` | true | Passed at controller-map setup (`internal/cmd/ansible-operator/run/cmd.go:190`). |
| `watchClusterScopedResources` | false | Passed at controller-map setup (`internal/cmd/ansible-operator/run/cmd.go:190`). |
| `watchAnnotationsChanges` | false | Adds an annotation-change predicate (`internal/ansible/controller/controller.go:110`). |
| `snakeCaseParameters` | true | Selects spec-key conversion (`internal/ansible/runner/runner.go:347`). |
| `markUnsafe` | false | Wraps parameter strings before execution (`internal/ansible/runner/runner.go:355`). |

`watches.Load` supplies command-line concurrency/verbosity defaults before
decoding watches (`internal/ansible/watches/watches.go:313`).
Per-GVK concurrency environment settings are handled by
`getIntegerEnvMaxReconcile`, with the newer setting preferred over legacy workers
(`internal/ansible/watches/watches.go:480`).

## Error Classification

| Situation | Result |
|---|---|
| Missing runner executable | `Run` returns the `exec.LookPath` error (`internal/ansible/runner/runner.go:183`). |
| Missing primary CR | NotFound is handled without a retry error (`internal/ansible/controller/reconcile.go:75`). |
| No stats event | Returns `did not receive playbook_on_stats event` (`internal/ansible/controller/reconcile.go:217`). |
| Unignored, unrescued failed task | Collected into failure messages (`internal/ansible/controller/reconcile.go:206`). |
| Failed run | Returns an error whether or not status management is enabled (`internal/ansible/controller/reconcile.go:260`). |
| Deletion starts during execution and a finalizer is configured | Requeues after five seconds for finalization (`internal/ansible/controller/reconcile.go:256`). |

Status helpers are `markRunning`, `markError`, and `markDone`; they operate on
the CR status, not a ClusterOperator object
(`internal/ansible/controller/reconcile.go:295`).

## OpenShift Integration Points

| Integration | Local evidence and scope |
|---|---|
| Downstream base image | `openshift/README.md:3` describes the OpenShift image purpose. |
| CI build root | `.ci-operator.yaml:1` selects the release Go builder image. |
| Vendored downstream build tooling | `openshift/Makefile:4` includes build-machinery dependency targets. |
| Kubernetes clients | Root dependencies are declared in `go.mod:22`. |
| Kubebuilder plugin | Plugin interfaces are imported in `pkg/plugins/ansible/v1/plugin.go:18`. |

These are integration boundaries, not evidence that this repository implements
CVO, CNO, or OLM reconciliation. Follow the runtime startup map before adding
component-specific claims (`internal/cmd/ansible-operator/run/cmd.go:95`).

## Generated Code Inventory

| Output | Source / regeneration |
|---|---|
| `testdata/` samples | NEVER hand-edit; `make generate` removes and recreates them (`Makefile:52`). |
| `vendor/` | Root module dependencies; see downstream layout (`openshift/README.md:19`). |
| `openshift/vendor/` | Downstream module dependencies (`openshift/README.md:20`). |
| Downstream requirements files | Use `make -f openshift/Makefile generate-requirements` (`openshift/Makefile:24`). |
| `openshift/release/ansible/ansible_collections/` | Use `make -f openshift/Makefile update-collections` (`openshift/Makefile:37`). |

The root generator also invokes `go generate ./...`; inspect directives when
adding generation steps rather than inventing a new target (`Makefile:55`).

## API Behavioral Contracts

`runner.makeParameters` starts from the CR spec, optionally converts keys,
and then adds `ansible_operator_meta` plus raw-object/raw-spec variables
(`internal/ansible/runner/runner.go:336`).
Watch variables overwrite preceding parameters; finalizer variables overwrite
them again only during a matching finalizer run
(`internal/ansible/runner/runner.go:373`).

The reconcile-period annotation is parsed as a duration and overrides the watch
period (`internal/ansible/controller/reconcile.go:86`).
Do not remove the post-run APIReader fetch: the code explicitly rereads the
primary CR after Ansible before finalizer/status changes
(`internal/ansible/controller/reconcile.go:232`).
Finalizer removal requires a successful run in the deletion path
(`internal/ansible/controller/reconcile.go:248`).

## Form Factor Behavior

The startup path selects watched namespaces and configures a manager cache
(`internal/cmd/ansible-operator/run/cmd.go:337`).
No topology-specific guarantees are asserted here for SNO, hosted control planes,
or MicroShift; this document's runtime contracts concern configured watches.

## Design References

### Keep runtime and scaffolding separate

The binary runs projects while the plugin scaffolds them. Preserve this split
when locating a change: a new CLI template belongs to the plugin, not the runtime
command (`cmd/ansible-operator/main.go:37`, `pkg/plugins/ansible/v1/plugin.go:34`).
The public [overview](../README.md) explains the Operator SDK relationship.

### Preserve downstream build inputs independently

The public [downstream guide](../openshift/README.md) describes a mirror plus
downstream artifacts. Root and downstream dependency trees are separate inputs
(`openshift/README.md:15`); changes must follow the relevant module/build path.
The [requirements guide](../openshift/hack/generate_requirements.md) covers Python inputs.
See the [design catalog](ENHANCEMENTS.md) for a historical downstream SDK proposal;
its proposed branch strategy is not a description of this checkout.

## Platform Documentation

- [Development guides](https://github.com/openshift/enhancements/tree/master/dev-guide)
- [Enhancement process](https://github.com/openshift/enhancements/tree/master/guidelines)
- [Shared conventions](https://github.com/openshift/enhancements/blob/master/CONVENTIONS.md)

## SME Review Recommended

Maintainers should assess downstream release policy and supported topology matrices;
source tracing here is not a support commitment or a replacement for release guidance.
