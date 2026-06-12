#!/usr/bin/env bash
# Run a Goose recipe inside the claude-and-goose-runtime container.
#
# Usage:
#   ./scripts/run-recipe-in-container.sh \
#     --recipe recipes/execute-issue.yaml \
#     --params issue_number=4
#
# All --params flags are forwarded to `goose run`. Repeat as needed.
#
# Mounts the current repo (read-write) at /work. Resolves bazzite.local
# on the host and exports OLLAMA_HOST=http://<ip>:11434 into the
# container so the mDNS name doesn't need to work from inside Docker.

set -euo pipefail

IMAGE="${CLAUDE_GOOSE_IMAGE:-claude-and-goose-runtime}"
OLLAMA_HOSTNAME="${OLLAMA_HOSTNAME:-bazzite.local}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"

recipe=""
params=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --recipe)
      recipe="$2"; shift 2 ;;
    --params)
      params+=("--params" "$2"); shift 2 ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$recipe" ]]; then
  echo "Missing --recipe <path>" >&2
  exit 2
fi

# --recipe must be relative to the repo root; we prefix /work/ inside the
# container. An absolute path would yield /work//Users/... and fail with
# a confusing "file not found" deep inside Goose. Reject early.
if [[ "$recipe" = /* ]]; then
  echo "--recipe must be a path relative to the repo root, got: $recipe" >&2
  exit 2
fi

if [[ -z "${GITHUB_PERSONAL_ACCESS_TOKEN:-}" ]]; then
  echo "GITHUB_PERSONAL_ACCESS_TOKEN not set in env" >&2
  exit 2
fi

# Resolve Ollama host on the macOS host so the container doesn't need mDNS.
# dscacheutil is macOS's name-resolution shim; the awk pulls the first A record.
if ! ollama_ip="$(dscacheutil -q host -a name "$OLLAMA_HOSTNAME" \
    | awk '/^ip_address:/ {print $2; exit}')"; then
  echo "dscacheutil lookup of $OLLAMA_HOSTNAME failed" >&2
  exit 1
fi

if [[ -z "$ollama_ip" ]]; then
  echo "Could not resolve $OLLAMA_HOSTNAME (empty result)" >&2
  exit 1
fi

repo_root="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"

# Resolve the target repo's default branch and inject it as
# base_branch=<X> unless the caller already provided one. The recipe
# uses {{ base_branch }} for branch creation and PR targeting, so the
# default branch is now resolved server-side at invocation time rather
# than hard-coded to "main". Without this, cross-repo runs against
# repos that use `develop` as integration (Jon's standard
# feature/* → develop → main workflow) open PRs against `main`
# instead of `develop` and silently drift behind. See #40.
target_repo=""
base_branch_set=false
for v in "${params[@]}"; do
  case "$v" in
    repo=*)        target_repo="${v#repo=}" ;;
    base_branch=*) base_branch_set=true ;;
  esac
done

if ! $base_branch_set; then
  if [[ -z "$target_repo" ]]; then
    # Mirrors the recipe's `repo` default — self-runs against the harness.
    target_repo="why-pengo/claude_and_goose"
  fi
  if default_branch="$(gh api "repos/$target_repo" --jq '.default_branch' 2>/dev/null)" && [[ -n "$default_branch" ]]; then
    params+=("--params" "base_branch=$default_branch")
    resolved_base="$default_branch (resolved from $target_repo)"
  else
    params+=("--params" "base_branch=main")
    resolved_base="main (fallback — could not resolve from $target_repo)"
  fi
else
  resolved_base="(provided via --params)"
fi

# Forward GOOSE_MODEL and GOOSE_CONTEXT_LIMIT if set in parent env — lets
# callers override the goose.yaml defaults per-invocation for bake-off
# experiments without editing goose.yaml. The container's goose.yaml
# still provides defaults; these env vars win because Goose's env-var
# precedence beats config files. Critical when a model variant was loaded
# at a smaller context than goose.yaml advertises (e.g. 70B-class models
# with KV cache pressure can only fit 65K, not the qwen3.6 baseline 131K).
override_args=()
if [[ -n "${GOOSE_MODEL:-}" ]]; then
  override_args+=(-e "GOOSE_MODEL=$GOOSE_MODEL")
  model_line="$GOOSE_MODEL (overriding goose.yaml default)"
else
  model_line="(goose.yaml default — qwen3.6:latest)"
fi
if [[ -n "${GOOSE_CONTEXT_LIMIT:-}" ]]; then
  override_args+=(-e "GOOSE_CONTEXT_LIMIT=$GOOSE_CONTEXT_LIMIT")
  ctx_line="$GOOSE_CONTEXT_LIMIT (overriding goose.yaml default)"
else
  ctx_line="(goose.yaml default — 131072)"
fi

echo "Image:          $IMAGE"
echo "Repo mount:     $repo_root -> /work"
echo "Ollama:         $OLLAMA_HOSTNAME ($ollama_ip):$OLLAMA_PORT"
echo "Recipe:         $recipe"
echo "Base branch:    $resolved_base"
echo "Model:          $model_line"
echo "Context limit:  $ctx_line"
echo "Params:         ${params[*]:-(none)}"
echo

exec docker run --rm -i \
  -v "$repo_root:/work" \
  -e GITHUB_PERSONAL_ACCESS_TOKEN \
  -e "OLLAMA_HOST=http://${ollama_ip}:${OLLAMA_PORT}" \
  -e "GOOSE_ADDITIONAL_CONFIG_FILES=/work/goose.yaml" \
  ${override_args[@]+"${override_args[@]}"} \
  "$IMAGE" \
  goose run --recipe "/work/$recipe" "${params[@]}"
