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
while [[ "$1" != -v ]]; do shift; done
mount=$2
stage=${mount%%:*}
if [[ "$mount" == *:/tmp/ansible_collections/* ]]; then
  if [[ "$INCOMPLETE" != 1 ]]; then
    mkdir "$stage/ansible_collections"
    echo partial > "$stage/ansible_collections/new.txt"
  fi
else
  for name in $OUTPUT_NAMES; do
    [[ "$INCOMPLETE" != 1 || "$name" != Pipfile.lock ]] || continue
    echo partial > "$stage/$name"
  done
fi
# Failure after writing partial output, or success with required output missing.
[[ "$INCOMPLETE" == 1 ]] || { echo "simulated container failure" >&2; exit 1; }
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
        result = self.run_script("hack/auto-rebase.sh")
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
        self.git("merge", "--no-ff", "v1.10.0", "-m", "Merge upstream tag v1.10.0",
                 "-m", "Overwritten conflicts:\nremote-conflict.txt")
        published = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.git("commit", "--amend", "-m", "regenerated merge")
        remote = self.base / "remote.git"
        subprocess.run([self.env["REAL_GIT"], "init", "--bare", str(remote)], check=True, capture_output=True)
        self.git("remote", "add", "origin", str(remote))
        self.git("remote", "add", "upstream", str(remote))
        self.git("push", "origin", "main")
        self.command("gh", '''
if [[ "$2" == list ]]; then echo 0; else
  printf '%s\\n' "$*" > "$CALLS"
  while [[ "$1" != --body-file ]]; do shift; done
  cp "$2" "$CALLS.body"
fi
''')
        self.write("check-publication.sh", '''
source hack/auto-rebase.sh
check_remote() { :; }
update_golang_builder() { :; }
select_container_engine() { echo fake-engine; }
generate_and_commit() { [[ "$DRAFT_TEST" == 0 ]]; }
check_build_data_requirements() { :; }
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
                    self.assertIn("remote-conflict.txt", (self.base / "calls.body").read_text())
                else:
                    self.assertIn("different contents or missing ancestry", result.stderr)
                    self.assertFalse((self.base / "calls").exists())
                remote_tip = self.git("ls-remote", "origin", "refs/heads/v1.10.0-rebase-main").split()[0]
                self.assertEqual(remote_tip, tip)
                self.git("checkout", "main")
                self.git("branch", "-D", "v1.10.0-rebase-main")

if __name__ == "__main__":
    unittest.main()
