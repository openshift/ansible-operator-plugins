# Watches and API Contracts

## watches.yaml Contract

Each entry requires `group`, `version`, `kind`, and exactly one of `playbook` or `role`. Version and Kind are mandatory; Group may be empty.

- Duplicate GVKs in the same file cause a load error.
- Environment variables are expanded using `${VAR}` syntax. Undefined variables are left as literal `${VAR}`.
- Defaults: `manageStatus: true`, `watchDependentResources: true`, `watchClusterScopedResources: false`, `snakeCaseParameters: true`, `maxRunnerArtifacts: 20`, `reconcilePeriod: 0s`, `watchAnnotationsChanges: false`, `markUnsafe: false`.

### Per-GVK Environment Variable Overrides

- `MAX_CONCURRENT_RECONCILES_{KIND}_{GROUP}` overrides max concurrent reconciles (dots replaced with underscores, uppercased).
- `WORKER_{KIND}_{GROUP}` is the deprecated equivalent. If both are set, `MAX_CONCURRENT_RECONCILES_*` wins.
- `ANSIBLE_VERBOSITY_{KIND}_{GROUP}` overrides verbosity (valid range: 0-7).

### Finalizer Contract

- A finalizer must have a non-empty `name` field.
- It must specify a `role`, `playbook`, or non-empty `vars`. If none are provided, validation fails.
- If only `vars` is set (no role/playbook), the main watch's role/playbook is used as the finalizer command.

### Role Path Resolution

Role paths support FQCN format (`namespace.collection.role`), resolved against `ANSIBLE_COLLECTIONS_PATH` or default paths (`/usr/share/ansible/collections`, `~/.ansible/collections`).

The `selector` field in watches.yaml produces a `LabelSelectorPredicate` that filters which CRs trigger reconciliation.

## Metrics API Server (internal/ansible/apiserver)

- Runs on `localhost:5050` and exposes a single endpoint: `POST /metrics`.
- Only POST is accepted; all other methods return `405 Method Not Allowed`.
- Request body must be JSON-decodable into a `metrics.UserMetric` struct. Malformed JSON returns `400 Bad Request`.
- A valid request must contain exactly one metric type (`counter`, `gauge`, `histogram`, or `summary`). Zero or more than one returns 400.
- Metrics are auto-registered with controller-runtime's Prometheus registry on first use. Once a metric name is registered with a type, that type is immutable.

### UserMetric JSON Field Mapping

The JSON field name for the metric description is `description`, not `help`:
```json
{"name": "my_metric", "description": "A help string", "counter": {"increment": true}}
```

## REST Proxy Server (internal/ansible/proxy)

### Handler Chain Ordering

The proxy applies HTTP handler middleware in a strict order:
1. **cacheResponseHandler** (outermost for GET) -- intercepts GETs and serves from informer cache when possible
2. **injectOwnerReferenceHandler** -- intercepts POSTs and adds ownerReferences or owner annotations
3. **removeAuthorizationHeader** -- strips the Authorization header so the proxy can re-inject its own
4. **RequestLogHandler** (optional) -- logs request method, URI, and body
5. **reverse proxy to real API server** (innermost)

### Cache Response Contract

- Only GET requests are candidates for cache lookup. All other methods pass through.
- Cache responses set `Content-Type: application/json` and `X-Cache: HIT`.
- Cache lookup is skipped for: subresources other than `status`, virtual resources, blacklisted GVKs, namespaces not in the watched set, and paths matching `AutoSkipCacheREList` (exec, attach).
- Cache operations use a 6-second context timeout. If the informer cache does not respond in time, the request falls through to the real API server.

### Owner Reference Injection Contract

- Owner references are only injected on POST (create) requests, never on subresource POSTs.
- The owner identity is extracted from the HTTP Basic Auth username field, which is a base64-encoded JSON `NamespacedOwnerReference`.
- When cross-namespace or cross-scope ownership prevents a native `ownerReference`, the proxy falls back to operator-lib owner annotations.
- After injecting, a dependent watch is registered on the controller so that changes to the created resource trigger owner reconciliation.

## Event API (internal/ansible/runner/eventapi)

### Unix Socket Protocol

- Each ansible-runner invocation gets its own `EventReceiver` listening on `/tmp/ansibleoperator-{ident}`.
- The receiver accepts POST requests at `/events/` only. Non-POST returns `405`; wrong path returns `404`.
- Request Content-Type must be `application/json`. Otherwise returns `415`.
- Malformed JSON body returns `400`. Server errors return `500`.
- Successful event receipt returns `204 No Content`.
- After the receiver is stopped, further POSTs return `410 Gone`.

### Event Filtering

- Events without a UUID are status events from ansible-runner and are silently dropped.
- Only events with a non-empty `uuid` field are forwarded to the `Events` channel.
- The channel is buffered with capacity 1000. If the channel blocks for more than 10 seconds, the handler returns `500`.

## Status Condition Types

Three condition types are managed on the CR's `.status.conditions`:
- `Running` -- set to True when reconciliation starts
- `Failure` -- set to True on ansible failure or validation errors
- `Successful` -- set to True on successful reconciliation

All status updates use the status subresource (`client.Status().Update()`).

## Annotations Contract

- `ansible.sdk.operatorframework.io/reconcile-period` -- overrides the controller's reconcile period for a specific CR.
- `ansible.sdk.operatorframework.io/max-runner-artifacts` -- overrides max artifacts per CR.
- `ansible.sdk.operatorframework.io/verbosity` -- overrides ansible verbosity per CR.

