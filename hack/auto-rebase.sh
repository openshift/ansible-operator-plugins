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

# Verify the full compiler version, including its patch, in the actual image.
_verify_builder() {
  local new_go=$1 ocp=$2 output actual
  selected_builder="registry.ci.openshift.org/ocp/builder:rhel-9-golang-${new_go}-openshift-${ocp}"
  _builder_image_exists "$new_go" "$ocp" || return 1
  "$CONTAINER_ENGINE" pull "$selected_builder" >>"$check_artifacts/builder.log" 2>&1 || return 1
  output=$("$CONTAINER_ENGINE" run --rm --network=none --entrypoint=go "$selected_builder" version \
    2>>"$check_artifacts/builder.log") || return 1
  printf '%s: %s\n' "$selected_builder" "$output" >>"$check_artifacts/builder.log"
  actual=$(awk '$1 == "go" && $2 == "version" {print $3}' <<<"$output")
  "$security_helper" at-least "$actual" "$required_go"
}

# Inventory is a hint; an authenticated pull and compiler check prove suitability.
_resolve_builder_ocp() {
  local new_go=$1 current_ocp=$2 all_tags prefix ocp inventory
  command -v oc >/dev/null 2>&1 || return 1
  if _verify_builder "$new_go" "$current_ocp"; then printf '%s\n' "$current_ocp"; return; fi
  for inventory in 'builder ocp rhel-9-golang-' 'release openshift rhel-9-release-golang-'; do
    read -r name namespace prefix <<<"$inventory"
    if all_tags=$(oc get is "$name" -n "$namespace" -o jsonpath='{.status.tags[*].tag}' 2>/dev/null); then
      while IFS= read -r ocp; do
        [[ -n "$ocp" && "$ocp" != "$current_ocp" ]] || continue
        if _verify_builder "$new_go" "$ocp"; then printf '%s\n' "$ocp"; return; fi
      done < <(printf '%s\n' "$all_tags" | tr ' ' '\n' \
        | sed -n "s/^${prefix}${new_go//./\\.}-openshift-\\([0-9][0-9]*\\.[0-9][0-9]*\\)$/\\1/p" | sort -uVr)
    fi
  done
  while IFS= read -r ocp; do
    [[ "$ocp" != "$current_ocp" ]] || continue
    if _verify_builder "$new_go" "$ocp"; then printf '%s\n' "$ocp"; return; fi
  done < <(_builder_ocp_candidates "$current_ocp" | sort -uVr)
  return 1
}

remediate_go() {
  security_helper="$work_dir/go-security"
  if ! GOTOOLCHAIN=auto go build -mod=vendor -o "$security_helper" ./hack/go-security \
      >"$check_artifacts/helper-build.log" 2>&1; then
    fail_check "Go security: helper build failed (helper-build.log)"
    return
  fi
  if ! command -v osv-scanner >/dev/null 2>&1 \
    || ! osv-scanner --version 2>&1 | grep -q '^osv-scanner version: 2\.7\.1$'; then
    fail_check "Go security: checksum-verified OSV-Scanner 2.7.1 is required"
    return
  fi
  if "$security_helper" fix "$check_artifacts/go-security"; then
    commit_paths "UPSTREAM: <carry>: Remediate Go dependency advisories

$(cat "$check_artifacts/go-security/summary.txt")" go.mod go.sum vendor
    cat "$check_artifacts/go-security/summary.txt"
  else
    fail_check "Go security: remediation or rescan failed ($(cat "$check_artifacts/go-security/error.txt" 2>/dev/null || echo 'see security.log'))"
  fi
}

# Validation failures are recoverable; edits and commit failures are fatal.
update_golang_builder() {
  local new_go current_go current_ocp target_ocp old_suffix new_suffix
  selected_builder=''
  if [[ ! -x "$security_helper" ]] || ! required_go=$("$security_helper" required-go); then
    fail_check "Builder: could not read final Go/toolchain requirement"
    return
  fi
  new_go=${required_go%.*}
  [[ "$required_go" =~ ^[0-9]+\.[0-9]+$ ]] && new_go=$required_go
  current_go=$(sed -n 's/.*golang-\([0-9]*\.[0-9]*\).*/\1/p' .ci-operator.yaml | head -1)
  current_ocp=$(sed -n 's/.*openshift-\([0-9]*\.[0-9]*\).*/\1/p' .ci-operator.yaml | head -1)
  old_suffix="golang-${current_go}-openshift-${current_ocp}"
  if [[ -z "$current_go" || -z "$current_ocp" ]] \
    || ! grep -Fq "release-${old_suffix}" .ci-operator.yaml \
    || ! grep -Fq "$old_suffix" openshift/Dockerfile; then
    fail_check "Builder: .ci-operator.yaml and openshift/Dockerfile pins do not match"
    return
  fi
  if ! target_ocp=$(_resolve_builder_ocp "$new_go" "$current_ocp"); then
    fail_check "Builder: no verified image for Go ${required_go} or newer in Go ${new_go}"
    return
  fi
  selected_builder="registry.ci.openshift.org/ocp/builder:rhel-9-golang-${new_go}-openshift-${target_ocp}"
  new_suffix="golang-${new_go}-openshift-${target_ocp}"
  [[ "$old_suffix" != "$new_suffix" ]] || return 0
  log "Updating builder: ${old_suffix} -> ${new_suffix}"
  sed -i "s/release-${old_suffix//./\\.}/release-${new_suffix}/" .ci-operator.yaml
  sed -i "s/${old_suffix//./\\.}/${new_suffix}/" openshift/Dockerfile
  commit_paths "UPSTREAM: <carry>: Update golang builder to ${new_suffix}" .ci-operator.yaml openshift/Dockerfile
}

validate_go() {
  local check
  if [[ -z "$selected_builder" ]]; then
    fail_check "Go build and vet: skipped because no verified builder is available"
    return
  fi
  mkdir -p "$work_dir/go-cache"
  for check in build vet; do
    if ! "$CONTAINER_ENGINE" run --rm --network=none --user "$(id -u):$(id -g)" \
        -v "$REPO_ROOT:/workspace:ro,Z" -v "$work_dir/go-cache:/go-cache:Z" -w /workspace \
        -e HOME=/tmp -e GOCACHE=/go-cache -e GOPROXY=off -e GOTOOLCHAIN=local \
        --entrypoint=go "$selected_builder" "$check" -mod=vendor ./... \
        >"$check_artifacts/go-${check}.log" 2>&1; then
      fail_check "Go ${check}: failed in the selected builder (go-${check}.log)"
    fi
  done
}

refresh_credentials() {
  if [[ -n "${GITHUB_TOKEN_COMMAND:-}" ]]; then
    [[ -x "$GITHUB_TOKEN_COMMAND" ]] || die "GITHUB_TOKEN_COMMAND must name an executable token provider"
    GITHUB_TOKEN=$("$GITHUB_TOKEN_COMMAND") || die "GitHub token refresh failed"
  fi
  [[ -n "${GITHUB_TOKEN:-}" && "$GITHUB_TOKEN" != *$'\n'* ]] || die "A GitHub token is required"
  export GH_TOKEN="$GITHUB_TOKEN"
}

# Backticks in the Markdown body are intentionally literal.
# shellcheck disable=SC2016
create_pr() {
  local tag=$1 branch=$2 pin=$3
  local -a draft_args=()
  {
    printf '## Summary\nAutomated rebase to `%s` (previous pin: `%s`).\n' "$tag" "$pin"
    if ((${#failures[@]})); then
      printf '\n## Follow-up required\n'
      printf -- '- [ ] %s\n' "${failures[@]}"
      draft_args=(--draft)
    else
      printf '\nGo dependency security, builder, build, vet, collections, and requirements checks passed.\n'
    fi
    printf '\n## Human review\n- Review upstream changes and add needed `UPSTREAM: <carry>:` commits.\n- Request an ART test build to verify Python build dependencies.\n'
  } >"$work_dir/pr-body.md"
  gh pr create --repo "$DEST_ORG_REPO" --base "$REBASE_BRANCH" --head "$branch" \
    --title "Rebase to ${tag}" --body-file "$work_dir/pr-body.md" "${draft_args[@]}" \
    || die "Failed to create PR for ${branch}"
}

main() {
  local pin tag branch count tool kind
  local security_helper required_go selected_builder check_artifacts
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
  refresh_credentials
  for tool in gh go make; do
    command -v "$tool" >/dev/null || die "Missing required tool: ${tool}"
  done
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
  check_artifacts=${ARTIFACT_DIR:-$work_dir/artifacts}/auto-rebase-checks
  mkdir -p "$check_artifacts"
  git config user.name "${GIT_AUTHOR_NAME:-openshift-app-platform-shift-bot}"
  git config user.email "${GIT_AUTHOR_EMAIL:-267347085+openshift-app-platform-shift-bot@users.noreply.github.com}"
  git config --local --replace-all credential.helper ''
  git config --local --add credential.helper '!gh auth git-credential'
  git fetch origin "refs/heads/${REBASE_BRANCH}:refs/remotes/origin/${REBASE_BRANCH}"
  git checkout -B "$REBASE_BRANCH" "origin/$REBASE_BRANCH"
  git branch --set-upstream-to="origin/$REBASE_BRANCH" "$REBASE_BRANCH"
  SKIP_GENERATION=1 ORIGIN_REMOTE=origin ./openshift/hack/rebase_upstream.sh "$tag" "$REBASE_BRANCH" upstream

  remediate_go
  selected_builder=''
  if [[ -n "${CONTAINER_ENGINE:-}" ]] && command -v "$CONTAINER_ENGINE" >/dev/null 2>&1 \
    && "$CONTAINER_ENGINE" info >/dev/null 2>&1; then
    export CONTAINER_ENGINE
    update_golang_builder
    validate_go
    for kind in collections requirements; do
      if ! generate_and_commit "$kind"; then
        fail_check "Generation failed: ${kind}; regenerate and commit the result (see openshift/README.md)"
      fi
    done
  else
    fail_check "Builder, Go build/vet, collections and requirements: CONTAINER_ENGINE must name a working engine; generation skipped"
  fi
  [[ -z "$(git status --porcelain)" ]] || die "Unexpected uncommitted files after rebase checks"
  refresh_credentials
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
  refresh_credentials
  create_pr "$tag" "$branch" "$pin"
  ((${#failures[@]} == 0)) || die "Checks failed; draft PR opened for manual fixes"
  log "Auto-rebase complete for ${tag}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
