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

# Print the newest stable upstream tag newer than the pin, or nothing.
newest_upstream_tag() {
  local pin=$1 newest
  newest=$(git ls-remote --tags --refs "$upstream_url" 'v*' \
    | awk -F'refs/tags/' '$2 ~ /^v[0-9]+\.[0-9]+\.[0-9]+$/ {print $2}' | sort -V | tail -1) \
    || die "Failed to query upstream tags"
  if [[ -n "$newest" && "$newest" != "$pin" \
    && "$(printf '%s\n' "$pin" "$newest" | sort -V | tail -1)" == "$newest" ]]; then
    printf '%s\n' "$newest"
  fi
}

# Bump the Go builder pins when upstream bumps go.mod. The OCP version is left
# alone; if the resulting image does not exist, CI on the PR says so.
update_golang_builder() {
  local new_go current_go
  new_go=$(awk '/^go /{split($2, a, "."); print a[1]"."a[2]}' go.mod)
  current_go=$(sed -n 's/.*golang-\([0-9]*\.[0-9]*\)-openshift-.*/\1/p' .ci-operator.yaml | head -1)
  if [[ -z "$new_go" || -z "$current_go" ]] \
    || ! grep -Fq "golang-${current_go}-openshift-" openshift/Dockerfile; then
    fail_check "Builder: Go pins in .ci-operator.yaml and openshift/Dockerfile are missing or disagree; update both manually"
    return
  fi
  [[ "$new_go" != "$current_go" ]] || return 0
  log "Updating golang builder pins: ${current_go} -> ${new_go}"
  sed -i "s/golang-${current_go//./\\.}-openshift-/golang-${new_go}-openshift-/" \
    .ci-operator.yaml openshift/Dockerfile
  commit_paths "UPSTREAM: <carry>: Update golang builder to Go ${new_go}" \
    .ci-operator.yaml openshift/Dockerfile
}

# Backticks in the Markdown body are intentionally literal.
# shellcheck disable=SC2016
create_pr() {
  local tag=$1 branch=$2 pin=$3 body status
  local -a draft_args=()
  if ((${#failures[@]})); then
    draft_args=(--draft)
    status=$(printf '## Follow-up required\n'; printf -- '- [ ] %s\n' "${failures[@]}")
  else
    status="Collections and requirements generated. Builder pins follow go.mod and are not verified against the registry."
  fi
  body=$(printf '## Summary\nAutomated rebase to `%s` (previous pin: `%s`).\n\n%s\n\n## Human review\n- Review upstream changes and add needed `UPSTREAM: <carry>:` commits.\n- Request an ART test build to verify Python build dependencies.\n' \
    "$tag" "$pin" "$status")
  gh pr create --repo "$DEST_ORG_REPO" --base "$REBASE_BRANCH" --head "$branch" \
    --title "Rebase to ${tag}" --body "$body" "${draft_args[@]}" \
    || die "Failed to create PR for ${branch}"
}

main() {
  local pin tag branch count tool kind
  pin=$(tr -d '[:space:]' <UPSTREAM-VERSION)
  [[ "$pin" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Invalid UPSTREAM-VERSION"
  tag=${OVERRIDE_TAG:-$(newest_upstream_tag "$pin")}
  if [[ -z "$tag" ]]; then
    log "No newer upstream release than ${pin}"
    return
  fi
  [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Expected a stable vMAJOR.MINOR.PATCH tag"
  branch="${tag}-rebase-${REBASE_BRANCH}"
  log "Candidate rebase: ${pin} -> ${tag} (${branch})"
  if [[ "${DRY_RUN:-0}" == 1 ]]; then
    log "DRY_RUN=1: would run rebase_upstream.sh ${tag} ${REBASE_BRANCH} upstream, push, and open a PR"
    return
  fi

  [[ -n "${OPENSHIFT_CI:-}${CI:-}${JOB_NAME:-}" ]] || die "Real runs require a disposable CI checkout; use DRY_RUN=1 locally"
  [[ -z "$(git status --porcelain)" ]] || die "Working tree must be clean, including untracked files"
  [[ -n "${GITHUB_TOKEN:-}" ]] || die "GITHUB_TOKEN is required"
  export GH_TOKEN="$GITHUB_TOKEN"
  for tool in gh go make; do
    command -v "$tool" >/dev/null || die "Missing required tool: ${tool}"
  done
  git remote add upstream "$upstream_url" 2>/dev/null || true
  count=$(gh pr list --repo "$DEST_ORG_REPO" --state open --head "$branch" --base "$REBASE_BRANCH" \
    --json number --jq 'length') || die "Failed to query existing PRs"
  if [[ "$count" -gt 0 ]]; then
    log "Open PR for ${tag} already exists; skipping"
    return
  fi

  git config user.name "${GIT_AUTHOR_NAME:-openshift-app-platform-shift-bot}"
  git config user.email "${GIT_AUTHOR_EMAIL:-267347085+openshift-app-platform-shift-bot@users.noreply.github.com}"
  git config --local --replace-all credential.helper ''
  git config --local --add credential.helper '!gh auth git-credential'
  git fetch origin "refs/heads/${REBASE_BRANCH}:refs/remotes/origin/${REBASE_BRANCH}"
  git checkout -B "$REBASE_BRANCH" "origin/$REBASE_BRANCH"
  git branch --set-upstream-to="origin/$REBASE_BRANCH" "$REBASE_BRANCH"
  SKIP_GENERATION=1 ./openshift/hack/rebase_upstream.sh "$tag" "$REBASE_BRANCH" upstream

  update_golang_builder
  if [[ -n "${CONTAINER_ENGINE:-}" ]] && command -v "$CONTAINER_ENGINE" >/dev/null 2>&1 \
    && "$CONTAINER_ENGINE" info >/dev/null 2>&1; then
    export CONTAINER_ENGINE
    for kind in collections requirements; do
      if ! generate_and_commit "$kind"; then
        fail_check "Generation failed: ${kind}; regenerate and commit the result (see openshift/README.md)"
      fi
    done
  else
    fail_check "Collections and requirements: CONTAINER_ENGINE must name a working engine; generation skipped"
  fi
  [[ -z "$(git status --porcelain)" ]] || die "Unexpected uncommitted files after rebase checks"
  git push -u origin "$branch"
  create_pr "$tag" "$branch" "$pin"
  ((${#failures[@]} == 0)) || die "Checks failed; draft PR opened for manual fixes"
  log "Auto-rebase complete for ${tag}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
