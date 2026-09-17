# Downstream Carry Patch

## When to Use

When making a change that is specific to the OpenShift downstream fork and must
persist across upstream rebases.

## Steps

1. **Make changes** in the `openshift/` directory (it has its own `go.mod`,
   `vendor/`, `Makefile`, and `Dockerfile`).

2. **Commit with the carry prefix**:

```bash
git commit -m "UPSTREAM: <carry>: description of the change"
```

3. **Validate downstream targets**:

```bash
cd openshift && make check-requirements check-collections
```

## Commit Prefix Convention

| Prefix | Meaning |
|---|---|
| `UPSTREAM: <carry>:` | Preserve this change across future rebases |
| `UPSTREAM: <drop>:` | Accept upstream version; discard this delta on next rebase |

## Key Rules

- `openshift/` Go code does not import the root module's packages at build time.
- DO NOT hand-edit `openshift/vendor/` or `openshift/release/ansible/ansible_collections/`.
- Rebase workflow: `openshift/hack/rebase_upstream.sh`.
- If a carry patch touches both root and `openshift/`, split into separate commits.

## Reference

- Full rebase workflow: `docs/references/downstream-sync.md`
- Downstream overview: `openshift/README.md`
- ADR: `docs/decisions/adr-0001-upstream-downstream-mirror.md`
