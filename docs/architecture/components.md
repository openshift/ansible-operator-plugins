# Architecture: Components and Integration

## Architecture Overview

This project bridges Ansible automation with Kubernetes controllers via
controller-runtime. The main loop: a `watches.yaml` file maps GVKs to Ansible
playbooks/roles. For each watch entry, a controller-runtime controller is
created that, on reconcile, shells out to `ansible-runner`, consumes job events
via a Unix-domain-socket HTTP API, and updates the CR's status conditions.

## Watches Configuration (internal/ansible/watches/)

1. Every Watch must specify exactly one of `playbook` or `role`, never both.
2. Default values: `manageStatus: true`, `watchDependentResources: true`,
   `watchClusterScopedResources: false`, `snakeCaseParameters: true`,
   `maxRunnerArtifacts: 20`, `ansibleVerbosity: 2`.
3. Watches supports `${VAR}` environment variable interpolation via `os.Expand`.
4. Per-GVK concurrency: `MAX_CONCURRENT_RECONCILES_<KIND>_<GROUP>` (dots → underscores, uppercased). Legacy `WORKER_<KIND>_<GROUP>` still works.
5. Role paths support FQCN format resolved against `ANSIBLE_COLLECTIONS_PATH`.
6. The `selector` field produces a `LabelSelectorPredicate` that filters which CRs trigger reconciliation.

## Controller-Runtime Integration (internal/ansible/controller/)

7. Controllers are named `<kind>-<version>-controller` (lowercased), registered via `controller.New`.
8. Unregistered GVKs are dynamically added to the scheme as `unstructured.Unstructured`.
9. Default predicate stack: `GenerationChangedPredicate` OR `NoGenerationPredicate`. If `watchAnnotationsChanges` is true, `AnnotationChangedPredicate` is OR'd in.
10. The primary watch uses `LoggingEnqueueRequestForObject` for metrics + logging.
11. `controller.Add` returns a `*controller.Controller` pointer stored in the `ControllerMap` so the proxy can dynamically add dependent watches.

## Reconciliation Loop (internal/ansible/controller/reconcile.go)

12. `APIReader` (direct API reads, bypassing cache) is used in two places: `markRunning`/`markError`/`markDone` call it to refresh the object immediately before `Client.Status().Update`, and after `Runner.Run` completes the reconciler calls it again to re-read the CR from the API server (ansible may have modified it via the proxy during the run).
13. Per-CR reconcile period override: annotate with `ansible.sdk.operatorframework.io/reconcile-period: <duration>`.
14. Finalizer lifecycle: added on first reconcile if configured, removed only after a successful finalizer run on deletion.
15. If the CR has no `spec`, an empty map is injected so ansible parameters work for Secrets/ConfigMaps.
16. The `requeue_after` module in ansible overrides `RequeueAfter` when detected from event data.
17. Failed tasks (`runner_on_failed`) that are neither `IgnoreError()` nor `Rescued()` produce failure messages.
18. A `playbook_on_stats` event must be present somewhere in the event stream (it is recorded as it is seen, then checked after the stream closes). If missing, reconciliation fails.

## Status Management (internal/ansible/controller/status/)

19. Three condition types: `Running`, `Failure`, `Successful`. When `manageStatus` is true, the reconciler transitions between these.
20. `SetCondition` is a no-op when `Type`, `Status`, and `Reason` are unchanged, except for `FailureConditionType` which always updates.
21. Status is serialized via `GetJSONMap()` (marshal/unmarshal cycle) because `unstructured.Unstructured` has special DeepCopy rules.

## Ansible Runner Integration (internal/ansible/runner/)

22. The `Runner` interface: `Run(ident, *unstructured.Unstructured, kubeconfig) (RunResult, error)` and `GetFinalizer() (string, bool)`.
23. `ansible-runner` must be on `$PATH`. Detected via `exec.LookPath` at run time, not startup.
24. Input directory layout: `/tmp/ansible-operator/runner/<group>/<version>/<kind>/<namespace>/<name>/` with `env/`, `project/`, `inventory/`.
25. Parameters in `env/extravars`: snake_cased spec, `ansible_operator_meta`, `_<group>_<kind>`, watch vars, finalizer vars.
26. The `markUnsafe` feature wraps all string values as `{"__ansible_unsafe": "<value>"}`.
27. After each run, a `latest` symlink is created under `artifacts/`.

## Event API (internal/ansible/runner/eventapi/)

28. Each reconcile creates a Unix socket at `/tmp/ansibleoperator-<ident>` and starts an HTTP server.
29. The events channel is buffered with capacity 1000. A 10-second write timeout prevents blocking.
30. Status events (those without a UUID) are silently dropped; only JobEvents with a UUID are forwarded.

## Proxy Server (internal/ansible/proxy/)

31. Runs on localhost (default port 8888). Ansible connects via a generated kubeconfig.
32. Owner reference injection on POST; falls back to annotation-based ownership for cross-namespace/cluster-scoped resources.
33. Cache response handler serves GETs from informer cache (`X-Cache: HIT`). Cache timeout is 6 seconds.
34. Dependent watch registration on resource creation.
35. The `blacklist` field in watches.yaml prevents specific GVKs from being watched or cached.

## Event Handler Wrappers (internal/ansible/handler/)

36. Three handler wrappers, all adding structured logging at V(1):
    - `LoggingEnqueueRequestForObject`: primary resource watches
    - `LoggingEnqueueRequestForAnnotation`: annotation-based dependent watches
    - `EnqueueRequestForOwnerWithLogging`: owner-based dependent watches (full reimplementation)

## Prometheus Metrics (internal/ansible/metrics/)

37. Built-in metrics (subsystem `ansible_operator`): `reconcile_result` (Gauge), `reconciles` (Histogram), `build_info` (Gauge).
38. Registered with controller-runtime's `metrics.Registry`, not the default prometheus registry.
39. User-defined metrics via the API server on port 5050. Type changes are rejected after initial registration.
40. All metric operations wrapped with `recover()` to prevent operator crashes.

## Kubeconfig Generation (internal/ansible/proxy/kubeconfig/)

41. A temporary kubeconfig per reconcile, pointing to the proxy (`http://localhost:8888`). Owner reference base64-encoded into Basic Auth username.
42. Uses `insecure-skip-tls-verify: true` for the local proxy connection.

## ControllerMap (internal/ansible/proxy/controllermap/)

43. Thread-safe `map[GVK]*Contents` bridging controllers and the proxy. All access is mutex-protected.
44. `WatchMap` tracks which dependent GVKs already have watches registered, preventing duplicates.

## Plugin and Scaffolding (pkg/plugins/ansible/v1/)

45. Implements the kubebuilder plugin interface for scaffolding Ansible-based operators.
46. Templates in `scaffolds/internal/templates/` generate: Dockerfile, watches.yaml, molecule tests, RBAC manifests, kustomize config.
47. Scaffold output goes to `testdata/` via `make generate`. Edit templates, never testdata directly.

