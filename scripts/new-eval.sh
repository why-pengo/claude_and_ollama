#!/usr/bin/env bash
# Scaffold a new evals/eval-NN/ directory with empty placeholders.
#
# Usage: ./scripts/new-eval.sh <N>
#   e.g. ./scripts/new-eval.sh 02
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <eval-number>" >&2
  echo "Example: $0 02" >&2
  exit 1
fi

n="$1"
dir="evals/eval-${n}"

if [[ -e "$dir" ]]; then
  echo "Refusing to overwrite existing $dir" >&2
  exit 1
fi

mkdir -p "$dir"
: > "$dir/session.log"

cat > "$dir/issue.md" <<'EOF'
<!-- Paste the GitHub issue body here verbatim. -->
EOF

cat > "$dir/result.md" <<EOF
# eval-${n} result

## What ran
<!-- recipe + params + model -->

## What worked

## What didn't

## Verdict
Verdict: PASS | FAIL | PARTIAL

## Next time
-
-
-
EOF

echo "Scaffolded $dir"
