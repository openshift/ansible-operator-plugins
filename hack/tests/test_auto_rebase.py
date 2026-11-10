"""Focused checks for release discovery, generation, merges, and publication retries."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = (
    "requirements.txt", "requirements-build.txt", "requirements-build1.txt",
    "requirements-pre-build.txt", "Pipfile.lock",
)


class AutoRebaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="auto-rebase-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.repo = self.base / "repo"
        self.tools = self.base / "bin"
        self.tools.mkdir()
        for script in ("hack/auto-rebase.sh", "openshift/hack/rebase-lib.sh",
                       "openshift/hack/run-generation.sh", "openshift/hack/rebase_upstream.sh"):
            destination = self.repo / script
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / script, destination)
        self.write("UPSTREAM-VERSION", "v1.9.0\n")
        self.write(".git/config", "original configuration\n")
        self.write(".git/refs/heads/main", "original ref\n")
        self.write(".git/HEAD", "ref: refs/heads/main\n")
        self.write("openshift/release/ansible/ansible_collections/old.txt", "old collection\n")
        for name in REQUIREMENTS:
            self.write(f"openshift/{name}", f"original {name}\n")
        self.env = dict(os.environ, PATH=f"{self.tools}:{os.environ['PATH']}",
                        DRY_RUN="1", OVERRIDE_TAG="", FAIL_LOOKUP="0", INCOMPLETE="0",
                        CALLS=str(self.base / "calls"), CONTAINER_ENGINE="fake-engine",
                        REAL_GIT=shutil.which("git"),
                        OUTPUT_NAMES=" ".join(REQUIREMENTS))
        self.command("git", '''
[[ "$1" == ls-remote ]] || { echo "Unexpected Git operation" >&2; exit 1; }
printf '%s\\n' "$*" >> "$CALLS"
[[ "$FAIL_LOOKUP" != 1 ]] || exit 1
printf 'abc\\trefs/tags/v1.9.0\\nabc\\trefs/tags/v1.10.0\\nabc\\trefs/tags/v2.0.0-rc.1\\n'
''')
        self.command("fake-engine", '''
if [[ "$1" == info ]]; then
  [[ "${FAIL_ENGINE:-0}" != 1 ]]
  exit
fi
if [[ "$1" == pull ]]; then exit 0; fi
if [[ "$*" == *--entrypoint=go* ]]; then
  printf '%s\\n' "$*" >> "$CALLS.builder"
  case "${@: -1}" in
    version) echo "go version go${BUILDER_GO:-1.27.5} linux/amd64" ;;
    ./...) [[ "$*" != *" ${FAIL_GO_CHECK:-never} -mod=vendor "* ]] ;;
  esac
  exit
fi
while [[ "$1" != -v ]]; do shift; done
mount=$2
stage=${mount%%:*}
if [[ "$mount" == *:/tmp/ansible_collections/* ]]; then
  kind=collections
  if [[ "$INCOMPLETE" != 1 ]]; then
    mkdir "$stage/ansible_collections"
    echo partial > "$stage/ansible_collections/new.txt"
  fi
else
  kind=requirements
  for name in $OUTPUT_NAMES; do
    [[ "$INCOMPLETE" != 1 || "$name" != Pipfile.lock ]] || continue
    echo partial > "$stage/$name"
  done
fi
# Failure after writing partial output, or success with required output missing.
[[ "${FAIL_GENERATION:-}" != "$kind" ]] || { echo "simulated $kind failure" >&2; exit 1; }
[[ "$INCOMPLETE" == 1 || "${GENERATION_SUCCESS:-0}" == 1 ]] \\
  || { echo "simulated container failure" >&2; exit 1; }
''')

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def command(self, name, body):
        path = self.tools / name
        path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)

    def snapshot(self):
        return {str(path.relative_to(self.repo)): path.read_bytes()
                for path in self.repo.rglob("*") if path.is_file()}

    def run_script(self, script, *args, expected=0, **settings):
        result = subprocess.run(["bash", script, *args], cwd=self.repo,
                                env=dict(self.env, **settings), capture_output=True, text=True)
        if expected == 0:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_dry_run_selects_newest_stable_release_without_writes(self):
        before = self.snapshot()
        result = self.run_script("hack/auto-rebase.sh", CONTAINER_ENGINE="")
        self.assertIn("v1.9.0 -> v1.10.0", result.stderr)
        self.assertEqual(before, self.snapshot())
        calls = (self.base / "calls").read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("ls-remote --tags --refs "))

    def test_upstream_lookup_failure_is_an_error(self):
        before = self.snapshot()
        result = self.run_script("hack/auto-rebase.sh", FAIL_LOOKUP="1", expected=1)
        self.assertIn("Failed to query upstream tags", result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_no_new_release_exits_without_mutation_or_credentials(self):
        self.write("UPSTREAM-VERSION", "v1.10.0\n")
        before = self.snapshot()
        result = self.run_script("hack/auto-rebase.sh", DRY_RUN="0", GITHUB_TOKEN="")
        self.assertIn("No newer upstream release", result.stderr)
        self.assertEqual(before, self.snapshot())

    def assert_generation_preserved(self, kind, **settings):
        before = self.snapshot()
        result = self.run_script("openshift/hack/run-generation.sh", kind,
                                 expected=1, **settings)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(list(self.repo.glob("openshift/**/.*-generation.*")))
        return result

    def test_container_failure_preserves_existing_outputs(self):
        for kind in ("collections", "requirements"):
            with self.subTest(kind=kind):
                result = self.assert_generation_preserved(kind)
                self.assertIn("simulated container failure", result.stderr)

    def test_incomplete_output_preserves_existing_files(self):
        for kind in ("collections", "requirements"):
            with self.subTest(kind=kind):
                result = self.assert_generation_preserved(kind, INCOMPLETE="1")
                self.assertIn("output missing", result.stderr)


    def git(self, *args):
        return subprocess.check_output([self.env["REAL_GIT"], *args], cwd=self.repo,
                                       stderr=subprocess.STDOUT, text=True).strip()

    def prepare_git(self):
        shutil.rmtree(self.repo / ".git")
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.test")
        self.git("config", "commit.gpgsign", "false")
        self.command("git", '''
[[ "$1" != fetch || "$*" != *upstream* ]] || exit 0
if [[ "${LEAVE_UNMERGED:-0}" == 1 && "$*" == "add -- conflict.txt" ]]; then exit 0; fi
exec "$REAL_GIT" "$@"
''')

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-m", message)

    def prepare_remote(self):
        remote = self.base / "remote.git"
        subprocess.run([self.env["REAL_GIT"], "init", "--bare", str(remote)], check=True, capture_output=True)
        for name in ("origin", "upstream"):
            self.git("remote", "add", name, str(remote))
        self.git("push", "origin", "main", "refs/tags/v1.10.0")

    def prepare_gh(self):
        self.command("gh", '''
case "$1 $2" in
  'pr list')
    [[ "${FAIL_PR_QUERY:-0}" != 1 ]] || exit 1
    echo "${OPEN_PR_COUNT:-0}"
    ;;
  'pr create')
    printf '%s\\n' "$*" > "$CALLS"
    while [[ "$1" != --body-file ]]; do shift; done
    cp "$2" "$CALLS.body"
    ;;
  *) exit 1 ;;
esac
''')

    def prepare_workflow(self):
        """Run the real workflow with local remotes and simulated external tools."""
        self.prepare_git()
        self.write("OWNERS_ALIASES", "base owners\n")
        self.write("conflict.txt", "base\n")
        self.write("go.mod", "module example.test/operator\n\ngo 1.26.3\n")
        self.write("go.sum", "old sums\n")
        self.write("vendor/dependency.txt", "old vendor\n")
        self.write(".ci-operator.yaml", "build_root_image:\n  tag: rhel-9-release-golang-1.26-openshift-5.0\n")
        self.write("openshift/Dockerfile", "FROM registry.ci.openshift.org/ocp/builder:rhel-9-golang-1.26-openshift-5.0\n")
        self.commit("base")
        self.git("checkout", "-b", "upstream-release")
        self.write("go.mod", "module example.test/operator\n\ngo 1.27.2\n")
        self.write("OWNERS_ALIASES", "upstream owners\n")
        self.write("conflict.txt", "upstream\n")
        self.commit("upstream")
        self.git("tag", "v1.10.0")
        self.git("checkout", "main")
        self.write("OWNERS_ALIASES", "downstream owners\n")
        self.write("conflict.txt", "downstream\n")
        self.commit("downstream")
        self.prepare_remote()
        # Report canonical URLs for validation; fetches and pushes use local Git.
        self.command("git", '''
if [[ "$1 $2" == "remote get-url" ]]; then
  case "${@: -1}" in
    origin) echo https://github.com/example/test.git ;;
    upstream) echo https://github.com/operator-framework/ansible-operator-plugins.git ;;
    *) exit 1 ;;
  esac
else
  exec "$REAL_GIT" "$@"
fi
''')
        self.command("go", '''
printf '%s\\n' "$*" >> "$CALLS.go"
case "$*" in
  'build -mod=vendor -o '*) cp "$HELPER_STUB" "$4" ;;
  'mod tidy') echo 'new sums' > go.sum ;;
  'mod vendor') echo 'new vendor' > vendor/dependency.txt ;;
  *) exit 1 ;;
esac
''')
        self.command("make", '''
printf '%s\\n' "$*" >> "$CALLS.generation"
case "$*" in
  '-f openshift/Makefile update-collections') kind=collections ;;
  '-f openshift/Makefile generate-requirements') kind=requirements ;;
  *) exit 1 ;;
esac
exec bash openshift/hack/run-generation.sh "$kind"
''')
        self.command("oc", '''
[[ "${FAIL_BUILDER:-0}" != 1 ]] || exit 1
if [[ "$1 $2" == 'image info' ]]; then [[ "$3" == *golang-1.27-openshift-5.1 ]]; exit; fi
[[ "$*" == 'get is builder -n ocp '* ]] || exit 1
echo rhel-9-golang-1.27-openshift-5.1
''')
        self.command("security-helper", '''
case "$1" in
 fix)
  mkdir -p "$2"
  if [[ "${FAIL_SECURITY:-0}" == 1 ]]; then echo 'unresolved advisory' > "$2/error.txt"; exit 1; fi
  echo 'Go dependency scan passed; no updates required.' > "$2/summary.txt" ;;
 required-go) awk '/^go / {print $2}' go.mod ;;
 at-least)
  actual=${2#go}
  [[ "$(printf '%s\\n%s\\n' "$actual" "$3" | sort -V | tail -1)" == "$actual" ]] ;;
 *) exit 1 ;;
esac
''')
        self.command("osv-scanner", 'echo "osv-scanner version: 2.7.1"')
        self.env["HELPER_STUB"] = str(self.tools / "security-helper")
        self.prepare_gh()
        # Host Python/PyYAML and curl must not be invoked by the wrapper.
        for tool in ("python3", "curl"):
            self.command(tool, 'echo unexpected-host-tool >> "$CALLS.unexpected"; exit 1')
        self.env.update(DRY_RUN="0", CI="1", OVERRIDE_TAG="v1.10.0",
                        GITHUB_TOKEN="fake-token", DEST_ORG_REPO="example/test",
                        REBASE_BRANCH="main", GENERATION_SUCCESS="1")

    def assert_workflow_pr(self, draft=False, **settings):
        result = self.run_script("hack/auto-rebase.sh", expected=int(draft), **settings)
        calls = (self.base / "calls").read_text()
        body = (self.base / "calls.body").read_text()
        self.assertEqual("--draft" in calls, draft)
        self.assertNotIn("Image build config", body)
        self.assertNotIn("conflict.txt", body)
        self.assertNotIn("## Conflicts resolved to upstream", body)
        self.assertFalse((self.base / "calls.unexpected").exists())
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("ls-remote", "origin", "refs/heads/v1.10.0-rebase-main").split()[0],
                         self.git("rev-parse", "HEAD"))
        return result, body

    def test_workflow_opens_ready_pr_without_build_data_dependencies(self):
        self.prepare_workflow()
        self.assert_workflow_pr()
        self.assertEqual((self.repo / "UPSTREAM-VERSION").read_text(), "v1.10.0\n")
        self.assertEqual((self.repo / "OWNERS_ALIASES").read_text(), "downstream owners\n")
        self.assertEqual((self.repo / "conflict.txt").read_text(), "upstream\n")
        merge_message = self.git("log", "-1", "--format=%B", "--fixed-strings",
                                 "--grep=Merge upstream tag v1.10.0")
        self.assertIn("Overwritten conflicts:\nconflict.txt", merge_message)
        self.assertEqual((self.repo / "go.sum").read_text(), "new sums\n")
        self.assertEqual((self.repo / "vendor/dependency.txt").read_text(), "new vendor\n")
        for path in (".ci-operator.yaml", "openshift/Dockerfile"):
            self.assertIn("golang-1.27-openshift-5.1", (self.repo / path).read_text())
        self.assertTrue((self.repo / "openshift/release/ansible/ansible_collections/new.txt").is_file())
        for name in REQUIREMENTS:
            self.assertEqual((self.repo / f"openshift/{name}").read_text(), "partial\n")


    def test_security_failure_produces_draft(self):
        self.prepare_workflow()
        _, body = self.assert_workflow_pr(draft=True, FAIL_SECURITY="1")
        self.assertIn("Go security: remediation or rescan failed (unresolved advisory)", body)
        self.assertNotIn("checks passed", body)

    def test_builder_patch_is_enforced_even_when_minor_matches(self):
        self.prepare_workflow()
        _, body = self.assert_workflow_pr(draft=True, BUILDER_GO="1.27.1")
        self.assertIn("Builder: no verified image", body)
        self.assertIn("Go build and vet: skipped", body)

    def assert_go_failure(self, check):
        self.prepare_workflow()
        _, body = self.assert_workflow_pr(draft=True, FAIL_GO_CHECK=check)
        self.assertIn(f"Go {check}: failed", body)
        calls = (self.base / "calls.builder").read_text()
        for argument in ("build -mod=vendor -buildvcs=false ./...", "vet -mod=vendor -buildvcs=false ./...", "--network=none", "GOTOOLCHAIN=local"):
            self.assertIn(argument, calls)

    def test_build_failure_produces_draft(self):
        self.assert_go_failure("build")

    def test_vet_failure_produces_draft(self):
        self.assert_go_failure("vet")

    def test_credentials_refresh_before_publication(self):
        self.prepare_workflow()
        self.command("token-provider", '''
count=$(cat "$CALLS.tokens" 2>/dev/null || echo 0)
echo "$((count + 1))" > "$CALLS.tokens"
echo "fake-token-$((count + 1))"
''')
        self.assert_workflow_pr(GITHUB_TOKEN="", GITHUB_TOKEN_COMMAND=str(self.tools / "token-provider"))
        self.assertEqual((self.base / "calls.tokens").read_text(), "3\n")

    def assert_generation_failure_pr(self, kind):
        self.prepare_workflow()
        _, body = self.assert_workflow_pr(draft=True, FAIL_GENERATION=kind)
        self.assertIn(f"Generation failed: {kind}", body)
        other_kind = "requirements" if kind == "collections" else "collections"
        self.assertNotIn(f"Generation failed: {other_kind}", body)
        self.assertEqual((self.base / "calls.generation").read_text().splitlines(), [
            "-f openshift/Makefile update-collections", "-f openshift/Makefile generate-requirements",
        ])
        collection_dir = self.repo / "openshift/release/ansible/ansible_collections"
        self.assertEqual((collection_dir / "old.txt").exists(), kind == "collections")
        self.assertEqual((collection_dir / "new.txt").exists(), kind != "collections")
        for name in REQUIREMENTS:
            expected = f"original {name}\n" if kind == "requirements" else "partial\n"
            self.assertEqual((self.repo / f"openshift/{name}").read_text(), expected)

    def test_workflow_attempts_requirements_after_collections_fail(self):
        self.assert_generation_failure_pr("collections")

    def test_workflow_preserves_requirements_when_generation_fails(self):
        self.assert_generation_failure_pr("requirements")

    def test_workflow_drafts_when_builder_is_unavailable(self):
        self.prepare_workflow()
        _, body = self.assert_workflow_pr(draft=True, FAIL_BUILDER="1")
        self.assertIn("Builder: no verified image for Go 1.27", body)
        self.assertNotIn("Generation failed", body)
        for path in (".ci-operator.yaml", "openshift/Dockerfile"):
            self.assertIn("golang-1.26-openshift-5.0", (self.repo / path).read_text())

    def assert_generation_skipped(self, **settings):
        self.prepare_workflow()
        _, body = self.assert_workflow_pr(draft=True, **settings)
        self.assertIn("CONTAINER_ENGINE must name a working engine; generation skipped", body)
        self.assertFalse((self.base / "calls.generation").exists())
        self.assertTrue((self.repo / "openshift/release/ansible/ansible_collections/old.txt").is_file())
        for name in REQUIREMENTS:
            self.assertEqual((self.repo / f"openshift/{name}").read_text(), f"original {name}\n")

    def test_workflow_drafts_when_engine_is_unavailable(self):
        self.assert_generation_skipped(FAIL_ENGINE="1")

    def test_workflow_drafts_when_engine_is_missing(self):
        self.assert_generation_skipped(CONTAINER_ENGINE="nonexistent-container-engine")

    def test_workflow_requires_explicit_engine_without_autodetection(self):
        self.env.pop("CONTAINER_ENGINE")
        for engine in ("docker", "podman"):
            self.command(engine, 'echo unexpected-autodetection >> "$CALLS.autodetect"; exit 0')
        self.assert_generation_skipped()
        self.assertFalse((self.base / "calls.autodetect").exists())

    def test_existing_open_pr_is_skipped_and_query_errors_stop_the_run(self):
        self.prepare_workflow()
        head = self.git("rev-parse", "HEAD")
        config = self.git("config", "--local", "--list")
        for query_fails in (False, True):
            with self.subTest(query_fails=query_fails):
                result = self.run_script("hack/auto-rebase.sh", OPEN_PR_COUNT="1",
                                         FAIL_PR_QUERY=str(int(query_fails)), expected=int(query_fails))
                message = "Failed to query existing PRs" if query_fails else "already exists; skipping"
                self.assertIn(message, result.stderr)
                self.assertEqual(self.git("rev-parse", "HEAD"), head)
                self.assertEqual(self.git("config", "--local", "--list"), config)
                for suffix in ("", ".go", ".generation"):
                    self.assertFalse((self.base / f"calls{suffix}").exists())

    def test_resolved_whitespace_is_allowed_but_unmerged_entries_are_blocked(self):
        self.prepare_git()
        self.write("OWNERS_ALIASES", "owners\n")
        self.write("conflict.txt", "base\n")
        self.commit("base")
        self.git("checkout", "-b", "upstream-release")
        self.write("conflict.txt", "upstream with trailing whitespace \n")
        self.commit("upstream")
        self.git("tag", "v1.10.0")
        self.git("checkout", "main")
        self.write("conflict.txt", "downstream\n")
        self.commit("downstream")
        self.git("remote", "add", "upstream", "https://github.com/operator-framework/ansible-operator-plugins.git")
        self.git("remote", "add", "origin", str(self.base / "unused"))
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("branch", "--set-upstream-to=origin/main", "main")
        self.command("go", 'echo "reached vendoring" >&2; exit 1')
        # Stop at vendoring: this regression only needs to verify the merge commit.
        for unresolved in (False, True):
            with self.subTest(unresolved=unresolved):
                result = self.run_script("openshift/hack/rebase_upstream.sh", "v1.10.0",
                                         LEAVE_UNMERGED=str(int(unresolved)), expected=1)
                if unresolved:
                    self.assertIn("Unresolved merge conflicts remain", result.stderr)
                    self.assertEqual(self.git("diff", "--name-only", "--diff-filter=U"), "conflict.txt")
                else:
                    self.assertIn("reached vendoring", result.stderr)
                    self.assertEqual(self.git("log", "-1", "--format=%s"), "Merge upstream tag v1.10.0")
                    self.assertEqual((self.repo / "conflict.txt").read_text(), "upstream with trailing whitespace \n")
                    self.git("checkout", "main")
                    self.git("branch", "-D", "v1.10.0-rebase-main")

    def test_publication_reuses_only_matching_remote_history(self):
        self.prepare_git()
        # These tests exercise publication, using small function stubs for gates.
        self.write("openshift/hack/rebase_upstream.sh", '#!/bin/bash\ngit checkout -b "$1-rebase-$2" candidate\n')
        (self.repo / "openshift/hack/rebase_upstream.sh").chmod(0o755)
        self.commit("base")
        base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-b", "upstream-release")
        self.write("result.txt", "upstream\n")
        self.commit("upstream")
        self.git("tag", "v1.10.0")
        upstream = self.git("rev-parse", "HEAD")
        self.git("checkout", "main")
        self.write("downstream.txt", "downstream\n")
        self.commit("downstream")
        self.git("checkout", "-b", "candidate")
        self.git("merge", "--no-ff", "v1.10.0", "-m", "Merge upstream tag v1.10.0")
        published = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.git("commit", "--amend", "-m", "regenerated merge")
        self.prepare_remote()
        self.prepare_gh()
        self.write("check-publication.sh", '''
source hack/auto-rebase.sh
check_remote() { :; }
remediate_go() { :; }
update_golang_builder() { :; }
validate_go() { :; }
generate_and_commit() { [[ "$DRAFT_TEST" == 0 ]]; }
main
''')
        # Keep test commands out of the checkout's cleanliness check.
        runner = self.base / "check-publication.sh"
        shutil.move(self.repo / "check-publication.sh", runner)
        for mode in ("matching", "draft", "different", "missing-tag", "missing-base"):
            with self.subTest(mode=mode):
                tip = published
                if mode != "matching" and mode != "draft":
                    parent = upstream if mode == "missing-base" else base
                    changed_tree = tree if mode != "different" else self.git("rev-parse", "main^{tree}")
                    tip = subprocess.check_output([self.env["REAL_GIT"], "commit-tree", changed_tree, "-p", parent],
                                                  cwd=self.repo, input="existing branch\n", text=True).strip()
                self.git("push", "--force", "origin", f"{tip}:refs/heads/v1.10.0-rebase-main")
                (self.base / "calls").unlink(missing_ok=True)
                result = self.run_script(str(runner), DRY_RUN="0", CI="1", OVERRIDE_TAG="v1.10.0",
                                         GITHUB_TOKEN="fake-token", DEST_ORG_REPO="example/test",
                                         REBASE_BRANCH="main", DRAFT_TEST=str(int(mode == "draft")),
                                         expected=0 if mode == "matching" else 1)
                self.assertIn("non-fast-forward", result.stderr)
                if mode in ("matching", "draft"):
                    self.assertEqual(self.git("rev-parse", "HEAD"), published)
                    self.assertEqual("--draft" in (self.base / "calls").read_text(), mode == "draft")
                else:
                    self.assertIn("different contents or missing ancestry", result.stderr)
                    self.assertFalse((self.base / "calls").exists())
                remote_tip = self.git("ls-remote", "origin", "refs/heads/v1.10.0-rebase-main").split()[0]
                self.assertEqual(remote_tip, tip)
                self.git("checkout", "main")
                self.git("branch", "-D", "v1.10.0-rebase-main")

class RehearsalFixtureTests(unittest.TestCase):
    def test_complete_tooling_and_historical_ancestry(self):
        with tempfile.TemporaryDirectory(prefix="rehearsal-fixture-test-") as base:
            repo = Path(base) / "source"
            repo.mkdir()
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=repo, stderr=subprocess.STDOUT, text=True)
            git("init", "-b", "main")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.test")
            git("config", "commit.gpgsign", "false")
            for name, content in {
                "UPSTREAM-VERSION": "v1.0.0\n", "go.mod": "historical Go inputs\n",
                "hack/a.sh": "old", "openshift/hack/a.sh": "old",
                "openshift/Makefile": "old", "openshift/Dockerfile.requirements": "old",
                "openshift/README.md": "old",
            }.items():
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            git("add", ".")
            git("commit", "-m", "historical release")
            git("tag", "v1.0.0")
            baseline = git("rev-parse", "HEAD").strip()
            git("checkout", "-b", "upstream")
            (repo / "UPSTREAM-VERSION").write_text("v1.0.1\n")
            git("commit", "-am", "target release")
            git("tag", "v1.0.1")
            target = git("rev-parse", "HEAD").strip()
            git("checkout", "main")
            (repo / "openshift/hack/generate_requirements.md").write_text("complete guide\n")
            (repo / "hack/extra-tool.sh").write_text("complete tooling\n")
            git("add", ".")
            git("commit", "-m", "current tooling")
            destination = Path(base) / "fixture"
            result = subprocess.run(["bash", str(ROOT / "hack/prepare-rebase-rehearsal.sh"),
                                     "HEAD", baseline, "v1.0.0", "v1.0.1", str(destination)],
                                    cwd=repo, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for path in ("openshift/hack/generate_requirements.md", "hack/extra-tool.sh"):
                self.assertEqual((destination / path).read_bytes(), (repo / path).read_bytes())
                self.assertIn(path, (destination / ".rehearsal-manifest").read_text())
            self.assertEqual((destination / "go.mod").read_text(), "historical Go inputs\n")
            result = subprocess.run(["bash", str(ROOT / "hack/prepare-rebase-rehearsal.sh"),
                                     "HEAD", target, "v1.0.1", "v1.0.1", str(Path(base) / "bad")],
                                    cwd=repo, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already contains the target", result.stderr)
            self.assertFalse((Path(base) / "bad").exists())


if __name__ == "__main__":
    unittest.main()
