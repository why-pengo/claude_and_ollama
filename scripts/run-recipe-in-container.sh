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

echo "Image:          $IMAGE"
echo "Repo mount:     $repo_root -> /work"
echo "Ollama:         $OLLAMA_HOSTNAME ($ollama_ip):$OLLAMA_PORT"
echo "Recipe:         $recipe"
echo "Params:         ${params[*]:-(none)}"
echo

exec docker run --rm -i \
  -v "$repo_root:/work" \
  -e GITHUB_PERSONAL_ACCESS_TOKEN \
  -e "OLLAMA_HOST=http://${ollama_ip}:${OLLAMA_PORT}" \
  -e "GOOSE_ADDITIONAL_CONFIG_FILES=/work/goose.yaml" \
  "$IMAGE" \
  goose run --recipe "/work/$recipe" "${params[@]}"
