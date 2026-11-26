#!/usr/bin/env bash
# Shared by the manual merge script and the CI wrapper. Run from the repo root.

# Commit the given paths if they changed. Commit errors are always fatal.
commit_paths() {
  local message=$1
  shift
  git add -A -- "$@" || exit 1
  if ! git diff --cached --quiet -- "$@"; then
    git commit -m "$message" -- "$@" || exit 1
  fi
}

# Regenerate collections or requirements and commit the result. On failure the
# committed outputs are restored so partial container output is never committed.
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
  if make -f openshift/Makefile "$target" && ls -d -- "${outputs[@]}" >/dev/null 2>&1; then
    commit_paths "UPSTREAM: <carry>: ${message}" "${outputs[@]}"
    return 0
  fi
  # Restore committed state so partial output is never left behind.
  git checkout HEAD -- "${outputs[@]}" 2>/dev/null
  git clean -fdq -- "${outputs[@]}" 2>/dev/null
  return 1
}
