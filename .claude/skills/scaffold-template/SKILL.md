# Modify Scaffold Templates

## When to Use

When changing the generated output of `ansible-operator init` or
`ansible-operator create api` -- the files scaffolded for new operator projects.

## Steps

1. **Edit templates** in `pkg/plugins/ansible/v1/scaffolds/internal/templates/`.
   These are Go template files that produce the scaffolded project structure.

2. **Rebuild the binary**:

```bash
make build
```

3. **Regenerate testdata** (this runs the scaffolder against sample inputs):

```bash
make generate
```

4. **Verify no unintended changes**:

```bash
git diff testdata/
make verify
```

## Key Rules

- DO NOT hand-edit files in `testdata/` -- they are generated from templates.
- `pkg/` must never import `internal/`. The plugin package is a public API.
- Scaffold output includes: Dockerfile, watches.yaml, Makefile, roles directory,
  molecule tests, RBAC manifests.
- Pod security defaults in scaffolded output: `runAsNonRoot`,
  `seccompProfile: RuntimeDefault`, drops all capabilities.
- Every new `.go` file must have an Apache 2.0 license header.

## Reference Files

- Template directory: `pkg/plugins/ansible/v1/scaffolds/internal/templates/`
- Plugin entry point: `pkg/plugins/ansible/v1/init.go`
- Generated samples: `testdata/memcached-molecule-operator/`

## Validation

```bash
make generate
git diff -- testdata/    # review the generated diff; expected for intended template changes
make verify
```
