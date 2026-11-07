#!/bin/bash
#
# This script takes as arguments:
# $1 - [REQUIRED] upstream version as the first argument to merge
# $2 - [optional] branch to update, defaults to main. could be a versioned release branch, e.g., release-4.19
# $3 - [optional] non-openshift remote to pull code from, defaults to upstream
#
# Warning: this script resolves all conflicts by overwritting the conflict with
# the upstream version. If a ansible-operator specific patch was made downstream that is
# not in the incoming upstream code, the changes will be lost.
#
# Origin remote is assumed to point to openshift/ansible-operator-plugins

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$REPO_ROOT" || exit 1

# shellcheck source=openshift/hack/rebase-lib.sh
source "$REPO_ROOT/openshift/hack/rebase-lib.sh"

version=${1:-}
rebase_branch=${2:-main}
upstream_remote=${3:-upstream}
origin_remote=${ORIGIN_REMOTE:-origin}

# sanity checks
if [[ -z "$version" ]]; then
  echo "Version argument must be defined."
  exit 1
fi

ansible_repo=$(git remote get-url "$upstream_remote")
# Only accept HTTPS or SSH forms — reject bare hostnames (git treats them as local paths).
if [[ ! "$ansible_repo" =~ ^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)operator-framework/ansible-operator-plugins(\.git)?/?$ ]]; then
  echo "Upstream remote url should point at operator-framework/ansible-operator-plugins via HTTPS or SSH (git@/https://)."
  exit 1
fi

# check state of working directory
git diff-index --quiet HEAD || { printf "!! Git status not clean, aborting !!\n\n%s" "$(git status)"; exit 1; }

# update remote, including tags (-t)
git fetch -t "$upstream_remote"

# do work on the correct branch
git checkout "$rebase_branch" || { echo "Failed to checkout $rebase_branch, aborting."; exit 1; }
if ! remote_branch=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}'); then
  echo "Your branch is not properly tracking a remote as required, aborting."
  exit 1
fi
if ! git merge "$remote_branch"; then
  if git rev-parse -q --verify MERGE_HEAD >/dev/null; then
    git merge --abort || { echo "Failed to abort merge $remote_branch."; exit 1; }
  fi
  echo "Failed to merge $remote_branch, aborting."
  exit 1
fi
git checkout -b "$version"-rebase-"$rebase_branch" || { echo "Expected branch $version-rebase-$rebase_branch to not exist, delete and retry."; exit 1; }

# do the merge, but don't commit so tweaks below are included in commit
if ! git merge --no-ff --no-commit "tags/$version"; then
  if ! git rev-parse -q --verify MERGE_HEAD >/dev/null; then
    echo "Failed to merge tags/$version, aborting."
    exit 1
  fi
fi

# preserve our version of these files
git checkout HEAD -- OWNERS_ALIASES

# unmerged files are overwritten with the upstream copy
unmerged_files=$(git diff --name-only --diff-filter=U)

if [[ -n "$unmerged_files" ]]; then
  # Resolve each unmerged file: remove deletions, take upstream on conflicts.
  while IFS= read -r fname; do
    [[ -n "$fname" ]] || continue
    sts=$(git status --porcelain -- "$fname" | cut -c1-2)
    case "$sts" in
      DD|AU|UD)
        git rm -- "$fname"
        ;;
      DU)
        git checkout --theirs -- "$fname"
        git add -- "$fname"
        ;;
      UA)
        git add -- "$fname"
        ;;
      AA|UU)
        git checkout --theirs -- "$fname"
        git add -- "$fname"
        ;;
      *) echo "Unhandled conflict status: $sts" >&2; exit 1 ;;
    esac
  done <<< "$unmerged_files"

else
  unmerged_files="<NONE>"
fi

# Upstream whitespace is preserved; only unresolved index entries block the merge.
if ! git diff --quiet --diff-filter=U --; then
  echo "Unresolved merge conflicts remain, aborting." >&2
  exit 1
fi

# just to make sure an old version merge is not being made
git diff --staged --quiet && { echo "No changed files in merge?! Aborting."; exit 1; }

# bump UPSTREAM-VERSION file
echo "$version" > UPSTREAM-VERSION
git add UPSTREAM-VERSION

# make local commit
if ! git commit -m "Merge upstream tag $version" -m "Ansible Operator Plugins $version" -m "Merge executed via ./openshift/hack/rebase_upstream.sh $version $rebase_branch $upstream_remote" -m "$(printf "Overwritten conflicts:\n%s" "$unmerged_files")"; then
  echo "Failed to create the upstream merge commit, aborting."
  exit 1
fi

echo "output the commits pulled from upstream as part of rebase"
merge_base=$(git merge-base "$origin_remote/$rebase_branch" "tags/$version") || exit 1
git --no-pager log --oneline "${merge_base}..tags/$version"

# update vendor directory, abort if there's an error encountered
if ! go mod tidy || ! go mod vendor; then
  echo "go mod vendor failed. Aborting!"
  exit 1
fi
commit_paths "UPSTREAM: <drop>: Update vendor directory" go.mod go.sum vendor

# Manual rebases stop at the first generation failure. The CI wrapper runs
# these same steps independently and reports failures in a draft PR.
if [[ "${SKIP_GENERATION:-0}" != "1" ]]; then
  generate_and_commit collections || { echo "Updating collections failed." >&2; exit 1; }
  generate_and_commit requirements || { echo "Generating requirements failed." >&2; exit 1; }
fi

printf "\\n** Upstream merge complete! **\\n"
echo "View the above incoming commits to verify all is well"
echo "(mirrors the commit listing the PR will show)"
echo ""
echo "Now make a pull request."
