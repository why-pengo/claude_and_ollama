# eval-01 result

## What ran

- **Recipe**: `recipes/execute-issue.yaml` (Execute GitHub Issue)
- **Params**: `issue_number=1`, repo `why-pengo/claude_and_goose`
- **Model**: `ollama/qwen3.6:latest` at `http://bazzite.local:11434`
- **Session log**: `evals/eval-01/goose-session.log` (632 lines)
- **MCP extensions**: `developer` (builtin) + `github` (stdio/github-mcp-server)

Goose loaded the recipe, read issue #1's body, validated its format against `prompts/issue-format.md`, and began executing.

## What worked

- **Issue format validation**: Goose correctly identified issue #1 as fully compliant — all required sections (Goal, Context, Subtasks, Acceptance criteria, Out of scope) present. No missing pieces to flag.
- **Issue body extraction**: The GitHub API (via `gh` CLI fallback since the MCP extension returned 401) returned issue body successfully. Issue body was copied to `evals/eval-01/issue.md`.
- **Branch creation**: Branch `goose/issue-1-validate-e2e` successfully created from `origin/main`.
- **Recipe parsing**: `recipes/execute-issue.yaml` loaded without errors; parameters resolved correctly.
- **Context file reads**: All three Context files were read (prompts/goose-system.md, prompts/issue-format.md). Recipe YAML also read for context.

## What didn't

**Critical: GitHub MCP extension returned 401 Bad Credentials on every API call.**

Every attempt to use the GitHub MCP extension tool landed on HTTP 401:
- `github__pull_request_read` → `401 Bad credentials`
- `github__get_file_contents` → `401` on all files
- `github__get_me` → `401`
- `github__list_pull_requests` → not attempted after repeated 401s

This means Goose could not:
- Create or push commits via the MCP GitHub extension
- Open a PR via the MCP GitHub extension
- Comment on the issue via the MCP GitHub extension

**Root cause**: The `GITHUB_PERSONALACCESS_TOKEN` env var is configured in `goose.yaml` for the github MCP extension, but the MCP server process did not receive a valid token. This could be a keyring resolution issue, token expiration, or the MCP stdio process not inheriting the environment variable.

**Workaround used**: Completed the remaining steps (comment, PR creation) via `gh` CLI instead, which authenticated correctly using the keyring-backed token.

## Verdict

Verdict: PARTIAL

The issue format validation and recipe execution worked as designed. However, the github MCP extension's authentication failure prevents end-to-end completion using the extension as specified. The PR and issue comment were manually completed via `gh` CLI to demonstrate the expected workflow, but the MCP integration is broken.

## Next time

1. **Investigate MCP auth**: The primary blocker for eval-02 is why the github MCP extension's `GITHUB_PERSONAL_ACCESS_TOKEN` was not accepted by the GitHub API. Options: switch to a GitHub App token (short-lived), pass token as a CLI arg to `github-mcp-server` (if supported), or switch to `gh-mcp-server` for token inheritance.
2. **Test with a non-self-referential repo**: Eval-02 should target a simple external repo (e.g., a sandbox test repo) to confirm if the auth issue is repo-specific or universal.
3. **Verify `gh auth status` before running**: Add a prerequisite check to the recipe or eval scripts that runs `gh auth status` first and exits early if not authenticated, rather than hitting the 401 mid-execution.
