# feat: add scripts/post-run-check.sh (macOS-compatible) to verify goose-run side effects

## Goal

Re-attempt of #28. Same end goal — a single-file bash helper that verifies a Goose run produced real artifacts (tool calls in session log, branch on remote, PR closing the issue). The previous attempt (PR #29, closed) was correct in structure but used two GNU-only shell idioms that silent-failed on the macOS dev host. This issue respecs the task with explicit portable constructs.

## Context

- Previous attempt: PR #29 (closed). The script as written exited 1 with zero output on macOS because `find -printf` and `grep -oP` both fail at runtime; `set -euo pipefail` + `2>/dev/null` swallowed the error.
- Motivating failures: see `evals/eval-05/result.md` (merged) — three of five devstral runs produced session logs that looked plausible but had zero real artifacts on GitHub. This script is the canonical answer to "did the run actually do anything?"
- Companion script style: model after `scripts/check-ollama.sh` — `set -euo pipefail`, header comment block, minimal external deps (just `gh` and standard POSIX).
- The script must run on **macOS host** (BSD coreutils), not just the Linux container. Use only constructs that work on both.

## Subtasks

- [ ] Create `scripts/post-run-check.sh` with:
  - `#!/usr/bin/env bash` shebang
  - `set -euo pipefail`
  - 5–8 line header comment block: what it does, usage examples, exit codes
  - Argument parsing:
    - Required: `ISSUE_NUMBER` (positional arg 1)
    - Optional: `SESSION_LOG_PATH` (positional arg 2)
  - **For default-log discovery (when arg 2 is omitted)**, use this exact idiom (no `find -printf`, no `stat -f`):
    ```bash
    SESSION_LOG_PATH=$(find evals -name 'goose-session*.log' -type f -print 2>/dev/null \
      | xargs ls -t 2>/dev/null | head -1)
    ```
  - **For owner/repo detection**, use `gh repo view --json --jq` directly (no `grep -oP`, no `grep -P` at all):
    ```bash
    read -r GH_OWNER GH_REPO < <(gh repo view --json owner,name \
      --jq '"\(.owner.login) \(.name)"')
    ```
  - Three checks, each printing one line with `PASS` or `FAIL`:
    1. **Tool calls present** — count lines in the session log matching `^[[:space:]]*▸ `. PASS if count >= 1.
    2. **Branch on remote** — `gh api repos/{owner}/{repo}/branches --jq` for any branch matching `goose/issue-N-*`.
    3. **PR closing the issue** — `gh pr list --state all --search "closes #N in:body" --json number --jq '.[0].number'`.
  - Final line: `RESULT: PASS` if check 1 passes AND (check 2 OR check 3) passes; `RESULT: FAIL` otherwise.
  - Exit code: 0 on PASS, 1 on FAIL.
- [ ] Push the new file via `push_files` MCP (single-entry call).
- [ ] Open a PR with `Closes #<this-issue>` in the body. PR body must include:
  - `## Summary` — 2–3 bullets on what the script does
  - `## Verification` — be honest: if you couldn't actually execute the script in your environment, say so plainly ("did not execute; static-checked only"). Do not invent reasons (the previous attempt's PR body claimed "gh auth not configured" when in fact the script crashed earlier).
  - `## Follow-ups` — single line: `chmod +x scripts/post-run-check.sh post-merge (MCP push_files cannot set mode)`

## Acceptance criteria

- File `scripts/post-run-check.sh` exists on the goose branch.
- `grep -nE 'find .* -printf|grep .*-P' scripts/post-run-check.sh` returns nothing (no GNU-only flags).
- `grep -n 'set -euo pipefail' scripts/post-run-check.sh` returns line 1–20 (set early in the script).
- `grep -n 'gh repo view --json' scripts/post-run-check.sh` returns at least one line.
- `grep -n '^\[\[:space:\]\]\*▸ ' scripts/post-run-check.sh` returns at least one line (the tool-call marker regex).
- PR body includes the `## Follow-ups` chmod line.

## Out of scope

- Modifying `scripts/check-ollama.sh` or any other existing file.
- Updating `README.md` to reference the new script.
- Adding the script to any CI workflow.
- Inventing a `permissions.sh` or chmod helper.
- Adding extra bash flags beyond the two positional args.
