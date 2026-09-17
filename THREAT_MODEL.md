# Threat Model: Ansible Operator Plugins

> **Status**: Draft -- pending maintainer and security team review.

## 1. System context

Ansible Operator Plugins is a Go library and binary that bridges Ansible
automation with Kubernetes controllers via controller-runtime. The operator
process runs inside a Kubernetes pod, shells out to `ansible-runner` for
playbook/role execution, and communicates with the Kubernetes API server via a
localhost proxy. It manages Custom Resources by mapping GVKs to Ansible
automation defined in a `watches.yaml` file.

The operator is deployed by the operator author (cluster admin) and executes
playbooks defined at build time -- end users interact only via Custom Resource
CRUD operations.

## 2. Assets

| Asset | Description | Sensitivity |
|---|---|---|
| Kubernetes API credentials | ServiceAccount token projected into the pod | Critical |
| Kubeconfig temp files | Per-reconcile kubeconfig written to `/tmp/` | High |
| Custom Resource spec data | User-provided CR fields passed to Ansible as extravars | Medium-High |
| Ansible playbook/role code | Operator logic defined at build time | Medium |
| Status conditions | CR status subresource updated by the reconciler | Medium |
| Metrics data | Prometheus metrics on port 5050 | Low |
| Runner artifacts | Ansible-runner output in `/tmp/ansible-operator/runner/` | Low |

## 3. Entry points & trust boundaries

| Entry point | Description | Trust boundary | Reachable assets |
|---|---|---|---|
| Kubernetes API watch | CR create/update/delete events from API server | Cluster RBAC | CR spec data, status |
| Proxy HTTP (localhost) | Ansible modules call K8s API via localhost proxy | Pod-local only | K8s API credentials |
| Event API socket | Unix socket for ansible-runner job events | Pod-local only | Status conditions |
| Metrics API (localhost:5050) | User-defined metrics endpoint | Pod-local only | Metrics data |
| ansible-runner subprocess | Ansible playbook execution via `exec` | Pod process boundary | All pod-accessible resources |
| Container image layers | Python packages, Ansible collections | Build-time supply chain | All runtime assets |

```text
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                     │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Operator Pod                        │    │
│  │                                                  │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │    │
│  │  │Controller │  │  Proxy   │  │ansible-runner│  │    │
│  │  │ (Go)     │──│localhost │──│ (Python)     │  │    │
│  │  └──────────┘  └──────────┘  └──────────────┘  │    │
│  │       │                            │            │    │
│  │       │ kubeconfig (tmp)           │ unix sock  │    │
│  │       │                            │ /tmp/      │    │
│  └───────┼────────────────────────────┼────────────┘    │
│          │                            │                  │
│     K8s API Server              Playbook execution       │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## 4. Threats

| ID | Threat | Actor | Impact | Likelihood | Status |
|---|---|---|---|---|---|
| T1 | Overly broad RBAC on scaffolded ClusterRole | Operator author (misconfiguration) | High | Medium | Documented |
| T2 | Stale cache serving outdated data | N/A (race condition) | Medium | Low | Mitigated |
| T3 | Status subresource manipulation via stale writes | N/A (race condition) | Medium | Low | Mitigated |
| T4 | Jinja2 template injection from CR spec fields | Cluster user (malicious CR) | High | Medium | Mitigated |
| T5 | Untrusted playbook code execution | Operator author | Critical | Low | Accepted |
| T6 | ansible-runner not on PATH | N/A (misconfiguration) | Low | Low | Mitigated |
| T7 | Resource exhaustion from concurrent reconciles | Cluster user (CR flood) | Medium | Medium | Mitigated |
| T8 | Proxy exposed outside pod | Network attacker | Critical | Low | Mitigated |
| T9 | Authorization header leakage to API server | N/A (code bug) | High | Low | Mitigated |
| T10 | Metrics API exposed externally | Network attacker | Low | Low | Mitigated |
| T11 | Event API socket access by other pods | Co-located pod | Medium | Low | Mitigated |
| T12 | HTTP/2 vulnerabilities | Network attacker | Medium | Low | Mitigated |
| T13 | Slowloris attacks | Network attacker | Low | Low | Mitigated |
| T14 | Kubeconfig temp files persisting on disk | Pod co-tenant | High | Low | Mitigated |
| T15 | Owner reference in Basic Auth username | N/A | Low | Low | Mitigated |
| T16 | Request logging exposing secrets | Operator author (verbose config) | Medium | Low | Documented |
| T17 | Vulnerable Python packages in operator image | Supply chain | High | Medium | Partially mitigated |
| T18 | Container escape | Container attacker | Critical | Low | Mitigated |
| T19 | Tampered testdata committed | Contributor (malicious PR) | Medium | Low | Mitigated |
| T20 | Stale vendor dependencies | Supply chain | Medium | Medium | Mitigated |

### Mitigations

| ID | Mitigation |
|---|---|
| T1 | Document that production operators should narrow permissions from scaffold default |
| T2 | 6-second cache timeout with fallback to API server |
| T3 | Status updates use `APIReader` (direct reads) to prevent stale writes |
| T4 | `markUnsafe: true` wraps strings as `__ansible_unsafe` |
| T5 | Operator runs playbooks defined by the operator author, not end users |
| T6 | Detected at reconcile time via `exec.LookPath` |
| T7 | `MaxConcurrentReconciles` bounded; configurable per-GVK |
| T8 | Binds to `localhost` only; kubeconfig hardcodes localhost URL |
| T9 | Two independent stripping points in handler chain |
| T10 | Binds to `localhost:5050` |
| T11 | Unix socket in `/tmp` with umask `0077` |
| T12 | HTTP/2 disabled by default (`--enable-http2=false`) |
| T13 | `ReadHeaderTimeout: 5s` on all HTTP servers |
| T14 | `defer os.Remove` in reconcile; cleanup runs even on panic |
| T15 | Base64-encoded metadata only, not credentials; stripped before API server |
| T16 | Verbose logging (`--log-requests`, V(2)) disabled by default |
| T17 | Pipfile.lock pins versions; Dependabot monitors image deps |
| T18 | Scaffolded pod security: `runAsNonRoot`, `seccompProfile: RuntimeDefault`, drops all capabilities |
| T19 | `make test-sanity` regenerates and asserts `git diff --exit-code` |
| T20 | CI dirty-tree check catches stale vendor |

## 5. Deprioritized

| Threat | Reason |
|---|---|
| Ansible sandbox escape | Operator author controls playbook content; sandboxing is out of scope for this project |
| SA token theft via `/proc` | Requires container escape (T18) which is separately mitigated |
| DNS rebinding against localhost proxy | Pod network policies and localhost binding make this impractical |
| Timing side-channels in reconcile loop | No security-sensitive branching in the reconcile path |

## 6. Open questions

- Formal security audit of the proxy handler chain ordering
- Review of downstream Cachito dependency resolution for supply chain risks
- Evaluation of ansible-runner sandboxing options
- Audit of file permissions in `/tmp/ansible-operator/runner/` (currently 0777 for directories)
- Whether projected SA token rotation is handled correctly during long-running reconciles

## 7. Provenance

- **Mode**: bootstrap
- **Date**: 2026-09-10
- **Author**: AI-assisted draft, pending maintainer review
- **Methodology**: Manual code review of proxy, runner, and controller packages

## 8. Recommended mitigations

| Mitigation | Threat IDs | Effort | Priority |
|---|---|---|---|
| Narrow default scaffold RBAC to namespace-scoped | T1 | S | High |
| Add NetworkPolicy to scaffolded output restricting metrics ingress | T10 | S | Medium |
| Tighten `/tmp/ansible-operator/runner/` directory permissions to 0750 | T11, T14 | S | Medium |
| Add gosec to CI pipeline for SAST scanning | T17 | S | High |
| Document verbose logging security implications in AGENTS.md | T16 | S | Low |
| Evaluate ansible-runner process sandboxing (seccomp, AppArmor) | T5, T7 | L | Low |
| Add secret detection (gitleaks/detect-secrets) to pre-commit | T16 | M | Medium |
