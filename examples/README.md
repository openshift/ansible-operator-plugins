# Examples

## Sample Ansible Operator

`testdata/memcached-molecule-operator/` is a generated, buildable sample
operator produced by `make generate` (via `ansible-operator init` +
scaffolding). It is the canonical reference for:

- `watches.yaml` structure (GVK-to-role/playbook mapping)
- Role layout under `roles/<kind>/tasks/main.yml`
- Molecule test scaffolding under `molecule/`
- Generated manifests under `config/` (CRD, RBAC, manager, samples)

Do not hand-edit files under `testdata/` — see `docs/domain/generated-artifacts.md`
for regeneration rules.

## Minimal watches.yaml

```yaml
---
- version: v1alpha1
  group: cache.example.com
  kind: Memcached
  playbook: playbooks/memcached.yml
  finalizer:
    name: cache.example.com/finalizer
    role: memfin
```

## Further Reading

- `docs/patterns/README.md` — index of reference implementations by change type
- `docs/AOP_DEVELOPMENT.md` — build, setup, and validation commands
- `AGENTS.md` — agent-facing documentation router
