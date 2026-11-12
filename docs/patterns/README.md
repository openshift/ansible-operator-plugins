# Pattern Index

Index of copy-modify reference implementations for the most common change
types in this repository. Each entry links to a real file (or a `.claude/skills/`
recipe) instead of describing the change in the abstract.

| Change type | Reference implementation |
|---|---|
| New GVK watch entry | `internal/ansible/watches/watches.go`, `testdata/memcached-molecule-operator/watches.yaml`, `.claude/skills/add-watch-entry/SKILL.md` |
| Controller reconcile feature | `internal/ansible/controller/reconcile.go`, `.claude/skills/add-controller-feature/SKILL.md` |
| Scaffold template change | `pkg/plugins/ansible/v1/scaffolds/internal/templates/`, `.claude/skills/scaffold-template/SKILL.md` |
| Go dependency update | `go.mod`, `go.sum`, `.claude/skills/update-dependencies/SKILL.md` |
| Downstream carry patch | `openshift/Makefile`, `openshift/hack/rebase_upstream.sh`, `.claude/skills/downstream-carry/SKILL.md` |

See also `examples/` for a runnable sample operator and `AGENTS.md` for the
full agent-facing documentation map.
