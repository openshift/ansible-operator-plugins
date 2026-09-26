#!/usr/bin/env bash
#
# Periodic / CI entrypoint for rebasing openshift/ansible-operator-plugins onto
# a newer upstream ansible-operator-plugins release tag.
#
# Uses ./openshift/hack/rebase_upstream.sh for the merge. Opens a PR; does not
# auto-merge.
#
# Environment:
#   OVERRIDE_TAG           Optional. Override tag discovery; rebase this specific tag.
#   REBASE_BRANCH          Downstream branch to rebase onto (default: main).
#   UPSTREAM_REMOTE        Remote name for upstream repo (default: upstream).
#   UPSTREAM_URL           URL for the upstream remote (default: https://github.com/operator-framework/ansible-operator-plugins.git).
#   ORIGIN_REMOTE          Remote name to push PR branch (default: origin).
#   ORIGIN_URL             URL for the origin remote (default: https://github.com/${DEST_ORG_REPO}.git).
#   DEST_ORG_REPO          GitHub org/repo for PRs (default: openshift/ansible-operator-plugins).
#   GITHUB_TOKEN           Token for push + gh pr create (minted by the periodic job).
#   CONTAINER_ENGINE       Optional. Override the container engine used for generation.
#   DRY_RUN                If set to 1, only report what would happen (no merge/push/PR).
#   FORCE_REMOTE_URLS      If set to 1, allow rewriting an existing remote whose
#                          org/repo differs from the expected value (e.g. a developer fork).
#                          Default 0 — the script aborts instead to protect local config.
#   ALLOW_BRANCH_DELETE    If set to 1, allow deleting stale local rebase branches.
#                          Automatically enabled in CI (OPENSHIFT_CI / CI / JOB_NAME).
#   GIT_AUTHOR_NAME        Git identity for commits (default: openshift-app-platform-shift-bot).
#   GIT_AUTHOR_EMAIL       Git identity email (default: 267347085+openshift-app-platform-shift-bot@users.noreply.github.com).
#
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

REBASE_BRANCH=${REBASE_BRANCH:-main}
UPSTREAM_REMOTE=${UPSTREAM_REMOTE:-upstream}
ORIGIN_REMOTE=${ORIGIN_REMOTE:-origin}
DEST_ORG_REPO=${DEST_ORG_REPO:-openshift/ansible-operator-plugins}
UPSTREAM_URL=${UPSTREAM_URL:-https://github.com/operator-framework/ansible-operator-plugins.git}
ORIGIN_URL=${ORIGIN_URL:-https://github.com/${DEST_ORG_REPO}.git}
DRY_RUN=${DRY_RUN:-0}
FORCE_REMOTE_URLS=${FORCE_REMOTE_URLS:-0}
GIT_AUTHOR_NAME=${GIT_AUTHOR_NAME:-openshift-app-platform-shift-bot}
GIT_AUTHOR_EMAIL=${GIT_AUTHOR_EMAIL:-267347085+openshift-app-platform-shift-bot@users.noreply.github.com}

log() { printf '==> %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- Cleanup (credential file only) ---
_cred_file=""
_cleanup() {
  [[ -n "$_cred_file" ]] && rm -f "$_cred_file"
  git config --unset credential.helper 2>/dev/null || true
}
trap _cleanup EXIT

# True when running inside Prow / CI (checked env vars).
is_ci_context() {
  [[ -n "${OPENSHIFT_CI:-}" || -n "${CI:-}" || -n "${JOB_NAME:-}" ]]
}

# Delete a leftover local rebase branch, but only in CI or with opt-in.
cleanup_stale_branch() {
  local branch=$1
  git show-ref --verify --quiet "refs/heads/${branch}" || return 0
  if is_ci_context || [[ "${ALLOW_BRANCH_DELETE:-0}" == "1" ]]; then
    log "Deleting stale local branch ${branch}"
    git branch -D "$branch"
    return 0
  fi
  die "Local branch ${branch} already exists. Delete it manually or set ALLOW_BRANCH_DELETE=1."
}

# Return 0 if $1 is a strictly newer semver than $2 (release tags only).
version_gt() {
  local a=${1#v} b=${2#v}
  [[ "$(printf '%s\n%s\n' "$a" "$b" | sort -V | tail -n1)" == "$a" && "$a" != "$b" ]]
}

# Extract a safe "org/repo" identifier from supported GitHub URL forms.
# Never emit the original URL: it may contain credentials or point at an
# internal host.
_github_org_repo() {
  local url=$1
  local repo
  case "$url" in
    https://github.com/*)
      repo=${url#https://github.com/}
      ;;
    https://*@github.com/*)
      local userinfo=${url#https://}
      userinfo=${userinfo%%@github.com/*}
      [[ "$userinfo" != */* && "$userinfo" != *\?* && "$userinfo" != *#* && "$userinfo" != *@* ]] || return 1
      repo=${url#https://*@github.com/}
      ;;
    ssh://git@github.com/*)
      repo=${url#ssh://git@github.com/}
      ;;
    git@github.com:*)
      repo=${url#git@github.com:}
      ;;
    *)
      return 1
      ;;
  esac

  repo=${repo%.git}
  repo=${repo%/}
  [[ "$repo" =~ ^[[:alnum:]._-]+/[[:alnum:]._-]+$ ]] || return 1
  printf '%s\n' "$repo"
}

# Add or update a git remote; protects all remotes from silent org/repo overwrites.
ensure_remote() {
  local name=$1 url=$2
  if git remote get-url "$name" >/dev/null 2>&1; then
    local current
    current=$(git remote get-url "$name")
    if [[ "$current" != "$url" ]]; then
      local cur_repo exp_repo
      cur_repo=$(_github_org_repo "$current") \
        || die "Remote ${name} must use a supported github.com URL"
      exp_repo=$(_github_org_repo "$url") \
        || die "Configured URL for remote ${name} must use a supported github.com URL"
      if [[ "$cur_repo" == "$exp_repo" ]]; then
        log "Remote ${name} org/repo matches (${cur_repo}); keeping existing URL"
        return 0
      fi
      if [[ "$FORCE_REMOTE_URLS" != "1" ]]; then
        die "Remote ${name} points at ${cur_repo} but expected ${exp_repo}. Set FORCE_REMOTE_URLS=1 to overwrite, or set the matching URL env var to match your config."
      fi
      log "Rewriting remote ${name} to ${exp_repo}"
      git remote set-url "$name" "$url"
    fi
  else
    git remote add "$name" "$url"
  fi
}

# Die if gh CLI is not on PATH (CI image must provide it).
ensure_gh() {
  command -v gh >/dev/null 2>&1 || die "gh CLI is required but not found in PATH"
}

# Set git user.name and user.email for the bot's commits.
configure_git_identity() {
  git config user.name "$GIT_AUTHOR_NAME"
  git config user.email "$GIT_AUTHOR_EMAIL"
}

# Write GITHUB_TOKEN to a temp file and configure git credential.helper.
setup_credential_helper() {
  [[ -n "${GITHUB_TOKEN:-}" ]] || return 0
  _cred_file=$(mktemp)
  chmod 600 "$_cred_file"
  printf 'https://x-access-token:%s@github.com\n' "$GITHUB_TOKEN" >"$_cred_file"
  git config credential.helper "store --file=${_cred_file}"
}

# Read the current upstream version pin from UPSTREAM-VERSION.
current_pin() {
  local pin
  pin=$(tr -d '[:space:]' <UPSTREAM-VERSION)
  [[ -n "$pin" ]] || die "UPSTREAM-VERSION is empty"
  printf '%s\n' "$pin"
}

# Query upstream for the newest vMAJOR.MINOR.PATCH tag beyond the pin.
newest_upstream_tag() {
  local pin=$1 tag newest=""
  while IFS=$'\t' read -r _ ref; do
    tag=${ref#refs/tags/}
    [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || continue
    if version_gt "$tag" "$pin"; then
      if [[ -z "$newest" ]] || version_gt "$tag" "$newest"; then
        newest=$tag
      fi
    fi
  done < <(git ls-remote --tags "$UPSTREAM_URL" 'v*' 2>/dev/null)
  printf '%s\n' "$newest"
}

# Return 0 if an open PR already targets the rebase branch for this tag.
open_pr_exists() {
  local tag=$1
  command -v gh >/dev/null 2>&1 || return 1
  [[ -n "${GITHUB_TOKEN:-}" ]] || return 1
  local branch="${tag}-rebase-${REBASE_BRANCH}"
  local count
  count=$(gh pr list --repo "$DEST_ORG_REPO" --state open --head "$branch" \
    --json headRefName --jq 'length') || die "gh pr list failed for branch ${branch}"
  [[ "$count" -gt 0 ]]
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
  local current=$1 major=${1%%.*} minor=${1#*.} i
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

_builder_ok=1
_builder_error=""

# Bump golang builder pins in .ci-operator.yaml and openshift/Dockerfile if needed.
update_golang_builder() {
  local new_go current_go current_ocp
  new_go=$(awk '/^go /{split($2, a, "."); print a[1]"."a[2]}' go.mod)
  if [[ -z "$new_go" ]]; then
    _builder_ok=0
    _builder_error="Could not parse the Go version from go.mod"
    log "WARNING: ${_builder_error}"
    return 0
  fi

  current_go=$(sed -n 's/.*golang-\([0-9]*\.[0-9]*\).*/\1/p' .ci-operator.yaml | head -1)
  current_ocp=$(sed -n 's/.*openshift-\([0-9]*\.[0-9]*\).*/\1/p' .ci-operator.yaml | head -1)
  if [[ -z "$current_go" || -z "$current_ocp" ]]; then
    _builder_ok=0
    _builder_error="Could not parse the builder tag from .ci-operator.yaml"
    log "WARNING: ${_builder_error}"
    return 0
  fi

  if [[ "$new_go" == "$current_go" ]]; then
    if [[ ! -f openshift/Dockerfile ]] \
        || ! grep -Fq "golang-${current_go}-openshift-${current_ocp}" openshift/Dockerfile; then
      _builder_ok=0
      _builder_error="openshift/Dockerfile does not match the configured Go ${current_go} builder"
      log "WARNING: ${_builder_error}"
      return 0
    fi
    log "Golang version unchanged (${current_go}); no builder update needed"
    return 0
  fi

  local target_ocp
  if target_ocp=$(_resolve_builder_ocp "$new_go" "$current_ocp"); then
    log "Verified builder image: golang-${new_go}-openshift-${target_ocp}"
  else
    log "WARNING: no builder image found for golang-${new_go}; skipping builder bump"
    _builder_ok=0
    _builder_error="No verified builder image for Go ${new_go}; update .ci-operator.yaml and openshift/Dockerfile"
    return 0
  fi

  local old_ci_suffix="release-golang-${current_go}-openshift-${current_ocp}"
  local new_ci_suffix="release-golang-${new_go}-openshift-${target_ocp}"
  local old_builder_suffix="golang-${current_go}-openshift-${current_ocp}"
  local new_builder_suffix="golang-${new_go}-openshift-${target_ocp}"
  if [[ ! -f openshift/Dockerfile ]] \
      || ! grep -Fq "$old_ci_suffix" .ci-operator.yaml \
      || ! grep -Fq "$old_builder_suffix" openshift/Dockerfile; then
    _builder_ok=0
    _builder_error="Builder pins in .ci-operator.yaml and openshift/Dockerfile do not match"
    log "WARNING: ${_builder_error}"
    return 0
  fi
  log "Updating golang builder: ${old_builder_suffix} -> ${new_builder_suffix}"

  sed -i "s/${old_ci_suffix}/${new_ci_suffix}/" .ci-operator.yaml
  sed -i "s/${old_builder_suffix}/${new_builder_suffix}/" openshift/Dockerfile

  git add .ci-operator.yaml
  git add openshift/Dockerfile 2>/dev/null || true
  if ! git diff --staged --quiet; then
    git commit -m "UPSTREAM: <carry>: updates golang builder from ${old_builder_suffix} to ${new_builder_suffix}"
  fi
}

_collections_ok=1
_requirements_ok=1
_build_data_ok=1
_collections_error=""
_requirements_error=""
_build_data_error=""

# A binary on PATH is not enough: Docker may have no daemon in the CI pod.
select_container_engine() {
  local engine
  if [[ -n "${CONTAINER_ENGINE:-}" ]]; then
    command -v "$CONTAINER_ENGINE" >/dev/null 2>&1 \
      && "$CONTAINER_ENGINE" info >/dev/null 2>&1 || return 1
    printf '%s\n' "$CONTAINER_ENGINE"
    return 0
  fi
  for engine in docker podman; do
    if command -v "$engine" >/dev/null 2>&1 \
        && "$engine" info >/dev/null 2>&1; then
      printf '%s\n' "$engine"
      return 0
    fi
  done
  return 1
}

# Attempt to update ansible_collections; record pass/fail for PR body.
run_collections_gate() {
  local engine
  if ! engine=$(select_container_engine); then
    log "WARNING: no working container engine; skipping collections update"
    _collections_ok=0
    _collections_error="No working container engine"
    return 0
  fi
  log "Running make update-collections with ${engine}"
  if ! make -f openshift/Makefile update-collections CONTAINER_ENGINE="$engine"; then
    log "WARNING: make update-collections failed"
    _collections_ok=0
    _collections_error="make update-collections failed"
    return 0
  fi
  if [[ -n "$(git status --porcelain -- openshift/release/ansible/ansible_collections/)" ]]; then
    git add openshift/release/ansible/ansible_collections
    if ! git diff --cached --quiet -- openshift/release/ansible/ansible_collections/; then
      git commit -m "UPSTREAM: <carry>: Update ansible_collections directory" -- openshift/release/ansible/ansible_collections/
    fi
  else
    log "No changed files in ansible_collections directory"
  fi
}

# Attempt to generate downstream requirements files; record pass/fail for PR body.
run_requirements_gate() {
  local engine
  local -a outputs=(openshift/requirements.txt openshift/requirements-build.txt \
    openshift/requirements-build1.txt openshift/requirements-pre-build.txt openshift/Pipfile.lock)
  if ! engine=$(select_container_engine); then
    log "WARNING: no working container engine; skipping requirements generation"
    _requirements_ok=0
    _requirements_error="No working container engine"
    return 0
  fi
  log "Running make generate-requirements with ${engine}"
  if ! make -f openshift/Makefile generate-requirements CONTAINER_ENGINE="$engine"; then
    log "WARNING: make generate-requirements failed"
    _requirements_ok=0
    _requirements_error="make generate-requirements failed"
    return 0
  fi
  if [[ -n "$(git status --porcelain -- "${outputs[@]}")" ]]; then
    git add -- "${outputs[@]}"
    if ! git diff --cached --quiet -- "${outputs[@]}"; then
      git commit -m "UPSTREAM: <carry>: Update downstream requirements" -- "${outputs[@]}"
    fi
  else
    log "No changed files in openshift directory"
  fi
}

# Verify that the active downstream image config consumes each generated file.
check_build_data_requirements() {
  local config_file url
  config_file=$(mktemp)
  url=https://raw.githubusercontent.com/openshift-eng/ocp-build-data/openshift-5.1/images/openshift-enterprise-ansible-operator.yml
  if ! curl --fail --silent --show-error --location --retry 2 \
      --connect-timeout 10 --max-time 30 --output "$config_file" "$url"; then
    _build_data_ok=0
    _build_data_error="Could not read the openshift-5.1 image config in ocp-build-data"
  elif ! python3 - "$config_file" <<'PY'
import re
import sys

expected = {
    "requirements_files": {"requirements.txt"},
    "requirements_build_files": {
        "requirements-build.txt",
        "requirements-build1.txt",
        "requirements-pre-build.txt",
    },
}
found = {key: set() for key in expected}
active = None
indent = -1
with open(sys.argv[1], encoding="utf-8") as config:
    for line in config:
        section = re.match(r"^(\s*)(requirements_files|requirements_build_files):\s*$", line)
        if section:
            active = section.group(2)
            indent = len(section.group(1))
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if active is not None:
            if (len(line) - len(line.lstrip()) <= indent
                    and not line.lstrip().startswith("- ")):
                active = None
                continue
            item = re.match(r"^\s*-\s+([^\s#]+)", line)
            if item:
                found[active].add(item.group(1).strip("\"'"))

missing = {key: sorted(values - found[key]) for key, values in expected.items()}
for key, values in missing.items():
    if values:
        print(f"{key} missing: {', '.join(values)}", file=sys.stderr)
sys.exit(1 if any(missing.values()) else 0)
PY
  then
    _build_data_ok=0
    _build_data_error="Generated requirements filenames are missing from the openshift-5.1 image config"
  fi
  rm -f -- "$config_file"
  if [[ "$_build_data_ok" == 1 ]]; then
    log "ocp-build-data references all four generated requirements files"
  else
    log "WARNING: ${_build_data_error}"
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

# Open a PR (or draft if any gate failed) for the rebase branch.
create_pr() {
  local tag=$1 branch=$2 old_pin=$3
  local title body conflicts
  local any_failure=0

  [[ "$_builder_ok" == 1 && "$_collections_ok" == 1 \
    && "$_requirements_ok" == 1 && "$_build_data_ok" == 1 ]] || any_failure=1

  title="Rebase to ${tag}"
  conflicts=$(merge_conflicts "$tag")
  body=$(cat <<EOF
## Summary
Automated rebase of downstream Ansible Operator Plugins onto upstream \`${tag}\` via \`./openshift/hack/rebase_upstream.sh\`.

- Previous upstream pin: \`${old_pin}\`

## Automated checks
- Builder image: $([[ "$_builder_ok" == 1 ]] && echo "verified or unchanged" || echo "failed")
- Collections update: $([[ "$_collections_ok" == 1 ]] && echo "passed" || echo "failed or skipped")
- Requirements generation: $([[ "$_requirements_ok" == 1 ]] && echo "passed" || echo "failed or skipped")
- ocp-build-data requirements references: $(case "$_build_data_ok" in 1) echo passed;; 2) echo skipped;; *) echo failed;; esac)
EOF
)
  if [[ "$any_failure" == 1 ]]; then
    body+=$'\n\n## Follow-up required'
    [[ "$_builder_ok" == 1 ]] || body+=$'\n'"- [ ] Builder: ${_builder_error}"
    [[ "$_collections_ok" == 1 ]] || body+=$'\n'"- [ ] Collections: ${_collections_error}; run \`make -f openshift/Makefile update-collections\` and commit the result."
    [[ "$_requirements_ok" == 1 ]] || body+=$'\n'"- [ ] Requirements: ${_requirements_error}; run \`make -f openshift/Makefile generate-requirements\` and commit the result."
    [[ "$_build_data_ok" != 0 ]] || body+=$'\n'"- [ ] Image build config: ${_build_data_error}."
  fi
  if [[ -n "$conflicts" ]]; then
    body+=$'\n\n## Conflicts resolved to upstream\n```text\n'"${conflicts}"$'\n```'
  fi
  body+=$'\n\n## Human review\n- Review upstream changes and add any needed `UPSTREAM: <carry>:` commits.\n- Request an ART test build to verify Python build dependencies.'
  if [[ "$any_failure" == "1" ]]; then
    gh pr create --repo "$DEST_ORG_REPO" --base "$REBASE_BRANCH" --head "$branch" \
      --title "WIP: ${title}" --body "$body" --draft \
      || die "Failed to create draft PR for ${branch}"
  else
    gh pr create --repo "$DEST_ORG_REPO" --base "$REBASE_BRANCH" --head "$branch" \
      --title "$title" --body "$body" \
      || die "Failed to create PR for ${branch}"
  fi
}

# Orchestrate: discover tag, merge, gate, push, PR.
main() {
  local pin tag branch

  _github_org_repo "$UPSTREAM_URL" >/dev/null \
    || die "UPSTREAM_URL must use a supported github.com URL"
  _github_org_repo "$ORIGIN_URL" >/dev/null \
    || die "ORIGIN_URL must use a supported github.com URL"

  log "Fetching upstream tags"
  git fetch -t "$UPSTREAM_URL" 2>/dev/null || die "Failed to fetch upstream tags"

  pin=$(current_pin)
  if [[ -n "${OVERRIDE_TAG:-}" ]]; then
    tag=$OVERRIDE_TAG
    log "OVERRIDE_TAG set: ${tag}"
  else
    tag=$(newest_upstream_tag "$pin")
  fi

  if [[ -z "$tag" ]]; then
    log "No newer upstream release tag than ${pin}; nothing to do"
    exit 0
  fi

  if ! version_gt "$tag" "$pin" && [[ -z "${OVERRIDE_TAG:-}" ]]; then
    log "Selected tag ${tag} is not newer than pin ${pin}; nothing to do"
    exit 0
  fi

  branch="${tag}-rebase-${REBASE_BRANCH}"
  log "Candidate rebase: ${pin} -> ${tag} (branch ${branch})"

  if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY_RUN=1: would run ./openshift/hack/rebase_upstream.sh ${tag} ${REBASE_BRANCH} ${UPSTREAM_REMOTE}"
    exit 0
  fi

  if [[ -n "$(git status --porcelain)" ]]; then
    die "Working tree must be clean (including untracked files) before mutating"
  fi

  ensure_remote "$UPSTREAM_REMOTE" "$UPSTREAM_URL"
  ensure_remote "$ORIGIN_REMOTE" "$ORIGIN_URL"

  if ! git fetch "$ORIGIN_REMOTE" "$REBASE_BRANCH" 2>/dev/null \
    && ! git fetch "$ORIGIN_REMOTE" 2>/dev/null; then
    die "Failed to fetch ${ORIGIN_REMOTE}/${REBASE_BRANCH}"
  fi

  [[ -n "${GITHUB_TOKEN:-}" ]] || log "WARNING: no GITHUB_TOKEN; push/PR may fail"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    ensure_gh
    export GH_TOKEN="$GITHUB_TOKEN"
    if open_pr_exists "$tag"; then
      log "Open PR for ${tag} already exists; skipping"
      exit 0
    fi
  fi

  configure_git_identity
  setup_credential_helper

  if ! is_ci_context && git show-ref --verify --quiet "refs/heads/${REBASE_BRANCH}"; then
    if ! git merge-base --is-ancestor "$REBASE_BRANCH" "$ORIGIN_REMOTE/$REBASE_BRANCH"; then
      die "Local branch ${REBASE_BRANCH} contains commits not in ${ORIGIN_REMOTE}/${REBASE_BRANCH}; refusing to discard them outside CI"
    fi
  fi

  git checkout -B "$REBASE_BRANCH" "$ORIGIN_REMOTE/$REBASE_BRANCH"
  git branch --set-upstream-to="$ORIGIN_REMOTE/$REBASE_BRANCH" "$REBASE_BRANCH"

  if is_ci_context; then
    export ALLOW_BRANCH_DELETE=1
  fi

  cleanup_stale_branch "$branch"

  trap 'log "FAILED (rc=$?) on branch $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"' ERR

  log "Running rebase_upstream.sh ${tag} ${REBASE_BRANCH} ${UPSTREAM_REMOTE}"
  SKIP_GENERATION=1 ORIGIN_REMOTE="$ORIGIN_REMOTE" \
    ./openshift/hack/rebase_upstream.sh "$tag" "$REBASE_BRANCH" "$UPSTREAM_REMOTE"

  update_golang_builder

  run_collections_gate
  run_requirements_gate
  if [[ "$_requirements_ok" == 1 ]]; then
    check_build_data_requirements
  else
    _build_data_ok=2
    _build_data_error="Skipped because requirements generation did not succeed"
  fi

  [[ -n "${GITHUB_TOKEN:-}" ]] || die "GITHUB_TOKEN required to push and open PR"

  log "Pushing ${branch}"
  git push --force -u "$ORIGIN_REMOTE" "$branch" 2>/dev/null \
    || die "Failed to push ${branch}"

  log "Opening pull request"
  create_pr "$tag" "$branch" "$pin"

  if [[ "$_builder_ok" != 1 || "$_collections_ok" != 1 \
      || "$_requirements_ok" != 1 || "$_build_data_ok" != 1 ]]; then
    die "One or more gates failed; draft PR opened with the specific failures"
  fi
  log "Auto-rebase complete for ${tag}"
}

main "$@"
