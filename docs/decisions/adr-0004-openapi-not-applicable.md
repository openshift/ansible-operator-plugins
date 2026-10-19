# ADR-0004: OpenAPI Not Applicable

## Status

Accepted — no OpenAPI artifact

## Context

An agentic readiness audit flagged the absence of OpenAPI/Swagger specifications
as a gap. The repository contains three internal HTTP servers:

1. **REST proxy** (`internal/ansible/proxy/`) -- intercepts Ansible's K8s API calls
2. **Metrics API** (`internal/ansible/apiserver/`) -- accepts user-defined metrics on `localhost:5050`
3. **Event API** (`internal/ansible/runner/eventapi/`) -- receives ansible-runner events via Unix socket

None of these are public-facing HTTP APIs with authored request/response schemas
suitable for OpenAPI documentation:

- The **proxy** is a pass-through reverse proxy over the full Kubernetes API
  surface -- it has no authored schema of its own to document; the schema is
  Kubernetes' own OpenAPI, already published upstream.
- The **metrics API** accepts a simple JSON struct (`internal/ansible/metrics.UserMetric`)
  on localhost only; its contract is documented in prose in
  [docs/domain/watches-and-contracts.md](../domain/watches-and-contracts.md)
  and in the Go source (`internal/ansible/metrics/metrics.go`).
- The **event API** communicates over a Unix domain socket using
  `ansible-runner`'s internal event-stream format, not a request/response
  HTTP contract that OpenAPI models well.

## Decision

No `openapi.yaml` is maintained in this repository. The `openapi_specs` attribute
is excluded from AgentReady assessment via `.agentready-config.yaml`.

API contracts are documented in prose in
[docs/domain/watches-and-contracts.md](../domain/watches-and-contracts.md) and
in the Go type definitions themselves.

## Consequences

- No OpenAPI spec to maintain or keep in sync with source code.
- If a public API surface is ever added, this decision should be revisited.
