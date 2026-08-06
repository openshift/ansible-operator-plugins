# `generate_requirements.py` — ART Hermetic Build Requirements Generator

## Background

OpenShift's ART (Automated Release Tooling) builds container images in a
**hermetic environment** — no internet access during the actual image build.
All Python packages must be declared upfront in four requirements files so that
cachi2 (the dependency pre-fetcher) can download them before the build starts.

The old approach used a manually maintained shell pipeline inside
`openshift/Dockerfile.requirements` that hardcoded which packages caused
conflicts and where they belonged. Every time `images/ansible-operator/Pipfile`
changed, a human had to study the new conflict, figure out which packages were
involved, and update the bash script by hand.

`generate_requirements.py` replaces that pipeline with a fully automated tool
that detects conflicts dynamically and never needs to be told about specific
packages.

---

## Output Files

The script always produces exactly four files, compatible with the install order
enforced by `openshift/install-ansible.sh`:

```
requirements-pre-build.txt   →  installed first
requirements-build1.txt      →  installed second
requirements-build.txt       →  installed third
requirements.txt             →  installed fourth (runtime packages)
```

The three build files contain **build-system tools** (setuptools, wheel,
hatchling, etc.) that pip needs when building packages from source in its PEP
517 build isolation environments. Their sequential installation upgrades
conflicting tool versions in the correct order. The runtime file contains the
actual packages that the ansible-operator image needs at run time.

---

## Configuration — The Only Hardcoded Knowledge

### `RPM_INSTALLED`

```python
RPM_INSTALLED = frozenset({"cryptography", "cffi", "pycparser", "maturin"})
```

Packages that the ART OSBS environment provides through system RPMs rather than
pip. They cannot be pip-installed in the hermetic environment. The script still
lets pip-compile **resolve** them (so that packages depending on them, e.g.
`google-auth → cryptography`, produce correct dependency graphs), then **comments
them out** in every generated file.

### `PIP_COMPILE_UNSAFE`

```python
PIP_COMPILE_UNSAFE = frozenset({"pip", "setuptools", "distribute"})
```

Mirrors pip-tools' own `piptools.utils.UNSAFE_PACKAGES`. `pip freeze --all`
(used in Stage 1) always includes `pip`/`setuptools`/`distribute` even though
they're not real Pipfile dependencies, but pip-compile silently drops them
from its output whenever it's run without `--allow-unsafe` — which is how
Stage 2 compiles `requirements.txt`. Stage 6 treats their absence from
`requirements.txt` as correct rather than a completeness failure.

---

## Pipeline Overview

```
Pipfile + Pipfile.lock
         │
Stage 1  │  pipenv install --deploy
         │  ↳ CVE auto-fix (pipenv update per vulnerable package)
         │  pip freeze --all  →  all pinned runtime packages
         │
Stage 2  │  Iterative pip-compile  →  requirements.txt
         │  (detects runtime metadata conflicts dynamically)
         │
Stage 3  │  pip_find_builddeps.py per package  →  build-dep constraint map
         │
Stage 4  │  Conflict detection + phase splitting  →  3 build .txt files
         │  ↳ Auto-discovers build-isolation exact pins from package metadata
         │    (e.g. wheel==0.45.1 from ansible-core's pyproject.toml)
         │    and injects them into pre-build; later phases resolve newer versions
         │
Stage 5  │  Safety CVE scan of build files  →  auto-fix or FAIL
         │
Stage 6  │  Verify every Pipfile.lock package is in requirements.txt
         │  (active, unless RPM-installed — then commented out) →  pass or FAIL
         │
         └─ Export Pipfile.lock  (captures CVE-driven runtime updates)
```

---

## Stage 1 — Resolve Runtime Packages

```python
pipenv install --deploy      # install exactly what Pipfile.lock says
auto_fix_cves(RPM_INSTALLED) # scan with Safety, pipenv update per CVE
pipenv run pip freeze --all  # get all pinned versions
```

### CVE Auto-Fix for Runtime Packages

After installing from the lock file, `auto_fix_cves()` runs `pipenv check`
(which uses the Safety vulnerability database) and categorises every finding:

| Outcome | Action |
|---|---|
| Package in `RPM_INSTALLED` | Skip — the OS layer patches it |
| pip-managed package | `pipenv update <pkg>` to upgrade within Pipfile constraints |
| Pipfile constraint prevents fix | **Fail the script** with specific guidance; re-run after updating the Pipfile |

After attempting fixes, `pipenv check` is re-run. Any remaining vulnerabilities
that `pipenv update` could not resolve are reported with the message
"Broaden the Pipfile constraint…" and the script **exits non-zero**, so a
CVE that can't be auto-fixed can't be missed in a build log or silently pass
`make check-requirements` — it must be dealt with explicitly (either widen the
Pipfile constraint, or make a deliberate, reviewed decision to accept it).

`pip freeze` is run **after** all CVE fixes so that the pinned versions used
for the rest of the pipeline reflect the updated state.

### Manual CVE Remediation

When the script exits non-zero because a CVE couldn't be auto-fixed (either
here in Stage 1, for a runtime package, or in [Stage 5](#stage-5--build-dependency-cve-scanning),
for a build-time package), the printed output already contains everything
needed to start investigating:

1. **Read the failure output.** For each unresolved CVE it prints the package
   name, currently-pinned version, vulnerability ID, and the affected version
   spec (e.g. `affected: <2.5.0`) — that spec is what `pipenv update` /
   pip-compile couldn't satisfy given the current constraints.
2. **Find the constraint that's blocking the fix.** For Stage 1, look at the
   package's entry in `images/ansible-operator/Pipfile` — an upper bound there
   (e.g. `somepkg = "<2.0"`) is usually what's preventing `pipenv update` from
   reaching a safe version. For Stage 5, the failure message names the
   conflicting dependency directly.
3. **Check whether a safe version actually exists** that satisfies every other
   constraint in the dependency graph (`pip index versions <pkg>`, or checking
   PyPI directly). If the safe version was only released very recently, also
   confirm it's resolvable by pip-compile locally before assuming it's a
   genuine conflict.
4. **Widen the constraint** in `images/ansible-operator/Pipfile` (for a
   runtime package) if that's safe to do — i.e. it doesn't break at a version
   boundary the package intentionally warns about — then re-run
   `make generate-requirements` locally to confirm the CVE is now resolved
   and nothing else regresses.
5. **If it genuinely can't be fixed right now** (e.g. the safe version doesn't
   exist yet, or requires a breaking major upgrade), don't silence the check.
   Make a deliberate, reviewed exception instead: document why in the PR,
   and either temporarily adjust `RPM_INSTALLED`/the check itself with a
   comment explaining the accepted risk, or hold the rebase until a fix is
   available upstream.

### Why `openshift/Pipfile.lock` Can Differ From `images/ansible-operator/Pipfile.lock`

The CVE auto-fix above operates on a copy of `Pipfile.lock` inside the build
container and can bump individual package pins beyond what
`images/ansible-operator/Pipfile.lock` (the file consumed by upstream/local
`pipenv` installs) currently declares. The updated copy is exported as
`openshift/Pipfile.lock` (see "Export Pipfile.lock" below) — it is expected to
occasionally **diverge** from `images/ansible-operator/Pipfile.lock` rather
than always being a byte-for-byte copy.

This is intentional, not redundant: `images/ansible-operator/Pipfile` is not
touched by this process, and re-running `pipenv update` for every CVE just to
land the fix upstream first isn't practical given how frequently new CVEs are
reported. `openshift/Pipfile.lock` lets downstream builds move to newer,
less-vulnerable pins between upstream rebases. The divergence is naturally
bounded: every time `openshift/hack/rebase_upstream.sh` runs, downstream
regenerates from the (now-updated) upstream `Pipfile`/`Pipfile.lock` again, so
any drift introduced here doesn't compound indefinitely.

---

## Stage 2 — Generate `requirements.txt`

Some packages declare mutually incompatible version constraints in their
metadata (e.g. package A declares `setuptools>=77` while package B declares
`setuptools<=70`). pip-compile enforces these constraints during resolution and
fails when they conflict.

The stage iteratively finds which packages cause pip-compile to fail:

```
attempt 1: pip-compile requirements.in          → fails
  parse error → identify conflicting package X
attempt 2: pip-compile requirements.in (X commented out) → succeeds
```

The excluded packages are **appended uncommented** at the end of
`requirements.txt` after pip-compile succeeds. They are valid runtime
dependencies — their metadata conflicts are a pip-compile artifact, not a real
runtime incompatibility.

After that, RPM-installed packages are **commented out** in post-processing.
They remain in the file (so humans can see what version the image expects) but
pip will not install them.

---

## Stage 3 — Collect Per-Package Build Dependencies

The cachito/cachi2 build system requires every package needed to **build** each
runtime dependency from source to be pre-declared. `pip_find_builddeps.py`
(a cachito script) inspects a package's `pyproject.toml` / `setup.cfg`
build-system requirements and emits them as pip constraints.

The script runs `pip_find_builddeps.py` **once per package** (not once for the
whole list) so that each package's build constraints can be associated with
that specific package. This per-package association is essential for the
conflict-detection algorithm in Stage 4.

All packages from `pip freeze` are processed, including RPM-installed and
conflict-excluded ones. If `pip_find_builddeps.py` fails for a package (e.g.
because downloading its sdist triggers a Rust/maturin compilation), the package
is skipped with a warning and the rest continue.

Result: `pkg_constraints = { "ansible-runner": ["pbr>=2.1", …], … }`

---

## Stage 4 — Build Dependency Conflict Detection and Phase Splitting

This is the core of the tool.

### Why Phases Are Needed

Some build tools conflict in version requirements. For example:

- `ansible-runner` uses `pbr` as its build system; `pbr` requires
  `setuptools<=70`
- Most other packages use `hatch-vcs` which requires `setuptools>=77`

Installing both `setuptools<=70` and `setuptools>=77` simultaneously is
impossible. The solution is **sequential installation**: install the older
version first (pre-build), then upgrade to the newer version (build). pip's
`pip install` replaces the old version with the new one, and each package's
build isolation environment finds the version it needs in the cachi2 cache.

### The `split_phases()` Algorithm

`split_phases(packages, constraints, tmp)` recursively partitions packages into
an ordered list of groups whose build-dep constraints can each be compiled by
pip-compile without conflicts.

```
INPUT:  list of all packages with their build-dep constraint sets
OUTPUT: ordered list of groups (earlier group = must install first)
```

At each recursion level, six strategies are tried in order:

**Step 1 — Try the whole group**
Merge all constraints, run pip-compile. If it succeeds, no conflict exists and
all packages go into a single phase.

**Step 2 — Identify the conflicting dependency**
Parse pip-compile's error output to find the package name that could not be
satisfied. pip-tools 7.5+ emits `"ERROR: Cannot install setuptools …"`;
older versions emit `"Could not find a version that matches …"`. A fallback
scans for constraint-looking lines (operators followed immediately by a digit,
to avoid matching Python code like `result = self._result`).

**Step 3 — Direct upper-bound heuristic**
Search `pkg_constraints` for any package that **directly** declares an
upper-bound constraint (e.g. `setuptools<=70`) on the conflicting dependency.
Those packages need the older version and go into an earlier phase.

**Step 4 — Per-package compilation (transitive conflict detection)**
When Step 3 finds nothing, the upper bound may come **transitively** — e.g.
ansible-runner → pbr, and pbr's own build requirements restrict setuptools.
`pip_find_builddeps.py` only captures one level of build deps, so the
`setuptools<=70` constraint lives on pbr, not on ansible-runner.

The solution: compile each package's build constraints **individually** using
pip-compile and record what version of the conflicting dependency each resolves
to. Packages resolving to different versions reveal the fault line:

```
ansible-runner's build deps → setuptools 70.0.0
urllib3's build deps        → setuptools 82.0.1
split after 70.0.0 (largest gap)
→ earlier group: [ansible-runner]
```

The split point is the **largest version gap** in the distribution of resolved
versions (computed as `(hi.major - lo.major) * 1000 + (hi.minor - lo.minor)`).

**Step 5 — Single-package bisection**
When per-package compilation is also inconclusive (e.g. all packages resolve to
the same version of the conflicting dep because the upper bound is transitive
through a different path), the algorithm removes one package at a time and
retries pip-compile. The first removal that makes the remainder compile
identifies the culprit, which becomes the earlier group.

**Step 6 — Give up**
If no split can be found, the whole group is kept as one phase and a warning is
printed. This happens when a single package's own build deps are internally
contradictory (see [Internal Conflicts](#internal-conflicts)).

**Recursion**
Once a split is found, `split_phases` is called recursively on each sub-group.
The final result is a flat ordered list:

```
phases[0]  — needs oldest tool versions  →  pre-build
phases[1]  — intermediate                →  build1
phases[-1] — needs newest tool versions  →  build
```

### Mapping N Phases to 3 Files

The install order is fixed at 4 files. When `split_phases` returns more than 3
phases, a **greedy merge** runs: starting from the last (newest) phase and
working backwards through the middle phases, each middle phase is tentatively
merged into the "build" group and pip-compile is run to verify compatibility.
If the merge compiles, the phase is absorbed into build. If it fails, that
phase is instead folded into `build1` together with any other middle phases
that also failed to merge (there is no fifth output file — every middle
phase that can't join `build` ends up in `build1`). This prevents blindly
merging phases that have their own internal conflicts.

### Build-Isolation Pin Discovery and the Phased Upgrade Pattern

Packages in non-pre-build phases often declare **exact-version** build-system
requirements.  For example, ansible-core's `pyproject.toml` pins `wheel==0.45.1`
so its PEP 517 isolation environment gets precisely that version from the cachi2
cache.  Without special handling, this exact pin would propagate to the build
phase's `.in` file and pin the final image's wheel to an old, potentially
vulnerable version.

Stage 4 solves this automatically with a four-step process:

1. **Collect** all `pkg==X.Y.Z` constraints from every non-pre-build package's
   build-dep set.
2. **Probe** each candidate by adding it to the pre-build constraint set and
   running pip-compile.  Pins that conflict with the pre-build's existing
   constraints (e.g. `setuptools==82.0.0` would fail against ansible-runner's
   `setuptools<=70`) are discarded.  Compatible pins are confirmed.
3. **Inject** confirmed pins into the pre-build `.in` file — pip-compile
   resolves them naturally there, ensuring cachi2 pre-fetches those exact
   versions for build isolation.
4. **Strip** the same exact pins from non-pre-build phases — pip-compile there
   resolves the latest compatible version, giving the final image a
   newer (possibly CVE-fixed) version.

This is entirely automatic.  No configuration is needed: if ansible-core changes
its wheel requirement in a future release, the new version is discovered and
handled on the next `make generate-requirements` run.

### Phased Upgrade Pattern: Pre-Build vs Build

```
install order:  pre-build  →  build1  →  build   →  runtime
wheel:           0.45.1        —         0.47.0     (auto-discovered isolation pin)
setuptools:     70.0.0         —         82.0.0     (phase-split conflict)
setuptools-scm:  8.1.0         —          9.2.2     (phase-split conflict)
```

`pip install -r requirements-build.txt` after pre-build upgrades each of these
tools. Because both versions are in the cachi2 cache:

- ansible-runner's PEP 517 build isolation finds `setuptools==70.0.0` and
  `setuptools-scm==8.1.0`
- ansible-core's PEP 517 build isolation finds `wheel==0.45.1`
- The final image's global site-packages has the newer CVE-fixed versions

### Internal Conflicts

Some packages (e.g. `kubernetes==33.1.0`) have build dependencies that are
mutually contradictory — the same package's own build-dep set requires both
`setuptools-scm>=8` and `setuptools_scm<8`. This is an upstream packaging issue.

When a single-package phase fails to compile, the script:
1. Detects this as an internal conflict (only one package in the phase)
2. Writes an explanatory comment to the `.txt` file (not a warning that blocks
   the build)
3. Continues — the package itself remains in `requirements.txt` and pip's own
   build isolation can pull whatever it needs from the other build phases

---

## Stage 5 — Build Dependency CVE Scanning

After generating all build files, Safety is used to scan each one for known
vulnerabilities (`safety check -r <file>`).

For each vulnerability found:

| Package type | Action |
|---|---|
| In `RPM_INSTALLED` | Skip — the OS layer patches it |
| Any other pip package | Add `pkg>=min_safe_version` to the `.in` file and re-run pip-compile; if that conflicts (another dep constrains the package below the safe version), report the blocking constraint by name |

The minimum safe version is extracted from Safety's `"Affected spec: <X.Y.Z"`
field — the version just after the upper bound is the fix version.

If any vulnerability in a build requirements file cannot be auto-fixed (no
inferable minimum safe version, or a conflicting constraint blocks the
upgrade), the script **exits non-zero** listing every unresolved CVE by
package and phase, rather than only printing a warning that could be missed
in a long build log.

---

## Stage 6 — Completeness Verification

As a final sanity check, `stage6_verify_completeness()` confirms that every
package Stage 1 resolved from `Pipfile.lock` (via `pip freeze --all`) is
correctly represented in `requirements.txt`:

- Every `RPM_INSTALLED` package must appear, **commented out**.
- Every `PIP_COMPILE_UNSAFE` package (`pip`, `setuptools`, `distribute`) must
  be **absent entirely** — pip-compile drops these on its own when compiled
  without `--allow-unsafe`, which is how Stage 2 compiles `requirements.txt`.
- Every other package must appear **active** (uncommented). None may be
  missing entirely.

This guards against regressions in Stage 2's conflict-exclusion,
manual-append, or RPM-comment-out logic silently dropping or miscommenting a
package. Any discrepancy — missing, wrongly commented, or wrongly active —
is reported by package name and the script exits non-zero.

---

## Performance

The dominant cost is **Stage 3**, which invokes `pip_find_builddeps.py` once
per runtime package (one network round-trip to resolve/download each
package's build-system metadata) — this scales roughly linearly with the
number of runtime packages (~30 for this Pipfile). **Stage 4**'s recursive
`split_phases()` adds a handful of extra `pip-compile` calls on top of that:
one for the whole group, then (only if a conflict is found) one per fallback
strategy per recursion level. With the current Pipfile there's a single
build-tool conflict (`setuptools`/`setuptools-scm`, resolved in one split), so
recursion depth is shallow in practice; the theoretical worst case is `O(n)`
extra `pip-compile` invocations per recursion depth if Step 5's single-package
bisection has to run (it tries removing one package at a time until the
remainder compiles).

In a full local run of the current Pipfile (`make -f openshift/Makefile
generate-requirements`, ~30 runtime packages, 27 of which needed build-dep
collection), the entire script — Stages 1 through 6 — completed in well under
5 minutes; the dnf/toolchain setup portion of the Docker build (cached in
normal iterative use) is separate from this and unaffected by the script
itself. In a network-restricted environment, `pip_find_builddeps.py` can fail
per-package (skipped with a warning, as designed) which shortens Stage 3 but
produces incomplete build-dep data — this only affects Stage 4's output, not
the runtime `requirements.txt` from Stages 1/2/6, which involves no per-package
network calls beyond the initial `pipenv install`/`pip freeze`.

---

## Helper Reference

| Function | Purpose |
|---|---|
| `_norm(name)` | Canonical package name (lowercase, `[-_.]` → `-`) |
| `_pip_compile(in, out, extra)` | Run pip-compile; return `(success, stderr)`, never exits |
| `_read_pinned(text)` | Parse pip-freeze/pip-compile output → `{norm: "Pkg==ver"}` |
| `_comment_out(text, norms)` | Prefix matching `pkg==` lines with `#` |
| `_normalize_quirks(text)` | Fix `python-dateutil==2.9.0.post0` → `2.9.0` |
| `_strip_ansi(text)` | Remove terminal colour codes from Safety output |
| `_parse_vuln_report(text)` | Parse Safety text into `[{package, version, vuln_id, affected_spec}]` |
| `_min_safe_version(spec)` | Extract fix version from `"<X.Y.Z"` Safety spec |
| `_parse_conflict_dep(stderr)` | Extract conflicting package name from pip-compile error; handles pip-tools 7.5+ and older formats |
| `_pkgs_needing_older(dep, constraints)` | Packages with direct `<` or `<=` constraint on dep |
| `_find_older_group_by_compilation(dep, …)` | Per-package compilation to detect transitive conflicts |
| `split_phases(packages, constraints, tmp)` | Core recursive phase-splitting algorithm |
| `stage6_verify_completeness(all_pinned, out_dir)` | Verifies every Pipfile.lock package is correctly represented in requirements.txt |

---

## Running Locally

The script is runnable outside Docker for development given a Python 3.12
environment with pipenv and pip-tools installed, and
`pip_find_builddeps.py` downloaded to the working directory:

```bash
cd /path/to/ansible-operator-plugins
curl -LO https://raw.githubusercontent.com/containerbuildsystem/cachito/master/bin/pip_find_builddeps.py
chmod +x pip_find_builddeps.py
cp images/ansible-operator/Pipfile* .

python3 openshift/hack/generate_requirements.py --output-dir ./openshift
```

The normal path is through the Makefile:

```bash
make -f openshift/Makefile generate-requirements
```

This builds a container from `openshift/Dockerfile.requirements` and runs the
script inside it; the four output files (plus an updated `Pipfile.lock`) are
written to `openshift/`.

---

## Extending the Configuration

**Adding an RPM-installed package:**
Add its normalised name to `RPM_INSTALLED`. The script will automatically
comment it out from all generated files while still including it in pip-compile's
resolution.

**Changing the Pipfile:**
Simply update `images/ansible-operator/Pipfile` and re-run
`make generate-requirements`. No changes to the script are required — conflict
detection, phase splitting, and build-isolation pin discovery all adapt
automatically to the new package set.
