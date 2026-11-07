# Review Instructions

## Scope and Severity

Review changed behavior, not a hypothetical replacement architecture.
Must fix before merge: broken reconciliation, lifecycle regressions, unsafe
credential handling, or incompatible public behavior without a migration path.
Worth fixing, not blocking: unclear diagnostics or maintainability risks with
a concrete changed-code example. Style-only preferences are suggestions.

## Always Check

- Check compatibility when changing public CLI flags or behavior; the platform
  treats CLI compatibility explicitly ([breaking changes](https://github.com/openshift/enhancements/blob/master/dev-guide/breaking-changes.md)).
- If a change introduces or modifies a stable `openshift.io` API, reject
  incompatible same-version changes ([breaking changes](https://github.com/openshift/enhancements/blob/master/dev-guide/breaking-changes.md)).
- For newly exposed OpenShift APIs, check the applicable API conventions rather
  than extrapolating from arbitrary Ansible CRs ([API conventions](https://github.com/openshift/enhancements/blob/master/dev-guide/api-conventions.md)).
- Use established OpenShift terminology in new public text; distinguish local
  branch names from historical examples ([conventions](https://github.com/openshift/enhancements/blob/master/CONVENTIONS.md)).

## Do Not Report

Skip routine line-level review of generated/dependency content:
- `vendor/**`.
- `openshift/vendor/**`.
- `testdata/**`.
- `openshift/release/ansible/ansible_collections/**`.

Review the source inputs and unexplained generated churn instead.
Do not report individual `go.sum` checksum lines; investigate unexplained churn.
Keep `go.mod` semantic changes reviewable, including versions and replacements.
Do not duplicate mechanical formatting/lint failures already enforced by
`make test-sanity` (`Makefile:115`); explain behavioral impact instead.

## Verification Bar

Every finding must cite a changed `file:line`, explain a concrete failure mode,
and identify supporting source or a reproducible scenario.
Inspect callers before claiming a helper is unused or a condition impossible.
Do not claim a build or test passed without its command and observed result.
Distinguish unsupported assertions from confirmed defects.

## Re-review

Recheck fixes and affected dependencies. Do not introduce new style nits on
unchanged code; report newly discovered correctness/security issues with evidence.
Do not reopen resolved findings without new evidence.

## Path-specific Rules

### `internal/ansible/controller/**`

Check finalizer success/error ordering and the post-run uncached CR fetch.
Distinguish metadata Update from status Update (`reconcile.go:232`).

### `internal/ansible/proxy/**`

Check owner-reference versus owner-annotation handling and request scoping.
Do not infer SSA semantics for all forwarded requests (`inject_owner.go:143`).

### `pkg/plugins/ansible/v1/**`

Review template inputs together with regenerated sample output.
Keep runtime CLI and scaffolding plugin responsibilities distinct (`plugin.go:34`).

### `test/**`

Check suite prerequisites and whether the change belongs in the Ansible or
molecule workflow. Do not assume envtest replaces kind (`Makefile:142`).

### `openshift/**`

Review downstream dependency/image inputs in their own module/build context.
Use the public sync and requirements guides before prescribing regeneration.
