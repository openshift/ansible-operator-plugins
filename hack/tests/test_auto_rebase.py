"""Focused checks for release discovery, generation rollback, and conflict resolution."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("hack/auto-rebase.sh", "openshift/hack/rebase-lib.sh", "openshift/hack/rebase_upstream.sh")
REAL_GIT = shutil.which("git")
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
        for script in SCRIPTS:
            destination = self.repo / script
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / script, destination)
        self.write("UPSTREAM-VERSION", "v1.9.0\n")
        self.env = dict(os.environ, PATH=f"{self.tools}:{os.environ['PATH']}",
                        DRY_RUN="1", OVERRIDE_TAG="", CALLS=str(self.base / "calls"),
                        REAL_GIT=REAL_GIT)

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def command(self, name, body):
        path = self.tools / name
        path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)

    def git(self, *args):
        return subprocess.check_output([REAL_GIT, *args], cwd=self.repo,
                                       stderr=subprocess.STDOUT, text=True).strip()

    def init_git(self):
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.test")
        self.git("config", "commit.gpgsign", "false")

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-m", message)

    def run_script(self, *args, expected=0, **settings):
        result = subprocess.run(["bash", *args], cwd=self.repo, env=dict(self.env, **settings),
                                capture_output=True, text=True)
        check = self.assertEqual if expected == 0 else self.assertNotEqual
        check(result.returncode, 0, result.stdout + result.stderr)
        return result

    def fake_ls_remote(self, fail=False):
        self.command("git", f'''
[[ "$1" == ls-remote ]] || {{ echo "Unexpected Git operation" >&2; exit 1; }}
printf '%s\\n' "$*" >> "$CALLS"
{"exit 1" if fail else ""}
printf 'abc\\trefs/tags/v1.9.0\\nabc\\trefs/tags/v1.10.0\\nabc\\trefs/tags/v2.0.0-rc.1\\n'
''')

    # --- Tag discovery ---

    def test_dry_run_selects_newest_stable_release(self):
        self.fake_ls_remote()
        result = self.run_script("hack/auto-rebase.sh")
        self.assertIn("v1.9.0 -> v1.10.0", result.stderr)
        calls = (self.base / "calls").read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("ls-remote --tags --refs "))

    def test_no_newer_release_is_a_no_op(self):
        self.fake_ls_remote()
        self.write("UPSTREAM-VERSION", "v1.10.0\n")
        result = self.run_script("hack/auto-rebase.sh")
        self.assertIn("No newer upstream release", result.stderr)

    def test_upstream_lookup_failure_is_an_error(self):
        self.fake_ls_remote(fail=True)
        result = self.run_script("hack/auto-rebase.sh", expected=1)
        self.assertIn("Failed to query upstream tags", result.stderr)

    # --- Generation rollback ---

    def test_failed_generation_restores_committed_outputs(self):
        self.init_git()
        collections = "openshift/release/ansible/ansible_collections"
        self.write(f"{collections}/old.txt", "old collection\n")
        for name in REQUIREMENTS:
            self.write(f"openshift/{name}", f"original {name}\n")
        self.commit("base")
        # The fake make removes existing outputs, writes partial ones, then fails.
        self.command("make", f'''
if [[ "$3" == update-collections ]]; then
  rm -rf {collections}
  mkdir -p {collections}
  echo partial > {collections}/new.txt
else
  rm -f openshift/requirements.txt
  echo partial > openshift/requirements.txt
fi
echo "simulated container failure" >&2
exit 1
''')
        for kind in ("collections", "requirements"):
            with self.subTest(kind=kind):
                head = self.git("rev-parse", "HEAD")
                result = self.run_script(
                    "-c", f'source openshift/hack/rebase-lib.sh; generate_and_commit {kind}',
                    expected=1)
                self.assertIn("simulated container failure", result.stderr)
                self.assertEqual(self.git("rev-parse", "HEAD"), head)
                self.assertEqual(self.git("status", "--porcelain"), "")

    def test_incomplete_generation_restores_committed_outputs(self):
        self.init_git()
        collections = "openshift/release/ansible/ansible_collections"
        self.write(f"{collections}/old.txt", "old collection\n")
        for name in REQUIREMENTS:
            self.write(f"openshift/{name}", f"original {name}\n")
        self.commit("base")
        # The fake make "succeeds" but doesn't produce all outputs.
        self.command("make", f'''
if [[ "$3" == update-collections ]]; then
  rm -rf {collections}
else
  rm -f openshift/requirements.txt
fi
''')
        for kind in ("collections", "requirements"):
            with self.subTest(kind=kind):
                head = self.git("rev-parse", "HEAD")
                self.run_script(
                    "-c", f'source openshift/hack/rebase-lib.sh; generate_and_commit {kind}',
                    expected=1)
                self.assertEqual(self.git("rev-parse", "HEAD"), head)
                self.assertEqual(self.git("status", "--porcelain"), "")

    # --- Conflict resolution ---

    def test_conflicts_resolve_to_upstream_in_merge_commit(self):
        self.init_git()
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
        self.command("git", '''
[[ "$1" != fetch ]] || exit 0
exec "$REAL_GIT" "$@"
''')
        # Stop at vendoring: this test only needs to verify the merge commit.
        self.command("go", 'echo "reached vendoring" >&2; exit 1')
        result = self.run_script("openshift/hack/rebase_upstream.sh", "v1.10.0", expected=1)
        self.assertIn("reached vendoring", result.stderr)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "Merge upstream tag v1.10.0")
        self.assertIn("Overwritten conflicts:\nconflict.txt", self.git("log", "-1", "--format=%B"))
        self.assertEqual((self.repo / "conflict.txt").read_text(), "upstream with trailing whitespace \n")
        self.assertEqual((self.repo / "UPSTREAM-VERSION").read_text(), "v1.10.0\n")

    # --- Full workflow ---

    def prepare_workflow(self):
        """Set up a real git repo with local remotes and simulated external tools."""
        self.init_git()
        self.write("OWNERS_ALIASES", "base owners\n")
        self.write("conflict.txt", "base\n")
        self.write("go.mod", "module example.test/operator\n\ngo 1.26.3\n")
        self.write("go.sum", "old sums\n")
        self.write("vendor/dependency.txt", "old vendor\n")
        self.write(".ci-operator.yaml", "build_root_image:\n  tag: rhel-9-release-golang-1.26-openshift-5.0\n")
        self.write("openshift/Dockerfile", "FROM registry.ci.openshift.org/ocp/builder:rhel-9-golang-1.26-openshift-5.0\n")
        self.write("openshift/release/ansible/ansible_collections/old.txt", "old collection\n")
        for name in REQUIREMENTS:
            self.write(f"openshift/{name}", f"original {name}\n")
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
        # Set up local bare remote
        remote = self.base / "remote.git"
        subprocess.run([REAL_GIT, "init", "--bare", str(remote)], check=True, capture_output=True)
        for name in ("origin", "upstream"):
            self.git("remote", "add", name, str(remote))
        self.git("push", "origin", "main", "refs/tags/v1.10.0")
        # Git wrapper: report a canonical upstream URL for rebase_upstream.sh's
        # validation, real git for everything else.
        self.command("git", '''
[[ "$*" != "remote get-url upstream" ]] \\
  || exec echo https://github.com/operator-framework/ansible-operator-plugins.git
exec "$REAL_GIT" "$@"
''')
        self.command("go", '''
case "$*" in
  'mod tidy') echo 'new sums' > go.sum ;;
  'mod vendor') echo 'new vendor' > vendor/dependency.txt ;;
  *) exit 1 ;;
esac
''')
        self.command("make", '''
case "$*" in
  '-f openshift/Makefile update-collections')
    rm -rf openshift/release/ansible/ansible_collections
    mkdir -p openshift/release/ansible/ansible_collections
    echo generated > openshift/release/ansible/ansible_collections/new.txt
    [[ "${FAIL_GENERATION:-}" != collections ]] || { echo "collections failure" >&2; exit 1; }
    ;;
  '-f openshift/Makefile generate-requirements')
    for name in requirements.txt requirements-build.txt requirements-build1.txt requirements-pre-build.txt Pipfile.lock; do
      echo generated > "openshift/$name"
    done
    [[ "${FAIL_GENERATION:-}" != requirements ]] || { echo "requirements failure" >&2; exit 1; }
    ;;
  *) exit 1 ;;
esac
''')
        self.command("gh", '''
case "$1 $2" in
  'pr list')
    echo "${OPEN_PR_COUNT:-0}"
    ;;
  'pr create')
    printf '%s\\n' "$*" > "$CALLS"
    while [[ "$1" != --body ]]; do shift; done
    printf '%s\\n' "$2" > "$CALLS.body"
    ;;
  'auth git-credential') ;;
  *) exit 1 ;;
esac
''')
        self.env.update(DRY_RUN="0", CI="1", OVERRIDE_TAG="v1.10.0",
                        GITHUB_TOKEN="fake-token", DEST_ORG_REPO="example/test",
                        REBASE_BRANCH="main", CONTAINER_ENGINE="fake-engine")
        self.command("fake-engine", '''
if [[ "$1" == info ]]; then
  [[ "${FAIL_ENGINE:-0}" != 1 ]]
  exit
fi
exit 0
''')

    def assert_workflow_pr(self, draft=False, **settings):
        result = self.run_script("hack/auto-rebase.sh", expected=int(draft), **settings)
        calls = (self.base / "calls").read_text()
        body = (self.base / "calls.body").read_text()
        self.assertEqual("--draft" in calls, draft)
        self.assertEqual(self.git("status", "--porcelain"), "")
        return result, body

    def test_workflow_opens_ready_pr(self):
        self.prepare_workflow()
        _, body = self.assert_workflow_pr()
        self.assertIn("Collections and requirements generated", body)
        self.assertEqual((self.repo / "UPSTREAM-VERSION").read_text(), "v1.10.0\n")
        self.assertEqual((self.repo / "OWNERS_ALIASES").read_text(), "downstream owners\n")
        self.assertEqual((self.repo / "conflict.txt").read_text(), "upstream\n")
        merge_message = self.git("log", "-1", "--format=%B", "--fixed-strings",
                                 "--grep=Merge upstream tag v1.10.0")
        self.assertIn("Overwritten conflicts:\nconflict.txt", merge_message)
        self.assertEqual((self.repo / "go.sum").read_text(), "new sums\n")
        for path in (".ci-operator.yaml", "openshift/Dockerfile"):
            self.assertIn("golang-1.27-openshift-5.0", (self.repo / path).read_text())
        self.assertTrue((self.repo / "openshift/release/ansible/ansible_collections/new.txt").is_file())
        for name in REQUIREMENTS:
            self.assertEqual((self.repo / f"openshift/{name}").read_text(), "generated\n")

    def test_collections_failure_produces_draft(self):
        self.prepare_workflow()
        _, body = self.assert_workflow_pr(draft=True, FAIL_GENERATION="collections")
        self.assertIn("Generation failed: collections", body)
        self.assertNotIn("Generation failed: requirements", body)

    def test_requirements_failure_produces_draft(self):
        self.prepare_workflow()
        _, body = self.assert_workflow_pr(draft=True, FAIL_GENERATION="requirements")
        self.assertIn("Generation failed: requirements", body)
        self.assertNotIn("Generation failed: collections", body)

    def test_workflow_drafts_when_engine_unavailable(self):
        self.prepare_workflow()
        _, body = self.assert_workflow_pr(draft=True, FAIL_ENGINE="1")
        self.assertIn("CONTAINER_ENGINE must name a working engine", body)

    def test_workflow_drafts_when_builder_pins_disagree(self):
        self.prepare_workflow()
        self.write("openshift/Dockerfile",
                   "FROM registry.ci.openshift.org/ocp/builder:rhel-9-golang-1.25-openshift-5.0\n")
        self.commit("drifted builder pin")
        self.git("push", "origin", "main")
        _, body = self.assert_workflow_pr(draft=True)
        self.assertIn("Go pins in .ci-operator.yaml and openshift/Dockerfile", body)

    def test_existing_open_pr_is_skipped(self):
        self.prepare_workflow()
        head = self.git("rev-parse", "HEAD")
        result = self.run_script("hack/auto-rebase.sh", OPEN_PR_COUNT="1")
        self.assertIn("already exists; skipping", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)


if __name__ == "__main__":
    unittest.main()
