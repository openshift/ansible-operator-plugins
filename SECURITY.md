# Security Policy

## Reporting a Vulnerability

The Ansible Operator Plugins project follows the [Operator Framework security
policy](https://github.com/operator-framework/community/blob/main/SECURITY.md).

**Do not open a public GitHub issue for security vulnerabilities.**

To report a vulnerability privately, use one of the following:

- GitHub Security Advisories: open a draft advisory at
  https://github.com/operator-framework/ansible-operator-plugins/security/advisories/new
- Email the maintainers listed in [OWNERS](OWNERS), or reach the Operator
  Framework working group.

Please include:

- A description of the vulnerability and its impact
- Steps to reproduce (proof-of-concept if possible)
- Affected version(s) or commit SHA
- Any known mitigations

## Supported Versions

Security fixes are applied to the most recent minor release branch and
backported to the current downstream OpenShift rebase branch (see
`docs/references/downstream-sync.md`). Older branches are not routinely
patched.

## Scope and Threat Model

For a structured description of trust boundaries, entry points, and known
threats, see [`THREAT_MODEL.md`](THREAT_MODEL.md). Key security-relevant
areas of this codebase:

- The Ansible proxy (`internal/ansible/proxy/`) binds to localhost only and
  has no authentication of its own — see `docs/references/security.md`.
- The `Authorization` header is stripped in the proxy handler chain; both
  stripping calls are required and must not be removed.
- The user-metrics API (`internal/ansible/apiserver/`, port 5050) accepts
  local Unix-domain-socket input from `ansible-runner`, not external traffic.

## Dependency and Static Analysis Scanning

This repository uses automated scanning to catch known-vulnerable
dependencies and common code security issues before merge:

- **Dependabot** (`.github/dependabot.yml`) — dependency update alerts
- **CodeQL** (`.github/workflows/codeql.yml`) — static application security
  testing (SAST) for Go
- **Semgrep** (`.github/workflows/semgrep.yml`) — multi-rule SAST
- **detect-secrets** (`.pre-commit-config.yaml`) — pre-commit secret scanning

## Disclosure Process

1. Report received and acknowledged (best effort within 5 business days).
2. Maintainers validate and assess severity.
3. A fix is developed privately and a coordinated release is prepared.
4. A GitHub Security Advisory is published once a fix is available.
