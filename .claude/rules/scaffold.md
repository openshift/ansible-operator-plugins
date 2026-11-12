---
paths:
  - "pkg/plugins/ansible/v1/**"
---

# Scaffold/Plugin Module Rules

- Templates in `pkg/plugins/ansible/v1/scaffolds/internal/templates/` are the source of truth for scaffolded operator projects.
- After modifying any template, always run `make generate` to regenerate `testdata/`.
- DO NOT hand-edit files in `testdata/` -- they are generated artifacts.
- `pkg/` must never import `internal/`. The plugin scaffolding package is a public API consumed by downstream projects.
- Scaffold output includes: Dockerfile, watches.yaml, Makefile, roles directory, molecule tests.
- Pod security defaults: `runAsNonRoot`, `seccompProfile: RuntimeDefault`, drops all capabilities.
- Validate after template changes: run `make generate`, review the intended output with `git diff -- testdata/` (a diff here is expected for a real template change, not a failure), commit the template and generated-output changes together, then run `make verify`.
