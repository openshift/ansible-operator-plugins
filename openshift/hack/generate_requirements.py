#!/usr/bin/env python3
"""
generate_requirements.py

Automatically generates ART hermetic build requirements files from
images/ansible-operator/Pipfile without any hardcoded package-specific
assumptions (beyond the RPM-exclusion list and cachi2-specific pins).

Produces four files compatible with openshift/install-ansible.sh:

  requirements-pre-build.txt  — earliest phase (oldest conflicting build deps)
  requirements-build1.txt     — intermediate phase
  requirements-build.txt      — main build deps
  requirements.txt            — runtime packages

Algorithm
---------
Stage 1 — pipenv install + pip freeze → all pinned runtime packages.
Stage 2 — Iteratively find which packages cause pip-compile to fail (due to
           conflicting declared dependency metadata), exclude them, and append
           them manually.  Comment out RPM-only packages in post-processing.
Stage 3 — Run pip_find_builddeps.py per-package for every runtime package to
           collect each package's build-system requirements.
Stage 4 — Detect version conflicts across all build-dep sets by attempting
           pip-compile on the merged set.  When a conflict is found, split the
           packages into phases using an upper-bound heuristic (packages whose
           build deps require the *older* version of a conflicting dep go into
           an earlier phase) with bisection fallback.  Map discovered phases to
           the three output files and compile each.

Usage
-----
  python3 generate_requirements.py [--output-dir DIR]

Prerequisites
-------------
  - pipenv, pip-compile (pip-tools) present in PATH
  - ./pip_find_builddeps.py present and executable (downloaded by Dockerfile)
  - Pipfile + Pipfile.lock in the current directory
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration — the only package-specific knowledge in this script
# ---------------------------------------------------------------------------

# Packages installed via RPM in the ART/OSBS hermetic build environment.
# They cannot be pip-installed and are commented out in every output file,
# but they ARE included in pip-compile's dependency resolution so that
# packages depending on them (e.g. google-auth → cryptography) resolve
# correctly before being commented out.
RPM_INSTALLED: frozenset[str] = frozenset({
    "cryptography",
    "cffi",
    "pycparser",
    "maturin",
})

PIP_FIND_BUILDDEPS = "./pip_find_builddeps.py"

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _norm(name: str) -> str:
    """Canonical package name: lowercase, collapse [-_.] to '-'."""
    return re.sub(r"[-_.]", "-", name).lower()


def _run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a command, print it, and exit on non-zero return code."""
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if r.returncode != 0:
        if capture:
            sys.stderr.write(r.stderr)
        sys.exit(r.returncode)
    return r


def _pip_compile(
    in_file: Path,
    out_file: Path,
    extra: list[str] | None = None,
) -> tuple[bool, str]:
    """
    Attempt pip-compile.  Returns (success, stderr).  Never raises or exits.
    """
    cmd = [
        "pip-compile",
        f"--output-file={out_file}",
        "--strip-extras",
        *(extra or []),
        str(in_file),
    ]
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def _read_pinned(text: str) -> dict[str, str]:
    """
    Parse pip-freeze / pip-compile text into {norm_name: 'OrigName==ver'}.
    Skips commented-out lines, annotation lines, and non-pinned specs.
    """
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", line)
        if m:
            result[_norm(m.group(1))] = f"{m.group(1)}=={m.group(2)}"
    return result


def _comment_out(text: str, norms: set[str]) -> str:
    """Return text with `pkg==...` lines whose norm-name is in *norms* commented out."""
    out: list[str] = []
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#") or not stripped:
            out.append(raw)
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", stripped)
        if m and _norm(m.group(1)) in norms:
            out.append(f"#{raw}")
        else:
            out.append(raw)
    return "\n".join(out) + "\n"



def _normalize_quirks(text: str) -> str:
    """Fix known PyPI version-string quirks that the ART build does not accept."""
    # python-dateutil ships 2.9.0.post0 on PyPI; ART requires the bare 2.9.0 form.
    text = re.sub(
        r"(?i)(python-dateutil)==(2\.9\.0)\.post0",
        r"\1==\2",
        text,
    )
    return text


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (Safety colours its output by default)."""
    return re.sub(r"\x1b\[[0-9;]*[mGKHF]", "", text)


def _parse_vuln_report(text: str) -> list[dict[str, str]]:
    """
    Parse 'pipenv check' / Safety text output into a list of vulnerability dicts.
    Each dict has keys: package, version, vuln_id, affected_spec.

    Uses re.search (not re.match) so that ANSI colour codes or other prefixes
    on a line do not prevent the pattern from matching.
    """
    text = _strip_ansi(text)
    vulns: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        m = re.search(r"-> Vulnerability found in (\S+) version (\S+)", line)
        if m:
            if current:
                vulns.append(current)
            current = {"package": _norm(m.group(1)), "version": m.group(2)}
            continue
        if current:
            m = re.search(r"Vulnerability ID:\s*(\S+)", line)
            if m:
                current["vuln_id"] = m.group(1)
                continue
            m = re.search(r"Affected spec:\s*(.+)", line)
            if m:
                current["affected_spec"] = m.group(1).strip()
    if current:
        vulns.append(current)
    return vulns


def _min_safe_version(affected_spec: str) -> str | None:
    """
    Infer the minimum safe package version from a Safety 'Affected spec' string.

    Examples:
      '<0.46.3'     → '0.46.3'
      '<2.33.0'     → '2.33.0'
      '>=1.0,<1.5'  → '1.5'   (the upper bound IS the CVE boundary)

    Returns None when the spec contains no upper bound.
    """
    # Find the tightest upper bound: the version just after <X
    best: str | None = None
    for m in re.finditer(r"<([0-9][0-9a-zA-Z._-]*)", affected_spec):
        best = m.group(1)   # last match wins (most restrictive)
    return best


def auto_fix_cves(rpm_installed: frozenset[str]) -> None:
    """
    Run 'pipenv check', categorise every vulnerability by remediation type,
    and attempt to auto-fix CVEs in pip-managed (non-RPM) packages.

    Three outcomes per CVE:
      RPM-installed package  — skip; the RPM layer provides the fix.
      pip package, fix works — Pipfile.lock is updated in-place via
                               'pipenv update <pkg>'.
      pip package, Pipfile   — the version constraint in Pipfile is too narrow
        constraint prevents    to reach the safe version; a warning is printed
        the fix                with instructions for manual remediation.
    """
    print("\n  Running pipenv check for CVEs…", flush=True)
    check = subprocess.run(["pipenv", "check"], capture_output=True, text=True)

    if check.returncode == 0:
        print("  No vulnerabilities found.")
        return

    vulns = _parse_vuln_report(check.stdout)
    if not vulns:
        # Safety returned non-zero but output couldn't be parsed (network error,
        # DB format change, etc.) — warn but never block requirements generation.
        print(
            "  WARNING: pipenv check returned non-zero but output could not be parsed:\n"
            + check.stdout.rstrip(),
            file=sys.stderr,
        )
        return

    rpm_norms = {_norm(p) for p in rpm_installed}
    rpm_vulns = [v for v in vulns if v["package"] in rpm_norms]
    pip_vulns = [v for v in vulns if v["package"] not in rpm_norms]

    if rpm_vulns:
        print(
            f"  {len(rpm_vulns)} CVE(s) in RPM-installed packages"
            " (fixed at the RPM layer, not via pip):"
        )
        for v in rpm_vulns:
            print(
                f"    • {v['package']} {v['version']}"
                f"  [{v.get('vuln_id', '?')}]"
                f"  affected: {v.get('affected_spec', '?')}"
            )

    if not pip_vulns:
        print("  No CVEs in pip-managed packages — nothing to auto-fix.")
        return

    print(f"\n  Attempting to auto-fix {len(pip_vulns)} CVE(s) in pip-managed packages:")
    for v in pip_vulns:
        print(
            f"    • {v['package']} {v['version']}"
            f"  [{v.get('vuln_id', '?')}]"
            f"  affected: {v.get('affected_spec', '?')}"
        )

    for v in pip_vulns:
        pkg = v["package"]
        print(f"\n  Updating '{pkg}' to fix {v.get('vuln_id', 'vulnerability')}…", flush=True)
        r = subprocess.run(
            ["pipenv", "update", pkg],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            print(f"  ✓ 'pipenv update {pkg}' succeeded")
        else:
            print(
                f"  WARNING: 'pipenv update {pkg}' failed:\n"
                f"  {r.stderr.strip()[:400]}",
                file=sys.stderr,
            )

    # Re-check: what (if anything) is still vulnerable after updates?
    print("\n  Re-running pipenv check after updates…", flush=True)
    recheck = subprocess.run(["pipenv", "check"], capture_output=True, text=True)
    if recheck.returncode == 0:
        print("  All pip-managed CVEs resolved. ✓")
        return

    remaining_pip = [
        v for v in _parse_vuln_report(recheck.stdout)
        if _norm(v["package"]) not in rpm_norms
    ]
    if remaining_pip:
        print(
            f"\n  WARNING: {len(remaining_pip)} CVE(s) remain in pip-managed packages.\n"
            "  These likely require a Pipfile version constraint change:",
            file=sys.stderr,
        )
        for v in remaining_pip:
            print(
                f"    • {v['package']} {v['version']}"
                f"  [{v.get('vuln_id', '?')}]"
                f"  affected: {v.get('affected_spec', '?')}\n"
                f"      → Broaden the Pipfile constraint so a version"
                f" outside '{v.get('affected_spec', '?')}' can be installed.",
                file=sys.stderr,
            )
        print(
            "  After updating the Pipfile, re-run 'make generate-requirements'.\n"
            "  (The Pipfile.lock exported to the output dir reflects the current"
            " best-effort fix.)",
            file=sys.stderr,
        )


def _parse_conflict_dep(stderr: str) -> str | None:
    """
    Extract the name of the dependency that pip-compile could not satisfy.

    Handles multiple pip-tools / pip error formats:
      • pip-tools 7.5+  "ERROR: Cannot install pkg, pkg!=X, … because …"
      • pip-tools older  "Could not find a version that matches pkg>=X,<Y"
      • resolvelib       "SpecifierRequirement('pkg…')" in traceback
      • constraint lines "    pkg>=45" — only when followed immediately by a
                         digit so we never match Python code like 'result = …'
    """
    for pat in (
        # pip-tools 7.5+: first token after "Cannot install" is the dep
        r"ERROR: Cannot install ([A-Za-z0-9][A-Za-z0-9._-]*)[,\s!=<>]",
        # pip-tools <7.5
        r"Could not find a version that matches ([A-Za-z0-9][A-Za-z0-9._-]*)",
        r"No matching distribution found for ([A-Za-z0-9][A-Za-z0-9._-]*)",
        # resolvelib traceback: first SpecifierRequirement holds the dep name
        r"SpecifierRequirement\('([A-Za-z0-9][A-Za-z0-9._-]*)",
    ):
        m = re.search(pat, stderr, re.MULTILINE)
        if m:
            return _norm(m.group(1))
    # Last-resort scan: lines that look like version-constraint specs.
    # Require the operator to be followed immediately by a digit (e.g. >=45)
    # to avoid matching Python assignment lines (e.g. "result = self._result").
    for line in stderr.splitlines():
        m = re.match(
            r"\s+([A-Za-z0-9][A-Za-z0-9._-]*)(?:!=|==|>=|<=|~=|>|<)\d",
            line,
        )
        if m:
            return _norm(m.group(1))
    return None


def _pkgs_needing_older(dep_norm: str, constraints: dict[str, list[str]]) -> set[str]:
    """
    Return source packages whose build-dep constraints include an UPPER BOUND
    (< or <=) on *dep_norm*.  These must go into an EARLIER phase because they
    need the older version of that dependency.
    """
    result: set[str] = set()
    for pkg, specs in constraints.items():
        for s in specs:
            m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(.*)$", s.strip())
            if not m or _norm(m.group(1)) != dep_norm:
                continue
            # upper-bound markers: < (strict) or <=
            if re.search(r"(?:^|,)\s*<[^=]|(?:^|,)\s*<=", m.group(2)):
                result.add(pkg)
    return result


# ---------------------------------------------------------------------------
# Core phase-splitting algorithm
# ---------------------------------------------------------------------------


def _find_older_group_by_compilation(
    dep_norm: str,
    packages: list[str],
    constraints: dict[str, list[str]],
    tmp: Path,
    depth: int,
) -> list[str]:
    """
    Handle transitive version conflicts that _pkgs_needing_older cannot detect.

    Compiles each package's build deps **individually** and records the version
    of *dep_norm* that each resolves to.  Packages that resolve to a
    significantly older version of *dep_norm* than the rest are the ones that
    must go into an earlier phase.

    The split point is the largest version gap in the distribution of resolved
    versions (e.g. {70.0.0, 82.0.1} → gap of 12 → split after 70.0.0).

    Returns the 'older' group as a list, or [] if no clear split is found.
    """
    try:
        from packaging.version import Version
    except ImportError:
        return []

    print(
        f"    [depth={depth}] Per-package compilation to detect transitive"
        f" conflict on '{dep_norm}'…",
        flush=True,
    )

    # Compile each package's build deps in isolation and read the resolved
    # version of dep_norm from the output.
    #
    # Build a regex that matches both hyphen and underscore normalizations of
    # dep_norm (e.g. 'setuptools-scm' and 'setuptools_scm').
    # re.escape("setuptools-scm") → "setuptools\\-scm"; we then replace the
    # escaped hyphen/underscore sequences with a [-_] character class.
    name_re = re.escape(dep_norm).replace(r"\-", r"[-_]").replace(r"\_", r"[-_]")
    dep_pattern = re.compile(r"^#?\s*" + name_re + r"==(\S+)", re.IGNORECASE)
    pkg_resolved: dict[str, Version] = {}

    for pkg in packages:
        specs = constraints.get(pkg, [])
        if not specs:
            continue
        solo_in  = tmp / f"ppc_{depth}_{pkg}.in"
        solo_out = tmp / f"ppc_{depth}_{pkg}.txt"
        solo_in.write_text("\n".join(specs) + "\n")
        ok, _ = _pip_compile(solo_in, solo_out, ["--allow-unsafe"])
        if not ok or not solo_out.exists():
            continue
        for line in solo_out.read_text().splitlines():
            m = dep_pattern.match(line.strip())
            if m:
                try:
                    pkg_resolved[pkg] = Version(m.group(1))
                except Exception:
                    pass
                break

    if not pkg_resolved:
        return []

    unique = sorted(set(pkg_resolved.values()))
    print(
        f"    [depth={depth}] '{dep_norm}' per-package resolved versions: "
        + ", ".join(str(v) for v in unique),
        flush=True,
    )

    if len(unique) < 2:
        return []  # all packages agree — not the source of the conflict

    # Find the largest gap between consecutive resolved versions.
    # e.g. [70.0.0, 82.0.1] → gap of 12 minor/major units → split after 70.0.0
    split_after = unique[0]
    max_gap = 0
    for lo, hi in zip(unique, unique[1:]):
        gap = (hi.major - lo.major) * 1000 + (hi.minor - lo.minor)
        if gap > max_gap:
            max_gap = gap
            split_after = lo

    older = [p for p, v in pkg_resolved.items() if v <= split_after]
    print(
        f"    [depth={depth}] '{dep_norm}' split after {split_after};"
        f" older group: {sorted(older)}",
        flush=True,
    )
    return older if older and set(older) < set(packages) else []


def split_phases(
    packages: list[str],
    constraints: dict[str, list[str]],
    tmp: Path,
    _depth: int = 0,
) -> list[list[str]]:
    """
    Recursively split *packages* into ordered phases whose merged build-dep
    constraints are each solvable by pip-compile without conflicts.

    Returns a list of lists ordered earliest-first (pre-build → build).

    Resolution strategy (in order):
      1. Try to compile the merged constraints for the whole group.
         → success: single phase, done.
      2. Parse the conflicting dependency from pip-compile's error output.
      3. Direct upper-bound heuristic: find packages that directly declare an
         upper-bound constraint on the conflicting dep (e.g. setuptools<=70).
      4. Per-package compilation (transitive conflict detection): compile each
         package's build deps alone, observe what version of the conflicting dep
         they resolve to, and split at the largest version gap.  This catches
         cases where the upper bound comes transitively (e.g. ansible-runner →
         pbr → setuptools<=70).
      5. Single-package bisection: remove one package at a time until the
         remainder compiles — handles the case where a single package is the
         sole culprit and neither of the above found it.
      6. Give up and keep the group as one phase (with a warning).
    """
    if not packages:
        return []
    if len(packages) == 1:
        return [list(packages)]

    # ── Step 1: try the whole group ─────────────────────────────────────────
    all_specs = [s for pkg in packages for s in constraints.get(pkg, [])]
    merged_in  = tmp / f"split_{_depth}_{len(packages)}.in"
    merged_out = tmp / f"split_{_depth}_{len(packages)}.txt"
    merged_in.write_text("\n".join(all_specs) + "\n")

    ok, stderr = _pip_compile(merged_in, merged_out, ["--allow-unsafe"])
    if ok:
        return [list(packages)]

    # ── Step 2: identify the conflicting dependency ──────────────────────────
    dep = _parse_conflict_dep(stderr)
    earlier: list[str] = []

    # ── Step 3: direct upper-bound heuristic ─────────────────────────────────
    if dep:
        earlier = sorted(
            _pkgs_needing_older(dep, {p: constraints.get(p, []) for p in packages})
        )

    # ── Step 4: per-package compilation (transitive conflict detection) ──────
    if (not earlier or set(earlier) >= set(packages)) and dep:
        print(
            f"    [depth={_depth}] Direct upper-bound heuristic inconclusive"
            f" for '{dep}'; trying per-package compilation…",
            flush=True,
        )
        earlier = _find_older_group_by_compilation(
            dep, packages, constraints, tmp, _depth
        )

    # ── Step 5: single-package bisection ─────────────────────────────────────
    if not earlier or set(earlier) >= set(packages):
        print(
            f"    [depth={_depth}] Per-package compilation inconclusive;"
            f" bisecting {len(packages)} packages…",
            flush=True,
        )
        for suspect in packages:
            rest = [p for p in packages if p != suspect]
            test_in  = tmp / f"bisect_{_depth}_{_norm(suspect)}.in"
            test_out = tmp / f"bisect_{_depth}_{_norm(suspect)}.txt"
            specs = [s for p in rest for s in constraints.get(p, [])]
            test_in.write_text("\n".join(specs) + "\n")
            ok2, _ = _pip_compile(test_in, test_out, ["--allow-unsafe"])
            if ok2:
                earlier = [suspect]
                break

    # ── Step 6: give up ──────────────────────────────────────────────────────
    if not earlier or set(earlier) >= set(packages):
        print(
            f"  WARNING: Cannot split conflict at depth={_depth};"
            " keeping group as a single phase.",
            file=sys.stderr,
        )
        print(f"  pip-compile stderr:\n{stderr}", file=sys.stderr)
        return [list(packages)]

    later = [p for p in packages if p not in set(earlier)]
    return (
        split_phases(earlier, constraints, tmp, _depth + 1)
        + split_phases(later,  constraints, tmp, _depth + 1)
    )


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def stage1_resolve_runtime(tmp: Path) -> str:
    """
    Run pipenv install --deploy, attempt to auto-fix any CVEs found by
    'pipenv check', then run pip freeze --all.

    Returns the raw pip-freeze output (all runtime packages pinned).
    The Pipfile.lock may be updated in-place if CVE fixes are applied.
    """
    print("\n══ Stage 1: Resolve runtime packages via pipenv ══")
    _run(["pipenv", "install", "--deploy"])

    # Check for CVEs and attempt auto-fixes for pip-managed packages.
    # RPM-installed packages are skipped (fixed at the OS layer).
    # Never blocks requirements generation even if CVEs remain.
    auto_fix_cves(RPM_INSTALLED)

    # pip freeze after potential CVE-driven updates so we capture the final
    # pinned versions (including any packages updated by auto_fix_cves).
    r = _run(["pipenv", "run", "pip", "freeze", "--all"], capture=True)
    raw = _normalize_quirks(r.stdout)
    n = len(_read_pinned(raw))
    print(f"  Resolved {n} pinned packages")
    return raw


def stage2_runtime_txt(
    raw: str,
    tmp: Path,
    out_dir: Path,
) -> tuple[Path, set[str]]:
    """
    Generate requirements.txt.

    Iteratively detects which packages cause pip-compile to fail due to
    conflicting declared dependency metadata (e.g. mutually incompatible
    setuptools version constraints across packages), excludes them from
    compilation, and appends them manually afterwards.

    RPM-installed packages are NOT pre-excluded here — they participate in
    pip-compile's resolution so that their dependants resolve correctly.
    They are commented out in post-processing.

    Returns (requirements.txt path, set of manually-appended norm names).
    """
    print("\n══ Stage 2: Generate requirements.txt ══")

    all_pinned = _read_pinned(raw)
    excluded: set[str] = set()   # packages causing pip-compile failures
    appended: set[str] = set()   # same set — appended manually at end

    # Write the compile input to out_dir (not tmp) so pip-compile's
    # "# via -r requirements.in" annotation uses a clean relative-looking path
    # instead of a /tmp/… tempdir path.
    compile_in = out_dir / "requirements.in"
    out_txt    = out_dir / "requirements.txt"

    for attempt in range(1, 40):
        print(f"  Attempt {attempt} — excluded from pip-compile: {sorted(excluded) or '(none)'}")
        compile_in.write_text(_comment_out(raw, excluded))
        ok, stderr = _pip_compile(compile_in, out_txt)
        if ok:
            print(f"  pip-compile succeeded on attempt {attempt}")
            break

        dep = _parse_conflict_dep(stderr)
        new_exc: str | None = None

        if dep and dep not in excluded and dep in all_pinned:
            new_exc = dep
        else:
            # Broader scan: any recognisable package name from the error output
            for line in stderr.splitlines():
                m = re.search(r"([A-Za-z0-9][A-Za-z0-9._-]+)\s*[>=<!]", line)
                if m:
                    n = _norm(m.group(1))
                    if n not in excluded and n in all_pinned:
                        new_exc = n
                        break

        if new_exc is None:
            print("FATAL: Cannot identify conflicting package from pip-compile output.", file=sys.stderr)
            print(stderr, file=sys.stderr)
            sys.exit(1)

        print(f"  → Conflict in '{new_exc}'; excluding from pip-compile and appending manually")
        excluded.add(new_exc)
        appended.add(new_exc)
    else:
        print("FATAL: Exceeded attempt limit in stage 2.", file=sys.stderr)
        sys.exit(1)

    # ---- Post-process requirements.txt ----
    content = _normalize_quirks(out_txt.read_text())

    # Append manually-excluded packages (uncommented — they ARE runtime deps)
    manual_lines = [all_pinned[n] for n in sorted(appended) if n in all_pinned]
    if manual_lines:
        content = content.rstrip("\n") + "\n" + "\n".join(manual_lines) + "\n"

    # Comment out RPM-installed packages (installed via RPM, not pip, in ART)
    content = _comment_out(content, {_norm(p) for p in RPM_INSTALLED})

    out_txt.write_text(content)
    print(f"  requirements.txt: {len(content.splitlines())} lines")
    print(f"  Manually appended (uncommented): {sorted(appended) or '(none)'}")
    print(f"  RPM-installed (commented out):   {sorted(RPM_INSTALLED)}")
    return out_txt, appended


def stage3_collect_build_deps(
    all_pinned: dict[str, str],
    tmp: Path,
) -> dict[str, list[str]]:
    """
    Run pip_find_builddeps.py for every runtime package individually.
    Collecting build deps for ALL packages — including RPM-excluded and
    conflict-excluded ones — ensures the phase-split algorithm has complete
    information about which packages need which build-dep versions.

    If pip_find_builddeps.py fails for a package (e.g. because downloading its
    sdist triggers a Rust/maturin build), that package is skipped with a warning.

    Returns {norm_name: [build-constraint-string, …]}.
    """
    print("\n══ Stage 3: Collect per-package build deps via pip_find_builddeps.py ══")

    pkg_constraints: dict[str, list[str]] = {}

    for norm_name in sorted(all_pinned):
        pkg_line = all_pinned[norm_name]
        single_in  = tmp / f"bdi_{norm_name}.txt"
        single_out = tmp / f"bdo_{norm_name}.in"
        single_in.write_text(pkg_line + "\n")

        print(f"  {pkg_line}", end=" … ", flush=True)
        r = subprocess.run(
            [sys.executable, PIP_FIND_BUILDDEPS,
             str(single_in), "-o", str(single_out), "--append"],
            capture_output=True,
            text=True,
        )

        if r.returncode != 0 or not single_out.exists():
            print("SKIPPED (pip_find_builddeps failed)")
            if r.stderr.strip():
                # Print first 200 chars so failures are diagnosable without flooding output
                print(f"    {r.stderr.strip()[:200]}", file=sys.stderr)
            continue

        specs = [
            ln.strip()
            for ln in single_out.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        pkg_constraints[norm_name] = specs
        print(f"{len(specs)} build constraints")

    total = sum(len(v) for v in pkg_constraints.values())
    print(f"  Collected {total} build constraints across {len(pkg_constraints)} packages")
    return pkg_constraints


def stage4_build_phases(
    pkg_constraints: dict[str, list[str]],
    out_dir: Path,
    tmp: Path,
) -> None:
    """
    Detect conflicts in the collected build deps, recursively split into
    phases, and produce exactly three build requirements files.

    Phase mapping (always 3 output slots regardless of discovered phase count):
      phases[0]       → requirements-pre-build.txt  (oldest conflicting deps)
      phases[1:-1]    → requirements-build1.txt     (merged middle phases)
      phases[-1]      → requirements-build.txt      (newest deps, main phase)

    Each file has RPM-installed packages commented out.  Build-isolation
    exact-version pins are discovered dynamically and injected into pre-build.
    """
    print("\n══ Stage 4: Detect conflicts and generate build requirements ══")

    packages = list(pkg_constraints.keys())
    print(f"  Running phase-split on {len(packages)} packages…")

    phases = split_phases(packages, pkg_constraints, tmp)

    print(f"  Discovered {len(phases)} phase(s): {[len(p) for p in phases]} pkgs each")
    for i, ph in enumerate(phases):
        print(f"    Phase {i}: {sorted(ph)}")

    # ---- Map N discovered phases → exactly 3 output slots ----
    #
    # Strategy for N > 3 phases: keep phases[0] as pre-build and greedily
    # absorb middle phases (from latest to earliest) into the "build" group.
    # Any middle phase that makes the build group fail to compile is kept
    # separate in "build1".  This prevents blindly merging conflicting middle
    # phases (e.g. a setuptools-scm<8 phase with a setuptools-scm>=8 phase).
    def _try_compile_group(pkgs: list[str]) -> bool:
        """Return True if merging pkgs' build-dep constraints compiles cleanly."""
        if not pkgs:
            return True
        specs = [s for p in pkgs for s in pkg_constraints.get(p, [])]
        test_in  = tmp / f"maptest_{len(pkgs)}.in"
        test_out = tmp / f"maptest_{len(pkgs)}.txt"
        test_in.write_text("\n".join(specs) + "\n")
        ok, _ = _pip_compile(test_in, test_out, ["--allow-unsafe"])
        return ok

    if not phases:
        mapped: list[tuple[str, str, list[str]]] = [
            ("pre_build", "requirements-pre-build", []),
            ("build1",    "requirements-build1",    []),
            ("build",     "requirements-build",     []),
        ]
    elif len(phases) == 1:
        mapped = [
            ("pre_build", "requirements-pre-build", []),
            ("build1",    "requirements-build1",    []),
            ("build",     "requirements-build",     phases[0]),
        ]
    elif len(phases) == 2:
        mapped = [
            ("pre_build", "requirements-pre-build", phases[0]),
            ("build1",    "requirements-build1",    []),
            ("build",     "requirements-build",     phases[1]),
        ]
    else:
        # ≥3 phases: first → pre-build, last → initial build group.
        # Try to absorb middle phases into build (from latest to earliest).
        # Phases that cannot be merged go to build1.
        build_pkgs = list(phases[-1])
        build1_pkgs: list[str] = []

        # Iterate middle phases from latest (closest to build) to earliest
        for phase in reversed(phases[1:-1]):
            candidate = phase + build_pkgs
            if _try_compile_group(candidate):
                build_pkgs = candidate
            else:
                build1_pkgs = phase + build1_pkgs  # prepend to keep order

        mapped = [
            ("pre_build", "requirements-pre-build", phases[0]),
            ("build1",    "requirements-build1",    build1_pkgs),
            ("build",     "requirements-build",     build_pkgs),
        ]

    rpm_norms = {_norm(p) for p in RPM_INSTALLED}

    # ── Dynamically discover build-isolation exact-version pins ────────────────
    #
    # Packages in non-pre-build phases may declare exact-version build-system
    # requirements (e.g. ansible-core's pyproject.toml says wheel==0.45.1 so
    # that its PEP 517 isolation environment gets that specific version from the
    # cachi2 cache).  These pins must appear in requirements-pre-build.txt so
    # cachi2 pre-fetches them; later phases are then free to resolve newer
    # (possibly CVE-fixed) versions.
    #
    # Algorithm:
    #   1. Collect all pkg==X.Y.Z constraints from non-pre-build packages.
    #   2. For each candidate, try adding it to the pre-build phase's constraint
    #      set and run pip-compile.  Keep it only if pre-build still compiles
    #      (i.e. the pin doesn't conflict with the phase-split constraint, e.g.
    #      setuptools==82 would rightly fail against pre-build's setuptools<=70).
    #   3. Inject the confirmed pins into the pre-build .in file.
    #   4. Strip those same pins from non-pre-build phases so pip-compile there
    #      resolves the latest compatible version.

    pre_build_pkgs = next((pp for pk, _, pp in mapped if pk == "pre_build"), [])
    pre_build_base_specs = [
        s for pkg in pre_build_pkgs for s in pkg_constraints.get(pkg, [])
    ]

    # Step 1: collect candidate exact pins from non-pre-build packages
    candidate_iso_pins: dict[str, str] = {}   # norm → version
    for pk, _, pp in mapped:
        if pk == "pre_build" or not pp:
            continue
        for pkg in pp:
            for s in pkg_constraints.get(pkg, []):
                m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", s.strip())
                if m:
                    candidate_iso_pins[_norm(m.group(1))] = m.group(2)

    # Step 2: verify compatibility with pre-build; discard conflicting pins
    auto_iso_pins: dict[str, str] = {}
    if candidate_iso_pins and pre_build_pkgs:
        print(
            f"\n  Probing {len(candidate_iso_pins)} exact-version pin(s) for"
            " pre-build isolation compatibility…"
        )
        for norm, ver in sorted(candidate_iso_pins.items()):
            test_in  = tmp / f"iso_{norm}.in"
            test_out = tmp / f"iso_{norm}.txt"
            test_in.write_text(
                "\n".join(pre_build_base_specs + [f"{norm}=={ver}"]) + "\n"
            )
            ok, _ = _pip_compile(test_in, test_out, ["--allow-unsafe"])
            if ok:
                auto_iso_pins[norm] = ver
                print(f"    ✓ build-isolation pin: {norm}=={ver}")
            # If not ok: conflicts with pre-build constraints — skip

    pre_build_pin_norms: dict[str, str] = {**auto_iso_pins}

    if auto_iso_pins:
        print(
            f"  Auto-detected build-isolation pins for pre-build: "
            + ", ".join(f"{k}=={v}" for k, v in sorted(auto_iso_pins.items()))
        )

    for phase_key, base, phase_pkgs in mapped:
        in_path  = out_dir / f"{base}.in"
        txt_path = out_dir / f"{base}.txt"
        label    = base.replace("requirements-", "")

        if not phase_pkgs:
            print(f"\n  {label}: (empty — no packages assigned)")
            in_path.write_text("# No packages assigned to this phase\n")
            txt_path.write_text(
                f"# {base}.txt\n"
                "# No packages assigned to this phase\n"
            )
            continue

        print(f"\n  {label}: source packages = {sorted(phase_pkgs)}")

        raw_specs = [s for pkg in phase_pkgs for s in pkg_constraints.get(pkg, [])]

        if phase_key == "pre_build":
            # Step 3: inject isolation pins into pre-build.
            # Only skip if the EXACT same pin is already in the constraint set;
            # a looser constraint like wheel>=0.36 does not block the injection.
            already_exact_pinned = {
                _norm(m.group(1))
                for s in raw_specs
                if (m := re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", s.strip()))
            }
            additions = [
                f"{norm}=={ver}"
                for norm, ver in pre_build_pin_norms.items()
                if norm not in already_exact_pinned
            ]
            if additions:
                print(f"  Injecting isolation pins into pre-build: {additions}")
            specs = raw_specs + additions
        else:
            # Step 4: strip isolation-pinned exact constraints from later phases
            # so pip-compile can resolve a newer (CVE-fixed) version there.
            filtered_specs: list[str] = []
            stripped: list[str] = []
            for s in raw_specs:
                m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", s.strip())
                if m:
                    pkg_n = _norm(m.group(1))
                    ver   = m.group(2)
                    if pkg_n in pre_build_pin_norms and ver == pre_build_pin_norms[pkg_n]:
                        stripped.append(s.strip())
                        continue   # pre-build covers this exact pin
                filtered_specs.append(s)
            if stripped:
                print(
                    f"  Stripped {len(stripped)} pre-build isolation pin(s)"
                    f" from {label} (pre-build covers them; {label} resolves newer):"
                )
                for s in stripped:
                    print(f"    {s}")
            specs = filtered_specs

        in_path.write_text("\n".join(specs) + "\n")

        ok, stderr = _pip_compile(in_path, txt_path, ["--allow-unsafe"])
        if not ok:
            print(f"  WARNING: pip-compile failed for '{label}':", file=sys.stderr)
            # If this is a single-package phase, that package's own build deps
            # are internally conflicting (e.g. kubernetes 33.1.0 requires both
            # setuptools-scm>=8 and setuptools_scm<8 in its build system).
            # Skip the phase rather than leaving a broken file; the package
            # itself remains in requirements.txt and pip's build isolation will
            # use whatever is available from the other build phases.
            if len(phase_pkgs) == 1:
                conflict_dep = _parse_conflict_dep(stderr)
                print(
                    f"  → '{phase_pkgs[0]}' has an internal build-dep conflict"
                    f" on '{conflict_dep}'; skipping its build deps.",
                    file=sys.stderr,
                )
                txt_path.write_text(
                    f"# {base}.txt\n"
                    f"# '{phase_pkgs[0]}' has an internal build-dep conflict"
                    f" on '{conflict_dep}'.\n"
                    "# Its build deps are excluded; the package itself is in"
                    " requirements.txt.\n"
                )
                continue
            # Multi-package failure: try to further split via split_phases and
            # redistribute — put packages that compile into build, leave the
            # remainder in this phase.
            print(
                f"  Attempting recursive split of {len(phase_pkgs)} packages…",
                file=sys.stderr,
            )
            sub_phases = split_phases(phase_pkgs, pkg_constraints, tmp, _depth=10)
            if len(sub_phases) >= 2:
                # Move the 'newer' (last) sub-phase into the build group by
                # rewriting build specs.  The 'older' sub-phase stays here.
                print(
                    f"  Recursive split produced {len(sub_phases)} sub-phases;"
                    " merging latest into build.",
                    file=sys.stderr,
                )
                earlier_pkgs = sub_phases[0]
                later_pkgs   = sum(sub_phases[1:], [])
                # Rewrite this phase's .in with just the earlier sub-phase
                specs_earlier = [s for p in earlier_pkgs for s in pkg_constraints.get(p, [])]
                in_path.write_text("\n".join(specs_earlier) + "\n")
                ok2, stderr2 = _pip_compile(in_path, txt_path, ["--allow-unsafe"])
                # Append later_pkgs' specs to the build .in file for recompile
                build_in  = out_dir / "requirements-build.in"
                build_txt = out_dir / "requirements-build.txt"
                if build_in.exists():
                    existing = build_in.read_text()
                    extra = [s for p in later_pkgs for s in pkg_constraints.get(p, [])]
                    build_in.write_text(existing + "\n".join(extra) + "\n")
                    _pip_compile(build_in, build_txt, ["--allow-unsafe"])
                if not ok2:
                    print(f"  Sub-split earlier phase also fails; skipping.", file=sys.stderr)
                    txt_path.write_text(
                        f"# {base}.txt\n# WARNING: pip-compile failed after sub-split\n"
                    )
                    continue
            else:
                print(f"  {stderr}", file=sys.stderr)
                txt_path.write_text(
                    f"# {base}.txt\n"
                    "# WARNING: pip-compile failed — check pip-compile output above\n"
                )
                continue

        content = txt_path.read_text()
        content = _normalize_quirks(content)
        content = _comment_out(content, rpm_norms)
        txt_path.write_text(content)
        print(f"  → {txt_path.name}: {len(content.splitlines())} lines")


# ---------------------------------------------------------------------------
# Stage 5 — CVE checking for build requirements files
# ---------------------------------------------------------------------------


def stage5_check_build_dep_cves(out_dir: Path, tmp: Path) -> None:
    """
    Scan each generated build requirements file for CVEs using Safety and
    attempt to auto-fix them by adding minimum-version constraints and
    re-running pip-compile.

    Two outcomes per vulnerability:
      RPM-installed package — skip; fixed at the OS layer.
      Other pip package     — add 'pkg>=min_safe_version' to the .in file and
                              re-run pip-compile.  If that conflicts (another
                              dep constrains the package below the safe version),
                              report the blocking constraint by name.
    """
    print("\n══ Stage 5: Check build dep CVEs ══")

    rpm_norms = {_norm(p) for p in RPM_INSTALLED}

    # Collect (phase_key, txt_path, in_path) for every build phase that has
    # both files present.
    build_phases: list[tuple[str, Path, Path]] = []
    for phase_key, base in [
        ("pre_build", "requirements-pre-build"),
        ("build1",    "requirements-build1"),
        ("build",     "requirements-build"),
    ]:
        txt = out_dir / f"{base}.txt"
        inp = out_dir / f"{base}.in"
        if txt.exists() and inp.exists():
            build_phases.append((phase_key, txt, inp))

    any_vuln_found = False

    for phase_key, txt_path, in_path in build_phases:
        label = txt_path.stem.replace("requirements-", "")
        print(f"\n  Scanning {txt_path.name}…", flush=True)

        # safety lives inside the pipenv virtualenv; try several invocation forms
        for safety_cmd in (
            ["pipenv", "run", "safety", "check", "-r", str(txt_path)],
            ["python3", "-m", "safety", "check", "-r", str(txt_path)],
            ["safety", "check", "-r", str(txt_path)],
        ):
            check = subprocess.run(safety_cmd, capture_output=True, text=True)
            if check.returncode != 1 or check.stderr.strip():
                # returncode==1 with no stderr → not a "command not found"
                break
            if "No such file" in check.stderr or "not found" in check.stderr.lower():
                continue   # try next form
            break

        if check.returncode == 0:
            print(f"  No CVEs in {txt_path.name}")
            continue

        combined = _strip_ansi(check.stdout + "\n" + check.stderr)
        vulns = _parse_vuln_report(combined)
        if not vulns:
            # safety returned non-zero for a non-CVE reason (network, db, …)
            print(
                f"  WARNING: safety check returned non-zero for {txt_path.name}"
                " but output could not be parsed; skipping.",
                file=sys.stderr,
            )
            continue

        rpm_vulns = [v for v in vulns if _norm(v["package"]) in rpm_norms]
        pip_vulns = [v for v in vulns if _norm(v["package"]) not in rpm_norms]

        if rpm_vulns:
            print(
                f"  {len(rpm_vulns)} CVE(s) in RPM-installed packages"
                " (fixed at the OS layer):"
            )
            for v in rpm_vulns:
                print(
                    f"    • {v['package']} [{v.get('vuln_id','?')}]"
                    f"  affected: {v.get('affected_spec','?')}"
                )

        if not pip_vulns:
            continue

        any_vuln_found = True
        print(f"\n  {len(pip_vulns)} CVE(s) in pip-managed packages in {label}:")
        for v in pip_vulns:
            print(
                f"    • {v['package']} {v['version']}"
                f"  [{v.get('vuln_id','?')}]"
                f"  affected: {v.get('affected_spec','?')}"
            )

        for vuln in pip_vulns:
            pkg      = _norm(vuln["package"])
            spec     = vuln.get("affected_spec", "")
            vid      = vuln.get("vuln_id", "?")
            min_safe = _min_safe_version(spec)

            if not min_safe:
                print(
                    f"\n    [{vid}] Cannot infer min safe version from"
                    f" '{spec}' for '{pkg}'; skipping.",
                    file=sys.stderr,
                )
                continue

            # ── Try to add the min-version constraint and re-compile
            print(
                f"\n    [{vid}] Attempting to upgrade '{pkg}' to >={min_safe}…",
                flush=True,
            )
            in_content = in_path.read_text()
            augmented  = in_content.rstrip("\n") + f"\n{pkg}>={min_safe}\n"

            test_in  = tmp / f"s5_{phase_key}_{pkg}.in"
            test_out = tmp / f"s5_{phase_key}_{pkg}.txt"
            test_in.write_text(augmented)

            ok, stderr = _pip_compile(test_in, test_out, ["--allow-unsafe"])

            if ok:
                in_path.write_text(augmented)
                content = test_out.read_text()
                content = _normalize_quirks(content)
                content = _comment_out(content, {_norm(p) for p in RPM_INSTALLED})
                txt_path.write_text(content)
                print(f"    ✓ '{pkg}' upgraded to >={min_safe} in {txt_path.name}")
            else:
                conflict = _parse_conflict_dep(stderr)
                print(
                    f"\n    WARNING [{vid}]: Cannot upgrade '{pkg}' to >={min_safe}.\n"
                    f"    Blocking constraint on: '{conflict}'\n"
                    f"    A build dep is pinning '{conflict}' to a version that"
                    f" prevents '{pkg}'>={min_safe}.\n"
                    f"    Check which package in {in_path.name} constrains"
                    f" '{conflict}' and update it.",
                    file=sys.stderr,
                )

    if not any_vuln_found:
        print("  No CVEs found in any build requirements file.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Generate ART hermetic build requirements files from a Pipfile.\n"
            "Dynamically resolves conflicts and splits build deps into phases."
        )
    )
    ap.add_argument(
        "--output-dir", "-o",
        default=".",
        help="Directory for output files (default: current dir)",
    )
    args = ap.parse_args()

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    width = 60
    print("=" * width)
    print("  ART Hermetic Build Requirements Generator".center(width))
    print("=" * width)
    print(f"  Output dir    : {out_dir}")
    print(f"  RPM packages  : {sorted(RPM_INSTALLED)}")

    if not Path(PIP_FIND_BUILDDEPS).exists():
        print(
            f"\nERROR: {PIP_FIND_BUILDDEPS!r} not found.\n"
            "Download it with:\n"
            "  curl -LO https://raw.githubusercontent.com/containerbuildsystem/"
            "cachito/master/bin/pip_find_builddeps.py\n"
            "  chmod +x pip_find_builddeps.py",
            file=sys.stderr,
        )
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="gen_reqs_") as td:
        tmp = Path(td)

        # Stage 1 — resolve all runtime packages (includes CVE auto-fix)
        raw = stage1_resolve_runtime(tmp)
        all_pinned = _read_pinned(raw)

        # Stage 2 — generate requirements.txt with dynamic conflict exclusion
        _req_txt, _appended = stage2_runtime_txt(raw, tmp, out_dir)

        # Stage 3 — collect build deps for every runtime package
        pkg_constraints = stage3_collect_build_deps(all_pinned, tmp)

        # Stage 4 — detect conflicts, split phases, compile build files
        stage4_build_phases(pkg_constraints, out_dir, tmp)

        # Stage 5 — check generated build requirements for CVEs and auto-fix
        stage5_check_build_dep_cves(out_dir, tmp)

    # Export the (potentially CVE-updated) Pipfile.lock so the caller can
    # commit it alongside the requirements files.
    lock_src = Path("Pipfile.lock")
    lock_dst = out_dir / "Pipfile.lock"
    if lock_src.exists() and lock_src.resolve() != lock_dst.resolve():
        shutil.copy2(lock_src, lock_dst)
        print(f"\n  Pipfile.lock exported → {lock_dst}")
        print("  Commit it if CVE fixes updated it (check with git diff).")
    elif lock_src.resolve() == lock_dst.resolve():
        print(f"\n  Pipfile.lock already in output dir (same path), skipping copy.")

    # Summary
    print("\n" + "=" * width)
    print("  Summary".center(width))
    print("=" * width)
    for fname in (
        "requirements-pre-build.txt",
        "requirements-build1.txt",
        "requirements-build.txt",
        "requirements.txt",
        "Pipfile.lock",
    ):
        p = out_dir / fname
        if p.exists():
            lines = p.read_text().splitlines()
            active = sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))
            print(f"  {fname:<30} {len(lines):>4} lines  ({active} active)")
        else:
            print(f"  {fname:<30} MISSING")


if __name__ == "__main__":
    main()
