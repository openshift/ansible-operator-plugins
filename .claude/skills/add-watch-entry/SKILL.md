# Add a New GVK Watch Entry

## When to Use

When adding support for a new Kubernetes resource (Group/Version/Kind) to be
managed by an Ansible playbook or role.

## Steps

1. **Define the watch** in `watches.yaml`:

```yaml
- group: example.com
  version: v1alpha1
  kind: MyResource
  role: roles/myresource
  # or: playbook: playbooks/myresource.yml
```

2. **Create the Ansible role** under `roles/myresource/` with standard structure
   (`tasks/main.yml`, `defaults/main.yml`, etc.).

3. **Reference files**:
   - Watch schema and defaults: `internal/ansible/watches/watches.go`
   - Example watch config: `testdata/ansible/memcached-operator/watches.yaml`
   - Watch loading/validation: `internal/ansible/watches/watches_test.go`

## Key Rules

- A watch must specify exactly one of `playbook` or `role`, never both.
- Default values: `manageStatus: true`, `watchDependentResources: true`,
  `snakeCaseParameters: true`, `maxRunnerArtifacts: 20`, `ansibleVerbosity: 2`.
- Per-GVK concurrency: set via `MAX_CONCURRENT_RECONCILES_<KIND>_<GROUP>` env var.
- Supports `${VAR}` environment variable interpolation via `os.Expand`.

## Validation

```bash
go test ./internal/ansible/watches/ -short
make verify
```
