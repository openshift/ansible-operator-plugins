#!/usr/bin/env bash
# Discover upstream releases and open rebase PRs from a disposable CI checkout.
# See openshift/README.md for prerequisites and environment configuration.
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
# shellcheck source=openshift/hack/rebase-lib.sh
source "$REPO_ROOT/openshift/hack/rebase-lib.sh"

REBASE_BRANCH=${REBASE_BRANCH:-main}
DEST_ORG_REPO=${DEST_ORG_REPO:-openshift/ansible-operator-plugins}
BUILD_DATA_BRANCH=${BUILD_DATA_BRANCH:-openshift-5.1}
upstream_url=https://github.com/operator-framework/ansible-operator-plugins.git
failures=()

log() { printf '==> %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
fail_check() { log "WARNING: $*"; failures+=("$*"); }

# Accept canonical HTTPS/SSH URLs, but never print potentially credentialed URLs.
check_remote() {
  local name=$1 repo=$2 url
  url=$(git remote get-url "$name") || die "Missing remote ${name}"
  [[ "$url" == "https://github.com/${repo}" || "$url" == "https://github.com/${repo}.git" \
    || "$url" == "git@github.com:${repo}.git" || "$url" == "git@github.com:${repo}" \
    || "$url" == "ssh://git@github.com/${repo}.git" || "$url" == "ssh://git@github.com/${repo}" ]] \
    || die "Remote ${name} must point to ${repo}; use a fresh CI checkout"
}

# One checked query; exclude peeled tag refs and prereleases.
newest_upstream_tag() {
  local pin=$1 refs newest
  refs=$(git ls-remote --tags --refs "$upstream_url" 'v*') \
    || die "Failed to query upstream tags"
  newest=$(printf '%s\n' "$refs" | awk '$2 ~ /^refs\/tags\/v[0-9]+\.[0-9]+\.[0-9]+$/ {sub("refs/tags/", "", $2); print $2}' \
    | sort -V | tail -1)
  if [[ -n "$newest" && "$newest" != "$pin" \
    && "$(printf '%s\n%s\n' "$pin" "$newest" | sort -V | tail -1)" == "$newest" ]]; then
    printf '%s\n' "$newest"
  fi
  return 0
}

# Select the current OCP version when present, otherwise the newest matching tag.
_pick_ocp_from_tags() {
  local current_ocp=$1 prefix=$2 all_tags=$3 best_ocp
  if printf '%s\n' "$all_tags" | tr ' ' '\n' | grep -qxF "${prefix}${current_ocp}"; then
    printf '%s\n' "$current_ocp"
    return 0
  fi
  best_ocp=$(printf '%s\n' "$all_tags" | tr ' ' '\n' \
    | sed -n "s/^${prefix}\([0-9][0-9]*\.[0-9][0-9]*\)$/\1/p" \
    | sort -V | tail -1)
  [[ -n "$best_ocp" ]] || return 1
  printf '%s\n' "$best_ocp"
}

_builder_ocp_candidates() {
  local major=${1%%.*} minor=${1#*.} i
  [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || return 1
  for ((i = 0; i <= 4; i++)); do printf '%s.%s\n' "$major" "$((minor + i))"; done
  if [[ "$major" -eq 4 ]]; then
    for i in 0 1 2 3; do printf '5.%s\n' "$i"; done
  fi
}

_builder_image_exists() {
  local new_go=$1 ocp=$2 secret
  local ref="registry.ci.openshift.org/ocp/builder:rhel-9-golang-${new_go}-openshift-${ocp}"
  local -a args=("$ref" --filter-by-os=linux/amd64)
  for secret in /var/run/secrets/ci-pull-credentials/.dockerconfigjson \
                /var/run/secrets/registry-pull--build-farms/.dockerconfigjson; do
    if [[ -f "$secret" ]]; then
      args+=("--registry-config=$secret")
      break
    fi
  done
  oc image info "${args[@]}" >/dev/null 2>&1
}

# Try app.ci and build-farm imagestreams, then authenticated registry probes.
_resolve_builder_ocp() {
  local new_go=$1 current_ocp=$2 all_tags best_ocp ocp
  if ! command -v oc >/dev/null 2>&1; then
    log "oc not on PATH; cannot resolve builder image"
    return 1
  fi
  if all_tags=$(oc get is builder -n ocp \
      -o jsonpath='{.status.tags[*].tag}' 2>/dev/null) && [[ -n "$all_tags" ]]; then
    if best_ocp=$(_pick_ocp_from_tags "$current_ocp" \
        "rhel-9-golang-${new_go}-openshift-" "$all_tags"); then
      printf '%s\n' "$best_ocp"
      return 0
    fi
    log "ocp/builder has no matching Go tag; trying openshift/release"
  else
    log "ocp/builder unavailable; trying openshift/release"
  fi
  if all_tags=$(oc get is release -n openshift \
      -o jsonpath='{.status.tags[*].tag}' 2>/dev/null) && [[ -n "$all_tags" ]]; then
    if best_ocp=$(_pick_ocp_from_tags "$current_ocp" \
        "rhel-9-release-golang-${new_go}-openshift-" "$all_tags"); then
      if _builder_image_exists "$new_go" "$best_ocp"; then
        printf '%s\n' "$best_ocp"
        return 0
      fi
      log "openshift/release has golang-${new_go}-openshift-${best_ocp}, but ocp/builder image is unavailable"
    else
      log "openshift/release has no matching Go tag; trying registry"
    fi
  else
    log "openshift/release unavailable; trying registry"
  fi
  if _builder_image_exists "$new_go" "$current_ocp"; then
    printf '%s\n' "$current_ocp"
    return 0
  fi
  while IFS= read -r ocp; do
    [[ -n "$ocp" && "$ocp" != "$current_ocp" ]] || continue
    if _builder_image_exists "$new_go" "$ocp"; then
      printf '%s\n' "$ocp"
      return 0
    fi
  done < <(_builder_ocp_candidates "$current_ocp" | sort -uVr)
  return 1
}

# Validation failures are recoverable; edits and commit failures are fatal.
update_golang_builder() {
  local new_go current_go current_ocp target_ocp old_suffix new_suffix
  if [[ ! -f go.mod || ! -f .ci-operator.yaml || ! -f openshift/Dockerfile ]]; then
    fail_check "Builder: missing go.mod, .ci-operator.yaml, or openshift/Dockerfile"
    return
  fi
  new_go=$(awk '/^go /{split($2, a, "."); print a[1]"."a[2]}' go.mod)
  current_go=$(sed -n 's/.*golang-\([0-9]*\.[0-9]*\).*/\1/p' .ci-operator.yaml | head -1)
  current_ocp=$(sed -n 's/.*openshift-\([0-9]*\.[0-9]*\).*/\1/p' .ci-operator.yaml | head -1)
  if [[ ! "$new_go" =~ ^[0-9]+\.[0-9]+$ || -z "$current_go" || -z "$current_ocp" ]]; then
    fail_check "Builder: could not parse Go/OCP versions from go.mod and .ci-operator.yaml"
    return
  fi
  old_suffix="golang-${current_go}-openshift-${current_ocp}"
  if [[ ! -f openshift/Dockerfile ]] \
    || ! grep -Fq "release-${old_suffix}" .ci-operator.yaml \
    || ! grep -Fq "$old_suffix" openshift/Dockerfile; then
    fail_check "Builder: .ci-operator.yaml and openshift/Dockerfile pins do not match"
    return
  fi
  [[ "$new_go" != "$current_go" ]] || return 0
  if ! target_ocp=$(_resolve_builder_ocp "$new_go" "$current_ocp"); then
    fail_check "Builder: no verified image for Go ${new_go}; update both builder pins manually"
    return
  fi
  new_suffix="golang-${new_go}-openshift-${target_ocp}"
  log "Updating builder: ${old_suffix} -> ${new_suffix}"
  # Escape version dots so substitutions match only the literal old pin.
  sed -i "s/release-${old_suffix//./\\.}/release-${new_suffix}/" .ci-operator.yaml
  sed -i "s/${old_suffix//./\\.}/${new_suffix}/" openshift/Dockerfile
  commit_paths "UPSTREAM: <carry>: Update golang builder to ${new_suffix}" .ci-operator.yaml openshift/Dockerfile
}

# Select once; generation itself reports container failures through its exit code.
select_container_engine() {
  local engine
  for engine in ${CONTAINER_ENGINE:-docker podman}; do
    if command -v "$engine" >/dev/null 2>&1 && "$engine" info >/dev/null 2>&1; then
      printf '%s\n' "$engine"
      return 0
    fi
  done
  return 1
}

check_build_data_requirements() {
  local url="https://raw.githubusercontent.com/openshift-eng/ocp-build-data/${BUILD_DATA_BRANCH}/images/openshift-enterprise-ansible-operator.yml"
  if ! curl --fail --silent --show-error --location --retry 2 \
    --connect-timeout 10 --max-time 30 --output "$work_dir/build-data.yaml" "$url"; then
    fail_check "Image build config: could not read ${BUILD_DATA_BRANCH} in ocp-build-data"
  elif ! python3 - "$work_dir/build-data.yaml" <<'PYTHON'
import sys
import yaml

expected = {
    "requirements_files": {"requirements.txt"},
    "requirements_build_files": {
        "requirements-build.txt", "requirements-build1.txt", "requirements-pre-build.txt",
    },
}
try:
    with open(sys.argv[1], encoding="utf-8") as config:
        entries = yaml.safe_load(config)["cachito"]["packages"]["pip"]
    matches = [entry for entry in entries if entry.get("path") == "openshift"]
    if len(matches) != 1:
        raise ValueError("expected one pip entry with path: openshift")
    for key, required in expected.items():
        values = matches[0].get(key)
        if not isinstance(values, list) or not required.issubset(values):
            raise ValueError(f"{key} must reference {', '.join(sorted(required))}")
except (OSError, yaml.YAMLError, KeyError, TypeError, AttributeError, ValueError) as error:
    sys.exit(f"Invalid build-data requirements: {error}")
PYTHON
  then
    fail_check "Image build config: invalid requirements references in ${BUILD_DATA_BRANCH}"
  fi
}

# The upstream merge commit records files that were resolved to upstream.
merge_conflicts() {
  local tag=$1
  git log -1 --format=%B --fixed-strings --grep="Merge upstream tag ${tag}" \
    | sed -n '/^Overwritten conflicts:$/,$p' \
    | sed '1d' \
    | awk 'NF == 0 { exit } $0 != "<NONE>" { print }'
}

# Backticks in the Markdown body are intentionally literal.
# shellcheck disable=SC2016
create_pr() {
  local tag=$1 branch=$2 pin=$3 conflicts
  local -a draft_args=()
  conflicts=$(merge_conflicts "$tag")
  {
    printf '## Summary\nAutomated rebase to `%s` (previous pin: `%s`).\n' "$tag" "$pin"
    if ((${#failures[@]})); then
      printf '\n## Follow-up required\n'
      printf -- '- [ ] %s\n' "${failures[@]}"
      draft_args=(--draft)
    else
      printf '\nBuilder, collections, requirements, and image build config checks passed.\n'
    fi
    if [[ -n "$conflicts" ]]; then
      printf '\n## Conflicts resolved to upstream\n```text\n%s\n```\n' "$conflicts"
    fi
    printf '\n## Human review\n- Review upstream changes and add needed `UPSTREAM: <carry>:` commits.\n- Request an ART test build to verify Python build dependencies.\n'
  } >"$work_dir/pr-body.md"
  gh pr create --repo "$DEST_ORG_REPO" --base "$REBASE_BRANCH" --head "$branch" \
    --title "Rebase to ${tag}" --body-file "$work_dir/pr-body.md" "${draft_args[@]}" \
    || die "Failed to create PR for ${branch}"
}

main() {
  local pin tag branch count engine tool
  pin=$(tr -d '[:space:]' <UPSTREAM-VERSION)
  [[ "$pin" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Invalid UPSTREAM-VERSION"
  if [[ -n "${OVERRIDE_TAG:-}" ]]; then
    tag=$OVERRIDE_TAG
  else
    tag=$(newest_upstream_tag "$pin")
  fi
  if [[ -z "$tag" ]]; then
    log "No newer upstream release than ${pin}"
    return
  fi
  [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Expected a stable vMAJOR.MINOR.PATCH tag"
  branch="${tag}-rebase-${REBASE_BRANCH}"
  log "Candidate rebase: ${pin} -> ${tag} (${branch})"
  if [[ "${DRY_RUN:-0}" == 1 ]]; then
    log "DRY_RUN=1: would run rebase_upstream.sh ${tag} ${REBASE_BRANCH} upstream, validate, push, and open a PR"
    return
  fi

  [[ -n "${OPENSHIFT_CI:-}${CI:-}${JOB_NAME:-}" ]] || die "Real runs require a disposable CI checkout; use DRY_RUN=1 locally"
  [[ -z "$(git status --porcelain)" ]] || die "Working tree must be clean, including untracked files"
  [[ -n "${GITHUB_TOKEN:-}" ]] || die "GITHUB_TOKEN is required"
  export GH_TOKEN="$GITHUB_TOKEN"
  for tool in gh go make curl python3; do
    command -v "$tool" >/dev/null || die "Missing required tool: ${tool}"
  done
  python3 -c 'import yaml' || die "Python PyYAML is required"
  [[ -n "$BUILD_DATA_BRANCH" ]] || die "BUILD_DATA_BRANCH is required"
  [[ "$DEST_ORG_REPO" =~ ^[[:alnum:]_.-]+/[[:alnum:]_.-]+$ ]] || die "Invalid DEST_ORG_REPO"
  check_remote origin "$DEST_ORG_REPO"
  # Reject a separate push URL as well as mismatched fetch URLs.
  [[ "$(git remote get-url --push origin)" == "$(git remote get-url origin)" ]] \
    || die "Origin must use the same fetch and push URL"
  if git remote get-url upstream >/dev/null 2>&1; then
    check_remote upstream operator-framework/ansible-operator-plugins
  else
    git remote add upstream "$upstream_url"
  fi
  count=$(gh pr list --repo "$DEST_ORG_REPO" --state open --head "$branch" --base "$REBASE_BRANCH" \
    --json number --jq 'length') || die "Failed to query existing PRs"
  if [[ "$count" -gt 0 ]]; then
    log "Open PR for ${tag} already exists; skipping"
    return
  fi

  work_dir=$(mktemp -d)
  trap 'rm -rf -- "$work_dir"' EXIT
  git config user.name "${GIT_AUTHOR_NAME:-openshift-app-platform-shift-bot}"
  git config user.email "${GIT_AUTHOR_EMAIL:-267347085+openshift-app-platform-shift-bot@users.noreply.github.com}"
  git config --local --replace-all credential.helper ''
  git config --local --add credential.helper '!gh auth git-credential'
  git fetch origin "refs/heads/${REBASE_BRANCH}:refs/remotes/origin/${REBASE_BRANCH}"
  git checkout -B "$REBASE_BRANCH" "origin/$REBASE_BRANCH"
  git branch --set-upstream-to="origin/$REBASE_BRANCH" "$REBASE_BRANCH"
  SKIP_GENERATION=1 ORIGIN_REMOTE=origin ./openshift/hack/rebase_upstream.sh "$tag" "$REBASE_BRANCH" upstream

  update_golang_builder
  if engine=$(select_container_engine); then
    export CONTAINER_ENGINE="$engine"
    if ! generate_and_commit collections; then
      fail_check "Collections: run make -f openshift/Makefile update-collections and commit the result"
    fi
    if generate_and_commit requirements; then
      check_build_data_requirements
    else
      fail_check "Requirements: run make -f openshift/Makefile generate-requirements and commit the result"
      fail_check "Image build config: skipped because requirements generation failed"
    fi
  else
    fail_check "Collections and requirements: no working container engine; generation skipped"
    fail_check "Image build config: skipped because requirements generation did not run"
  fi
  [[ -z "$(git status --porcelain)" ]] || die "Unexpected uncommitted files after rebase checks"
  if ! git push -u origin "$branch"; then
    # A previous run may have pushed successfully before PR creation failed.
    git fetch --no-tags origin "refs/heads/${branch}" \
      || die "Push failed and the existing branch ${branch} could not be fetched"
    if ! git diff --quiet HEAD FETCH_HEAD -- \
      || ! git merge-base --is-ancestor "refs/tags/$tag" FETCH_HEAD \
      || ! git merge-base --is-ancestor "origin/$REBASE_BRANCH" FETCH_HEAD; then
      die "Remote branch ${branch} has different contents or missing ancestry; leaving it unchanged"
    fi
    git checkout --detach FETCH_HEAD
    log "Reusing verified remote branch ${branch} to retry PR creation"
  fi
  create_pr "$tag" "$branch" "$pin"
  ((${#failures[@]} == 0)) || die "Checks failed; draft PR opened for manual fixes"
  log "Auto-rebase complete for ${tag}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
