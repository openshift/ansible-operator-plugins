#!/usr/bin/env bash
# Run a generated-output container into staging, then replace tracked output.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_root"

kind=${1:?expected collections or requirements}
engine=${CONTAINER_ENGINE:-docker}
user_args=(-u "$(id -u):$(id -g)")
if [[ "$(basename -- "$engine")" == podman && "$(id -u)" != 0 ]]; then
  user_args=(--userns=keep-id "${user_args[@]}")
fi
stage=""
destination=""
completed=0
collections_installed=0
installed=()

cleanup() {
  local name
  if [[ "$completed" != 1 && -n "$stage" ]]; then
    if [[ "$kind" == collections ]]; then
      if [[ "$collections_installed" == 1 ]]; then
        rm -rf -- "$destination"
      fi
      if [[ -d "$stage/previous" ]]; then
        mv -- "$stage/previous" "$destination"
      fi
    else
      for name in ${installed[@]+"${installed[@]}"}; do
        rm -f -- "openshift/$name"
      done
      if [[ -d "$stage/previous" ]]; then
        for name in "$stage"/previous/*; do
          [[ -e "$name" ]] || continue
          mv -- "$name" openshift/
        done
      fi
    fi
  fi
  if [[ -n "$stage" ]]; then
    rm -rf -- "$stage"
  fi
}
trap cleanup EXIT

case "$kind" in
  collections)
    destination=openshift/release/ansible/ansible_collections
    stage=$(mktemp -d openshift/release/ansible/.collections-generation.XXXXXX)
    "$engine" run "${user_args[@]}" --rm \
      -v "$(pwd)/$stage:/tmp/ansible_collections/:Z" \
      "${COLLECTIONS_IMG:-get-collections}"
    [[ -d "$stage/ansible_collections" ]] || { echo "collections output missing" >&2; exit 1; }
    if [[ -e "$destination" ]]; then
      mv -- "$destination" "$stage/previous"
    fi
    mv -- "$stage/ansible_collections" "$destination"
    collections_installed=1
    ;;
  requirements)
    stage=$(mktemp -d openshift/.requirements-generation.XXXXXX)
    "$engine" run "${user_args[@]}" --rm \
      -v "$(pwd)/$stage:/tmp/requirements/:Z" \
      "${REQUIREMENTS_IMG:-pip-requirements}"
    outputs=(requirements.txt requirements-build.txt requirements-build1.txt \
      requirements-pre-build.txt Pipfile.lock)
    for name in "${outputs[@]}"; do
      [[ -f "$stage/$name" ]] || { echo "requirements output missing: $name" >&2; exit 1; }
    done
    mkdir "$stage/previous"
    for name in "${outputs[@]}"; do
      if [[ -e "openshift/$name" ]]; then
        mv -- "openshift/$name" "$stage/previous/$name"
      fi
    done
    for name in "${outputs[@]}"; do
      mv -- "$stage/$name" "openshift/$name"
      installed+=("$name")
    done
    ;;
  *)
    echo "unknown generation kind: $kind" >&2
    exit 2
    ;;
esac
completed=1
