# Overview

This is the downstream repo for the
[Operator Framework's Ansible Operator Plugins][upstream_repo]. The purpose of this repo is
to build downstream Ansible Operator base image for OpenShift releases.


# Downstream structure

This repo is a mirror of the upstream
[`operator-framework/ansible-operator-plugins`][upstream_repo] repo along with some downstream artifacts.

The downstream artifacts are as follows:

* `openshift` - contains files for building downstream ansible operator base image.
* `openshift/ci` - contains the CI related build files.
* `openshift/hack` - contains the scripts for updating downstream files.
* `openshift/release/ansible` - contains files related to ansible-collections.
* `vendor` - unlike the upstream, we vendor in the dependencies downstream.
* `openshift/vendor` - vendor in the dependencies from openshift/go.mod.

# Syncing

When an upstream release is ready, you can sync down that release downstream.
This can be done manually or automatically via a Prow periodic.

## Automatic rebase (periodic)

A Prow periodic runs [`hack/auto-rebase.sh`](../hack/auto-rebase.sh) weekly
against `main`. A custom script is used because this repo rebases via **git
merge** (not `git rebase` like rebasebot) and discovers releases by selecting the
newest `v*` tag beyond [`UPSTREAM-VERSION`](../UPSTREAM-VERSION) rather than
tracking a branch.

The workflow:

1. Compare `UPSTREAM-VERSION` to the newest upstream `v*` release tag.
2. If newer, run `./openshift/hack/rebase_upstream.sh <tag> main`.
3. Update golang builder pins (`.ci-operator.yaml`, `openshift/Dockerfile`) if
   the upstream Go version changed.
4. Attempt `make -f openshift/Makefile update-collections` and
   `make -f openshift/Makefile generate-requirements`. The script uses a working
   Docker or Podman engine, or `CONTAINER_ENGINE` when set. Generated files are
   replaced only after the container run succeeds.
5. Check that the four generated requirements filenames are referenced by the
   `openshift-5.1` image config in `openshift-eng/ocp-build-data`.
6. Push and open a PR. An unresolved builder, failed or skipped generation, or
   a failed image config check opens a draft PR and returns a non-zero exit
   status. The PR body names only the checks that need follow-up.

The bot does **not** auto-merge. A human reviews, verifies collections and
requirements, requests an ART test build, and merges.

### Credentials

The periodic uses `openshift-app-platform-shift-bot` via the existing
`test-credentials` secret. The GitHub App must be installed on this repo with
`contents:write` and `pull_requests:write`. It cannot merge.

### Prerequisites

`git`, `gh` (GitHub CLI), `go`, `python3`, `curl`, and a working `docker` or
`podman` engine (for collections and requirements generation). The Prow job
uses Podman with the `nested-podman` capability and registry pull credentials.
`oc` and those credentials allow the script to verify new Go builder images.

### Dry-run

To preview what the auto-rebase would do without making changes:

```sh
DRY_RUN=1 ./hack/auto-rebase.sh
```

To force a specific tag:

```sh
OVERRIDE_TAG=v1.43.0 DRY_RUN=1 ./hack/auto-rebase.sh
```

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OVERRIDE_TAG` | _(unset)_ | Rebase this tag instead of scanning |
| `REBASE_BRANCH` | `main` | Downstream branch to rebase onto |
| `UPSTREAM_REMOTE` | `upstream` | Remote name for upstream repo |
| `UPSTREAM_URL` | `https://github.com/operator-framework/ansible-operator-plugins.git` | URL for the upstream remote |
| `ORIGIN_REMOTE` | `origin` | Remote name for push |
| `ORIGIN_URL` | `https://github.com/${DEST_ORG_REPO}.git` | URL for the origin remote |
| `DEST_ORG_REPO` | `openshift/ansible-operator-plugins` | GitHub org/repo for PRs |
| `GITHUB_TOKEN` | _(required)_ | Token for push + `gh pr create` |
| `CONTAINER_ENGINE` | auto-detected | Override the engine used for generation |
| `DRY_RUN` | `0` | Only report what would happen |
| `FORCE_REMOTE_URLS` | `0` | Allow rewriting a fork's remote URLs |
| `ALLOW_BRANCH_DELETE` | `0` (auto `1` in CI) | Allow deleting stale local rebase branches |
| `GIT_AUTHOR_NAME` | `openshift-app-platform-shift-bot` | Git identity for commits |
| `GIT_AUTHOR_EMAIL` | `267347085+...@users.noreply.github.com` | Git identity email |

### Companion Prow job

The periodic job definition lives in `openshift/release` (not in this repo).
Follow the pattern from
[openshift/release#82799](https://github.com/openshift/release/pull/82799):

- **Job name:** `periodic-ci-openshift-ansible-operator-plugins-main-periodics-auto-rebase`
- **Schedule:** `0 6 * * 1` (Mondays 06:00 UTC)
- **Runs:** `./hack/auto-rebase.sh`
- **Credentials:** GitHub App `openshift-app-platform-shift-bot`
- **CI runner:** built from `src` with Podman and the `nested-podman` capability;
  `gh` and `oc` are installed in the job

## Manual rebase

## Verify upstream

Verify you have the upstream repo as a remote:

```
$ git remote -v
openshift       https://github.com/openshift/ansible-operator-plugins.git (fetch)
openshift       no_push (push)
origin  git@github.com:username/ansible-operator-plugins.git (fetch)
origin  git@github.com:username/ansible-operator-plugins.git (push)
upstream        https://github.com/operator-framework/ansible-operator-plugins.git (fetch)
upstream        no_push (push)
```

Ensure the `upstream` is up to date.

```
$ git fetch upstream
remote: Enumerating objects: 21, done.
remote: Counting objects: 100% (21/21), done.
remote: Compressing objects: 100% (15/15), done.
Unpacking objects: 100% (15/15), 17.36 KiB | 2.89 MiB/s, done.
remote: Total 15 (delta 8), reused 3 (delta 0), pack-reused 0
From https://github.com/operator-framework/ansible-operator-plugins
 * e3225a40..4c0a60dc  master                                                    -> upstream/master
```
## New release to main

Once the `upstream` has been verified, you can now sync the upstream release tag
you want. In the steps below, we will sync `v1.38.0` to `main`.

To rebase simply use the `rebase_upstream.sh` script.

`./openshift/hack/rebase_upstream.sh <UPSTREAM-TAG>`

<details>

<summary>Here is an example run using upstream tag <code>v1.38.0</code></summary>


```
$ ./openshift/hack/rebase_upstream.sh v1.38.0
Already on 'main'
Your branch is up to date with 'origin/main'.
Already up to date.
Switched to a new branch 'v1.38.0-rebase-main'
Auto-merging Makefile
CONFLICT (content): Merge conflict in Makefile
Auto-merging go.mod
CONFLICT (content): Merge conflict in go.mod
Auto-merging go.sum
CONFLICT (content): Merge conflict in go.sum
Auto-merging images/ansible-operator/Dockerfile
Auto-merging images/ansible-operator/Pipfile
CONFLICT (content): Merge conflict in images/ansible-operator/Pipfile
Auto-merging images/ansible-operator/Pipfile.lock
CONFLICT (content): Merge conflict in images/ansible-operator/Pipfile.lock
Auto-merging images/ansible-operator/pipfile.Dockerfile
Auto-merging internal/version/version.go
CONFLICT (content): Merge conflict in internal/version/version.go
Auto-merging testdata/memcached-molecule-operator/Makefile
CONFLICT (content): Merge conflict in testdata/memcached-molecule-operator/Makefile
Automatic merge failed; fix conflicts and then commit the result.
The following paths are ignored by one of your .gitignore files:
images/ansible-operator
hint: Use -f if you really want to add them.
hint: Disable this message with "git config set advice.addIgnoredFile false"
The following paths are ignored by one of your .gitignore files:
images/ansible-operator
hint: Use -f if you really want to add them.
hint: Disable this message with "git config set advice.addIgnoredFile false"
[v1.38.0-rebase-main 3cee93da] Merge upstream tag v1.38.0
output the commits pulled from upstream as part of rebase
4cab4eda (tag: v1.38.0, upstream/release-v1.38, upstream/main, upstream/HEAD) prepping for v1.38.0 release (#145)
10af011c scripts: add ignore-not-found for undeploy and uninstall to Makefile boiler plate (#106)
54d3fc84 updating dependencies to support k8s 1.32 (#142)
dc609070 (tag: v1.37.2, upstream/release-v1.37) prepping for v1.37.2 release (#140)
e7a55338 Fix CVE-2025-27516 by updating ansible-core to v2.18.3 (#139)
fac29c58 remove `--ignore 70612` from  pipenv check in pipfile.Dockerfile (#134)
c315031e prepping for v1.37.1 release (#128)
e2b748b2 fixing go and python cve (#126)
d88e9be0 (tag: v1.37.0) prepping for v1.37.0 release (#123)
83876cf1 updating to go 1.23 and UBI 9.5 (#122)
bef914f8 Update k8s dependencies to 1.31 (#107)
d23c8aa6 prepping for v1.36.1 release (#117)
3ad1b57a adding metrics-require-rbac flag, metrics-secure validation logic and corresponding scaffolding logic (#116)
3aaf1112 removing operator types from issues (#112)
[v1.38.0-rebase-main 62007ace] UPSTREAM: <drop>: Update vendor directory
 3474 files changed, 185246 insertions(+), 148228 deletions(-)
...
...
...
```
</details>

When the script is finished, you will be in a `UPSTREAM-TAG-rebase-main`
branch. In our example above we were in `v1.38.0-rebase-main`. For more
information about the output see the [breakdown of rebase_upstream.sh
output](#breakdown-of-rebase_upstreamsh-output) section below.

At this point, you _must_ verify if everything looks okay. Ensure that the `./openshift/release/ansible/ansible_collections` directory
and the requirements files in the `./openshift` directory are properly generated. This will require manual intervention and
inspection.

Once these directories have been verified, create a rebase PR downstream:

```
git push origin v1.38.0-rebase-main
```

Since the rebase process may include changes in the versions of the python packages,
the rebase PR should be checked using test builds to check if all the build dependencies
are satisfied for the python packages. You should reach out to the OpenShift ART
(Automated Release Tooling) team for creating the test build.


### Breakdown of `rebase_upstream.sh` output

Running `rebase_upstream.sh` will spew out a bunch of output. We'll break it down
here.

The script will verify if your branch is up to date and create a new branch
`UPSTREAM-TAG-rebase-main`.

```
$ ./openshift/hack/rebase_upstream.sh v1.38.0
Already on 'main'
Your branch is up to date with 'origin/main'.
Already up to date.
Switched to a new branch 'v1.38.0-rebase-main'
```

If there are any conflicts, it will identify those files. It will *always* choose
the file from the upstream tag.

```
CONFLICT (file location): ...
...
Auto-merging Makefile
CONFLICT (content): Merge conflict in Makefile
Auto-merging go.mod
CONFLICT (content): Merge conflict in go.mod
Auto-merging go.sum
CONFLICT (content): Merge conflict in go.sum
Auto-merging images/ansible-operator/Dockerfile
Auto-merging images/ansible-operator/Pipfile
CONFLICT (content): Merge conflict in images/ansible-operator/Pipfile
Auto-merging images/ansible-operator/Pipfile.lock
CONFLICT (content): Merge conflict in images/ansible-operator/Pipfile.lock
Auto-merging images/ansible-operator/pipfile.Dockerfile
Auto-merging internal/version/version.go
CONFLICT (content): Merge conflict in internal/version/version.go
Auto-merging testdata/memcached-molecule-operator/Makefile
CONFLICT (content): Merge conflict in testdata/memcached-molecule-operator/Makefile
Automatic merge failed; fix conflicts and then commit the result.
```

After removing the conflicted files listed above, the commits from the tags are
printed out:

```
[v1.38.0-rebase-main 3cee93da] Merge upstream tag v1.38.0
output the commits pulled from upstream as part of rebase
4cab4eda (tag: v1.38.0, upstream/release-v1.38, upstream/main, upstream/HEAD) prepping for v1.38.0 release (#145)
10af011c scripts: add ignore-not-found for undeploy and uninstall to Makefile boiler plate (#106)
54d3fc84 updating dependencies to support k8s 1.32 (#142)
dc609070 (tag: v1.37.2, upstream/release-v1.37) prepping for v1.37.2 release (#140)
e7a55338 Fix CVE-2025-27516 by updating ansible-core to v2.18.3 (#139)
fac29c58 remove `--ignore 70612` from  pipenv check in pipfile.Dockerfile (#134)
c315031e prepping for v1.37.1 release (#128)
e2b748b2 fixing go and python cve (#126)
d88e9be0 (tag: v1.37.0) prepping for v1.37.0 release (#123)
83876cf1 updating to go 1.23 and UBI 9.5 (#122)
bef914f8 Update k8s dependencies to 1.31 (#107)
d23c8aa6 prepping for v1.36.1 release (#117)
3ad1b57a adding metrics-require-rbac flag, metrics-secure validation logic and corresponding scaffolding logic (#116)
3aaf1112 removing operator types from issues (#112)
...
```

After the commits are listed, the vendor directory is updated:
```
[v1.38.0-rebase-main 62007ace] UPSTREAM: <drop>: Update vendor directory
 3474 files changed, 185246 insertions(+), 148228 deletions(-)
...
...
...
```

Then, the `ansible_collections` directory and the downstream requirements files are updated:

```
[v1.38.0-rebase-main e3b0c442] UPSTREAM: <carry>: Update ansible_collections directory

[v1.38.0-rebase-main dcd0d1b9] UPSTREAM: <carry>: Update downstream requirements
```

Finally you will get a completed message:

```
** Upstream merge complete! **
View the above incoming commits to verify all is well
(mirrors the commit listing the PR will show)

Now make a pull request.
```

## Patch release to specific release branch

There are times when you will want to bring an upstream patch release to the
downstream OpenShift release. For example, bringing down v1.37.2 to downstream
release-4.17.

We will use the same script, `rebase_upstream.sh` except we will add the branch
we want to patch.

```
./openshift/hack/rebase_upstream.sh v1.37.2 release-4.17
```

<details>

<summary>Here is the output of running the above script.</summary>

```
$ ./openshift/hack/rebase_upstream.sh v1.37.2 release-4.17
Switched to branch 'release-4.17'
Your branch is up to date with 'openshift/release-4.17'.
Already up to date.
Switched to a new branch 'v1.37.2-rebase-release-4.17'
Auto-merging go.mod
CONFLICT (content): Merge conflict in go.mod
Auto-merging go.sum
CONFLICT (content): Merge conflict in go.sum
Auto-merging images/ansible-operator/Pipfile
CONFLICT (content): Merge conflict in images/ansible-operator/Pipfile
Auto-merging images/ansible-operator/Pipfile.lock
CONFLICT (content): Merge conflict in images/ansible-operator/Pipfile.lock
Auto-merging images/ansible-operator/pipfile.Dockerfile
CONFLICT (content): Merge conflict in images/ansible-operator/pipfile.Dockerfile
Automatic merge failed; fix conflicts and then commit the result.
The following paths are ignored by one of your .gitignore files:
images/ansible-operator
hint: Use -f if you really want to add them.
hint: Disable this message with "git config set advice.addIgnoredFile false"
The following paths are ignored by one of your .gitignore files:
images/ansible-operator
hint: Use -f if you really want to add them.
hint: Disable this message with "git config set advice.addIgnoredFile false"
The following paths are ignored by one of your .gitignore files:
images/ansible-operator
hint: Use -f if you really want to add them.
hint: Disable this message with "git config set advice.addIgnoredFile false"
[v1.37.2-rebase-release-4.17 39db9574] Merge upstream tag v1.37.2
output the commits pulled from upstream as part of rebase
dc609070 (tag: v1.37.2, upstream/release-v1.37) prepping for v1.37.2 release (#140)
e7a55338 Fix CVE-2025-27516 by updating ansible-core to v2.18.3 (#139)
fac29c58 remove `--ignore 70612` from  pipenv check in pipfile.Dockerfile (#134)
c315031e prepping for v1.37.1 release (#128)
e2b748b2 fixing go and python cve (#126)
d88e9be0 (tag: v1.37.0) prepping for v1.37.0 release (#123)
83876cf1 updating to go 1.23 and UBI 9.5 (#122)
bef914f8 Update k8s dependencies to 1.31 (#107)
d23c8aa6 prepping for v1.36.1 release (#117)
3ad1b57a adding metrics-require-rbac flag, metrics-secure validation logic and corresponding scaffolding logic (#116)
3aaf1112 removing operator types from issues (#112)
50d76a42 (tag: v1.36.0) prepping for v1.36.0 release (#110)
4e0c617d adding adding ignore for CVE-2024-8775 (#111)
acf75942 in case of failure, we want to update the error to latest run (#62)
9871a1eb updating all non k8s go dependencies to latest (#108)
d5cde0cd Bump k8s dependencies to 1.30 (#102)
886b92ad Update github actions to use node 20 (#85)
3acad86d mark unsafe the non-spec obj parameter (#66)
f1aa5843 Updates ansible collections and ansible packages to supported versions (#105)
ab6893df Utilize GitHub Actions cache for image builds (#104)
9a6d15a1 Bump kubebuilder to 3.15.0 (with merge conflicts resolved) (#90)
8e08a453 Bump base image to RHEL9 and Python version to 3.12 (#101)
0818d9ab Bump base image to RHEL9 and Python version to 3.12
311f40b2 Fix deleted files
9dcddde9 bump kubebuilder to 3.15.0
36380ebe Update dependencies to resolve safety-cli alerts (#98)
3b42c75e Update dependencies to resolve safety-cli alerts
[v1.37.2-rebase-release-4.17 98007221] UPSTREAM: <drop>: Update vendor directory
 3224 files changed, 285459 insertions(+), 75421 deletions(-)
...
...
...
```
</details>

Just like sync to main, verify things look okay. Ensure that the `./openshift/release/ansible/ansible_collections` directory
and the requirements files in the `./openshift` directory are properly generated. This will require manual intervention and
inspection.

Once these directories have been verified, create a rebase PR downstream:

```
git push origin v1.37.2-rebase-release-4.17
```

# Generating `openshift/release/ansible/ansible_collections` directory

The downstream ansible-operator base image is pre-configured with the required `ansible_collections`
by copying them from the `openshift/release/ansible/ansible_collections` directory. However, this
directory should be kept updated and in-sync with the `testdata/memcached-molecule-operator/requirements.yml`
file.

For ensuring that the directory is in-sync with the file, run the following:
```
make -f openshift/Makefile update-collections
```

# Generating downstream requirements files

[Cachito](https://spaces.redhat.com/pages/viewpage.action?pageId=228017926#UpstreamSources(Cachito,Hermeto,ContainerFirst)-pip)
([upstream-docs](https://github.com/containerbuildsystem/cachito/blob/master/docs/pip.md))
is used for building the downstream ansible-operator base image. For ensuring the image is built without
any issues, the requirements files are needed to be generated from the upstream `images/Pipfile` and `images/Pipfile.lock` files.

For ensuring that the requirements files are in-sync with the `images/Pipfile` and `images/Pipfile.lock` files, run the following:
```
make -f openshift/Makefile generate-requirements
```

In addition to generation of these files, it should also be ensured that all these files are referenced in the image build
config of ansible-operator in the https://github.com/openshift-eng/ocp-build-data repo. For example, the 
[4.19 configuration](https://github.com/openshift-eng/ocp-build-data/blob/openshift-4.19/images/openshift-enterprise-ansible-operator.yml)
has all the generated requirements files added to it.

## Taking care of the conflicts while generating the build requirements files

More often than not, the generation of the downstream requirements files may fail when there are changes in the versions
of python packages in the Pipfile or Pipfile.lock files. As the generation of requirements files include the generation of
build requirements files, the failure in the generation of the files stems from the issue of conflicts in the build
dependencies of the python packages. The following steps can be used to take care of the conflicts:
- Get the build dependency of each python package

  For obtaining the build dependency of each python package the `openshift/hack/find_individual_builddeps.py` script
  can be used. This script runs the upstream
  [`pip_find_builddeps.py`](https://raw.githubusercontent.com/containerbuildsystem/cachito/master/bin/pip_find_builddeps.py)
  script repeatedly for each python package to find the corresponding build dependencies. It needs the requirements.txt file
  generated from the upstream `images/Pipfile` and `images/Pipfile.lock` files.

  However, it has been found that running the upstream `pip_find_builddeps.py` script multiple times on the same machine/container
  may skip some of the build dependecies of some python packages. A workaround for this issue can be to create a separate container
  for each python package where the requirements.txt file will only contain that python package. Once the `pip_find_builddeps.py`
  script finds the build dependencies and outputs them, the container can be removed. This step can be repeated for each of the
  python package.

- Separate out the conflicting build dependencies into different files

  The output of the build dependencies should be analyzed to understand the conflicts in the versions. Following is an example
  of such a conflict and how it can be resolved:

  ```Dockerfile
    # Resolve conflict with `setuptools_scm` version:
    #     - `setuptools_scm>=8` is required by requests-unixsocket.
    #     - `setuptools_scm<8` is required by kubernetes.
  ```
  In this example, the `setuptools_scm` is a build dependency of both `requests-unixsocket` and `kubernetes` packages. However,
  the version required by `requests-unixsocket` (>=8) is in direct conflict with the version required by `kubernetes` (<8). For
  creating build requirements files for these 2 packages, the conflicting versions should be separated out into different build
  requirements files. This can be done by commenting out one of these packages from the requirements.txt file when generating
  the first build requirements file and then uncommenting it. This will add the build dependency to the generated requirements
  file of the other python package. The package which was commented out can be added to a temporary requirements file and another
  build requirements file can be generated using it.

  The above example can be used as a guideline for solving such issues. There can be multiple such conflicts for different build
  dependencies, like `setuptools`, `setuptools_scm`, etc. The general approach should be to separate out the conflicting build
  dependencies into different files and also to minimize the number of build requirements files. For example, one of the conflicting
  version of `setuptools` can be added to one of the build requirements file along with one of the conflicting version of
  `setuptools_scm` and the other two conflicting versions can be added to a different build requirements file. However, it should be
  ensured while adding the python packages in different files, there are no conflicts in their build dependencies. If so, in such cases,
  creating another build requirements file can be one of the possible solutions.

  All these changes should be correctly reflected in the `openshift/Dockerfile.requirements` which is used for generating the requirements
  files. Once the changes are done then the `generate-requirements` make target in the `openshift/Makefile` should be run to generate
  the correct requirements files.


[upstream_repo]:https://github.com/operator-framework/ansible-operator-plugins/
