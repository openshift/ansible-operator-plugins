#!/usr/bin/env bash
# Build a reproducible historical fixture with a complete, pinned tooling snapshot.
set -euo pipefail
if (($# != 5)); then
  echo "Usage: $0 SOURCE_REF BASELINE OLD_TAG NEW_TAG NEW_DIRECTORY" >&2
  exit 1
fi
source_ref=$(git rev-parse --verify "$1^{commit}")
baseline=$(git rev-parse --verify "$2^{commit}")
old=$3 new=$4 destination=$5
[[ "$old" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ && "$new" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$(git show "$baseline:UPSTREAM-VERSION" | tr -d '[:space:]')" == "$old" ]]
git merge-base --is-ancestor "refs/tags/$old" "$baseline"
if git merge-base --is-ancestor "refs/tags/$new" "$baseline"; then
  echo 'The historical baseline already contains the target release' >&2
  exit 1
fi
# Copy whole tooling directories, including documentation, instead of an ad hoc file list.
paths=(hack openshift/hack openshift/Makefile openshift/Dockerfile.requirements openshift/README.md)
git worktree add --detach "$destination" "$baseline"
git archive "$source_ref" "${paths[@]}" | tar -x -C "$destination"
[[ -s "$destination/openshift/hack/generate_requirements.md" ]]
{
  printf 'source %s\nbaseline %s\nfrom %s\nto %s\n' "$source_ref" "$baseline" "$old" "$new"
  git ls-tree -r --name-only "$source_ref" -- "${paths[@]}" | while IFS= read -r path; do
    (cd "$destination" && sha256sum "$path")
  done
} >"$destination/.rehearsal-manifest"
git -C "$destination" add -- "${paths[@]}" .rehearsal-manifest
git -C "$destination" commit -m "Rehearsal: apply complete tooling snapshot from ${source_ref}"
printf 'Fixture: %s\nCommit: %s\n' "$destination" "$(git -C "$destination" rev-parse HEAD)"
