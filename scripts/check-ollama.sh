#!/usr/bin/env bash
# check-ollama.sh — list installed Ollama models via /api/tags.
#
# Usage:
#   ./scripts/check-ollama.sh              # uses http://bazzite.local:11434
#   OLLAMA_HOST=http://other.local:11434 ./scripts/check-ollama.sh
set -euo pipefail

HOST="${OLLAMA_HOST:-http://bazzite.local:11434}"
URL="${HOST}/api/tags"

body=$(curl -s -f --connect-timeout 5 "$URL" 2>&1) || {
  echo "error: could not connect to Ollama host (${URL})" >&2
  exit 1
}

printf '%-30s %8s  %s  %s\n' NAME SIZE_GB PARAMETER_SIZE QUANTIZATION_LEVEL
echo "$body" | jq -r '
  .models[] | [
    .name,
    ((.size / 1e9) | round | tostring),
    .details.parameter_size,
    .details.quantization_level
  ] | join("\t")
'