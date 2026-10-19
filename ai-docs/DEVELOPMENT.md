# Development

## Identity and Toolchain

The development branch is `main`; the Go module remains
`github.com/operator-framework/ansible-operator-plugins` (`go.mod:1`).
The root module declares Go `1.26.3` and no `toolchain` directive (`go.mod:3`).
GitHub workflows select Go from this file (`.github/workflows/unit.yml:15`).

Start from [AGENTS.md](../AGENTS.md) for task routing and
[ARCHITECTURE.md](ARCHITECTURE.md) for runtime contracts.
The public [README](../README.md) covers releases; the
[downstream README](../openshift/README.md) covers mirroring and image inputs.

## Build Commands

| Command | Effect / evidence |
|---|---|
| `make help` | Default goal; lists annotated targets (`Makefile:179`, `Makefile:181`). |
| `make build` | Builds `cmd/ansible-operator` into `BUILD_DIR` (`Makefile:78`). |
| `make install` | Installs the runtime binary (`Makefile:74`). |
| `make generate` | Builds, recreates `testdata/`, then runs Go generators (`Makefile:52`). |
| `make lint` | Runs the Bingo-managed golangci-lint (`Makefile:64`). |
| `make fix` | Runs tidy, fmt, and lint auto-fixes; mutates files (`Makefile:58`). |

Build metadata is injected through linker flags, including version, commit,
Kubernetes version, and image version (`Makefile:22`).
`BUILD_GOOS` and `BUILD_GOARCH` override host defaults for builds (`Makefile:46`).
Tool versions and tool installation are managed through `.bingo/Variables.mk`,
included by the root Makefile (`Makefile:40`).

## Common Tasks

### Change a watch contract

Start in `internal/ansible/watches/watches.go:111` for YAML/default translation.
Trace startup wiring in `internal/cmd/ansible-operator/run/cmd.go:171`, then the
consumer in controller or runner code. Update watch tests alongside the contract
(`internal/ansible/watches/watches_test.go:1`).

For parameter conversion, inspect `runner.makeParameters` before changing
`paramconv.MapToSnake`; watch/finalizer variables have later overwrite precedence
(`internal/ansible/runner/runner.go:336`).
Conversion tests exercise acronym handling and flat-map conversion
(`internal/ansible/paramconv/paramconv_test.go:1`).

### Change generated projects

Edit templates below `pkg/plugins/ansible/v1/scaffolds/`, not just a generated
sample. The plugin dispatches initialization and API creation separately
(`pkg/plugins/ansible/v1/plugin.go:47`).
Use `make generate`, inspect the generated diff, and select the affected e2e
suite; the root generator currently calls `GenerateMoleculeSample`
(`hack/generate/samples/generate_testdata.go:56`).

### Change downstream dependencies

Read [requirements generation](../openshift/hack/generate_requirements.md) first.
`make -f openshift/Makefile generate-requirements` builds and runs the requirements
container; `check-requirements` then checks for a diff (`openshift/Makefile:24`, `openshift/Makefile:28`).
`update-collections` deletes and replaces the downstream collection tree;
`check-collections` checks its resulting diff (`openshift/Makefile:37`, `openshift/Makefile:42`).
These are container-backed, mutating operations, not lightweight doc checks.

### Prepare a release or upstream sync

Use [the release guide](../README.md) for version updates and signed tags.
Use [the downstream sync guide](../openshift/README.md) for upstream-tag rebases.
Their remote-name examples differ: identify URLs before copying commands.
The workflow in this checkout may name the OpenShift repository `upstream`;
the downstream guide's examples use that name for Operator Framework.

## CI and Validation Selection

| Workflow | Entry point |
|---|---|
| Sanity | `make test-sanity` (`.github/workflows/test-sanity.yml:18`). |
| Unit | `make test-unit` (`.github/workflows/unit.yml:16`). |
| Ansible e2e | `make test-e2e-ansible` (`.github/workflows/test-ansible.yml:17`). |
| Molecule e2e | `make test-e2e-ansible-molecule` (`.github/workflows/test-ansible.yml:38`). |

`test-sanity` runs generation and auto-fixes before enforcing a clean diff,
then license/error-message checks, vet, and lint (`Makefile:115`).
Do not treat that recipe as read-only validation.
For test prerequisites and suite selection, see [TESTING.md](TESTING.md).

The legacy `test-docs` target references a changelog generator, website submodule,
and link-check script absent from this checkout (`Makefile:124`).
Do not claim it validates these agent docs; check documentation links, YAML,
and the complete diff using the available documentation tooling instead.

## Common Mistakes

- `make clean` targets `BUILD_DIR` for removal, whose default is `.`; do not run it
  casually in a checkout you intend to keep (`Makefile:18`, `Makefile:68`).
- `ansible-operator` is not the scaffolding CLI: its root registers only `run`
  and `version` (`cmd/ansible-operator/main.go:37`).
- Enabling RBAC for insecure metrics is rejected by argument validation
  (`internal/cmd/ansible-operator/run/cmd.go:78`).
- Do not assume changing a status helper changes Ansible's resource writes:
  the request proxy is a separate path (`internal/ansible/proxy/proxy.go:96`).

## Contribution Notes

The PR template requests concise commit messages, relevant issue links, and DCO
sign-off (`.github/PULL_REQUEST_TEMPLATE.md:8`). Its `master` and contribution-link
examples are historical; the current target branch here is `main`.
Recent downstream commits use `UPSTREAM: <carry>:` or `UPSTREAM: <drop>:` subjects;
consult history and the sync guide before choosing a downstream patch category.

## Platform Guidance and SME Review Recommended

[Platform development guides](https://github.com/openshift/enhancements/tree/master/dev-guide)
provide shared conventions rather than this repository's exact commands.
Maintainer review is recommended for downstream patch classification and release
automation; these notes do not authorize publishing images, branches, or tags.
