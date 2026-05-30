#!/usr/bin/env bash
# List installed Ollama models via the /api/tags endpoint.
#
# Usage:
#   ./scripts/check-ollama.sh              # uses http://bazzite.local:11434
#   OLLAMA_HOST=http://other.local:11434 ./scripts/check-ollama.sh
set -euo pipefail

HOST="${OLLAMA_HOST:-http://bazzite.local:11434}"
HOST="${HOST%/}"
URL="${HOST}/api/tags"

if ! body=$(curl -s -f --connect-timeout 5 "$URL"); then
  echo "Error: failed to reach Ollama host at ${URL}" >&2
  exit 1
fi

echo "$body" | jq -r '
  .models[] | [
    .name,
    ((.size / 1e9) | round),
    .details.parameter_size,
    .details.quantization_level
  ] | join("\t")
'
