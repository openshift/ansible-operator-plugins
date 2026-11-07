#!/usr/bin/env bash
# Shared by the manual merge script and the CI wrapper. Run from the repo root.

commit_paths() {
  local message=$1
  shift
  git add -A -- "$@" || exit 1
  if ! git diff --cached --quiet -- "$@"; then
    # Commit errors are fatal even when a caller is collecting check failures.
    git commit -m "$message" -- "$@" || exit 1
  fi
}

generate_and_commit() {
  local kind=$1 target message
  local -a outputs
  case "$kind" in
    collections)
      target=update-collections
      message='Update ansible_collections directory'
      outputs=(openshift/release/ansible/ansible_collections)
      ;;
    requirements)
      target=generate-requirements
      message='Update downstream requirements'
      outputs=(openshift/requirements.txt openshift/requirements-build.txt
        openshift/requirements-build1.txt openshift/requirements-pre-build.txt openshift/Pipfile.lock)
      ;;
    *) echo "Unknown generation kind: $kind" >&2; exit 1 ;;
  esac
  make -f openshift/Makefile "$target" || return 1
  commit_paths "UPSTREAM: <carry>: ${message}" "${outputs[@]}"
}
