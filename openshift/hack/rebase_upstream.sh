#!/bin/bash
#
# This script takes as arguments:
# $1 - [REQUIRED] upstream version as the first argument to merge
# $2 - [optional] branch to update, defaults to main. could be a versioned release branch, e.g., release-4.19
# $3 - [optional] non-openshift remote to pull code from, defaults to upstream
#
#
# Warning: this script resolves all conflicts by overwritting the conflict with
# the upstream version. If a ansible-operator specific patch was made downstream that is
# not in the incoming upstream code, the changes will be lost.

# Start from the root directory of the repo
pushd $(dirname "${BASH_ROOT}")

version=$1
rebase_branch=${2:-main}
upstream_remote=${3:-upstream}

# sanity checks
if [[ -z "$version" ]]; then
  echo "Version argument must be defined."
  popd
  exit 1
fi

ansible_operator_plugins_repo=$(git remote get-url "$upstream_remote")
if [[ $ansible_operator_plugins_repo != "https://github.com/operator-framework/ansible-operator-plugins.git" ]]; then
  echo "Upstream remote url should be set to operator-framework/ansible-operator-plugins repo."
  popd
  exit 1
fi

# check state of working directory
git diff-index --quiet HEAD || { printf "!! Git status not clean, aborting !!\\n\\n%s" "$(git status)"; popd ; exit 1; }

# update remote, including tags (-t)
git fetch -t "$upstream_remote"

# do work on the correct branch
git checkout "$rebase_branch"
remote_branch=$(git rev-parse --abbrev-ref --symbolic-full-name @{u})
if [[ $? -ne 0 ]]; then
  echo "Your branch is not properly tracking upstream as required, aborting."
  popd
  exit 1
fi
git merge "$remote_branch"
git checkout -b "$version"-rebase-"$rebase_branch" || { echo "Expected branch $version-rebase-$rebase_branch to not exist, delete and retry."; popd ; exit 1; }

# do the merge, but don't commit so tweaks below are included in commit
git merge --no-commit tags/"$version"

# preserve our version of these files
git checkout HEAD -- OWNERS_ALIASES

# unmerged files are overwritten with the upstream copy
unmerged_files=$(git diff --name-only --diff-filter=U --exit-code)
differences=$?

if [[ $differences -eq 1 ]]; then
  unmerged_files_oneline=$(echo "$unmerged_files" | paste -s -d ' ')
  unmerged=$(git status --porcelain $unmerged_files_oneline | sed 's/ /,/')

  # both deleted => remove => DD
  # added by us => remove => AU
  # deleted by them => remove  => UD
  # deleted by us => remove => DU
  # added by them => add => UA
  # both added => take theirs => AA
  # both modified => take theirs => UU
  for line in $unmerged
  do
      IFS=","
      set $line
      case $1 in
          "DD" | "AU" | "UD" | "DU")
          git rm -- $2
          ;;
          "UA")
          git add -- $2
          ;;
          "AA" | "UU")
          git checkout --theirs -- $2
          git add -- $2
          ;;
      esac
  done

  if [[ $(git diff --check) ]]; then
    echo "All conflict markers should have been taken care of, aborting."
    popd
    exit 1
  fi

else
  unmerged_files="<NONE>"
fi

# just to make sure an old version merge is not being made
git diff --staged --quiet && { echo "No changed files in merge?! Aborting."; popd ; exit 1; }

# make local commit
git commit -m "Merge upstream tag $version" -m "Ansible Operator Plugins $version" -m "Merge executed via ./rebase-upstream.sh $version $upstream_remote $rebase_branch" -m "$(printf "Overwritten conflicts:\\n%s" "$unmerged_files")"

echo "output the commits pulled from upstream as part of rebase"
git --no-pager log --oneline "$(git merge-base origin/"$rebase_branch" tags/"$version")"..tags/"$version"

# update vendor directory, abort if there's an error encountered
go mod tidy && go mod vendor || { echo "go mod vendor failed. Aborting!"; popd ; exit 1; }
# make sure that the vendor directory is actually updated 
if ! git diff --quiet vendor/; then
  # add the changes of go mod vendor
  git add vendor
  # make local commit
  git commit -m "UPSTREAM: <drop>: Update vendor directory"
else
  echo "No changed files in vendor directory. Skipping add."
fi

# Generate the openshift/release/ansible/ansible_collections directory,
# abort if there's an error encountered
make -f openshift/Makefile update-collections || { echo "Updating ansible_collections directory failed. Aborting!"; popd ; exit 1; }
# make sure that the ansible_collections directory is actually updated 
if ! git diff --quiet openshift/release/ansible/ansible_collections/; then
  # add the changes made to the ansible_collections directory
  git add openshift/release/ansible/ansible_collections
  # make local commit
  git commit -m "UPSTREAM: <carry>: Update ansible_collections directory"
else
  echo "No changed files in ansible_collections directory. Skipping add."
fi

# Generate the requirements and build-requirements files corresponding to the
# images/ansible-operator/Pipfile and images/ansible-operator/Pipfile.lock
# files, abort if there's an error encountered. For solving the issues related
# to the failure of the generation of the downstream requirements files refer
# to the openshift/README.md file for more details.
make -f openshift/Makefile generate-requirements || { echo "Generate the requirements and build-requirements files failed. Aborting!"; popd ; exit 1; }
# make sure that the openshift directory is actually updated 
if ! git diff --quiet openshift/; then
  # add the changes made to the ansible_collections directory
  git add openshift/
  # make local commit
  git commit -m "UPSTREAM: <carry>: Update downstream requirements"
else
  echo "No changed files in openshift directory. Skipping add."
fi

printf "\\n** Upstream merge complete! **\\n"
echo "View the above incoming commits to verify all is well"
echo "(mirrors the commit listing the PR will show)"
echo ""
echo "Now make a pull request."

popd
