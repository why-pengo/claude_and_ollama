#!/usr/bin/env bash
#
# post-run-check.sh — Verify a runner-driven eval produced real artifacts.
#
# Usage:
#   ./scripts/post-run-check.sh 32                    # default session log
#   ./scripts/post-run-check.sh 32 my-session.log      # custom session log
#
# Exit codes:
#   0 — PASS
#   1 — FAIL

set -euo pipefail

ISSUE_NUMBER="${1:?Usage: $0 ISSUE_NUMBER [SESSION_LOG_PATH]}"

# Default-log discovery (macOS/BSD-compatible). Matches both the runner-era
# session.log and the Goose-era goose-session.log for backward compatibility
# with the historical eval corpus.
if [ -z "${2:-}" ]; then
  SESSION_LOG_PATH=$(find evals \( -name 'session.log' -o -name 'goose-session*.log' \) -type f -print 2>/dev/null \
    | xargs ls -t 2>/dev/null | head -1 || true)
  if [ -z "${SESSION_LOG_PATH:-}" ] || [ ! -f "$SESSION_LOG_PATH" ]; then
    echo "No session log found under evals/ matching session.log or goose-session*.log" >&2
    exit 1
  fi
else
  SESSION_LOG_PATH="$2"
fi

# Owner/repo detection
read -r GH_OWNER GH_REPO <<EOF
$(gh repo view --json owner,name \
  --jq '"\(.owner.login) \(.name)"')
EOF

# --- Check 1: Tool calls present in session log ---
tool_call_count=$(grep -c '^[[:space:]]*▸ ' "$SESSION_LOG_PATH" || true)
if [ "$tool_call_count" -ge 1 ]; then
  echo "[CHECK 1] Tool calls: PASS ($tool_call_count found)"
  CHECK_1_PASS=true
else
  echo "[CHECK 1] Tool calls: FAIL (0 found)"
  CHECK_1_PASS=false
fi

# --- Check 2: Branch on remote ---
br_count=$(gh api "repos/${GH_OWNER}/${GH_REPO}/branches" --jq '.[].name' 2>/dev/null \
  | grep -cE "^(runner|goose)/issue-${ISSUE_NUMBER}-" || true)
if [ "$br_count" -ge 1 ]; then
  echo "[CHECK 2] Branch on remote: PASS ($br_count branches)"
  CHECK_2_PASS=true
else
  echo "[CHECK 2] Branch on remote: FAIL (none found)"
  CHECK_2_PASS=false
fi

# --- Check 3: PR closing the issue ---
pr_number=$(gh pr list --state all --search "closes #$ISSUE_NUMBER in:body" --json number --jq '.[0].number' 2>/dev/null || echo '')
if [ -n "$pr_number" ]; then
  echo "[CHECK 3] PR closing issue: PASS (PR #$pr_number)"
  CHECK_3_PASS=true
else
  echo "[CHECK 3] PR closing issue: FAIL (none found)"
  CHECK_3_PASS=false
fi

# --- Final result ---
if [ "$CHECK_1_PASS" = true ] && { [ "$CHECK_2_PASS" = true ] || [ "$CHECK_3_PASS" = true ]; }; then
  echo "RESULT: PASS"
  exit 0
else
  echo "RESULT: FAIL"
  exit 1
fi
