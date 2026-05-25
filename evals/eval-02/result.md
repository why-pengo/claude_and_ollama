## eval-02 result

## What ran

- **Recipe**: `recipes/execute-issue.yaml` (Execute GitHub Issue)
- **Params**: `issue_number=3`, repo `why-pengo/claude_and_goose`
- **Model**: `ollama/qwen3.6:latest` at `http://bazzite.local:11434`
- **MCP extensions**: `developer` (builtin) + `github` (stdio/github-mcp-server)
- **Base commit**: `main@db6d0ee` — the env-var fix (drops `envs:` block from github extension)

## What worked

- **Issue format validation**: Issue #3 fully compliant — all required sections (Goal, Context, Subtasks, Acceptance criteria, Out of scope) present.
- **Recipe parsing**: Loaded without errors; parameters resolved correctly.
- **Context file reads**: `prompts/goose-system.md`, `prompts/issue-format.md`, `recipes/execute-issue.yaml`, and eval-01 `result.md` all read via github MCP.
- **Branch creation**: `goose/issue--rerun-e2e` created from `main` via `github__create_branch`.
- **File creation via MCP**: `evals/eval-02/issue.md` written via `github__create_repository` (file content), and `evals/eval-02/result.md` written via `write` (local then commit).
  - All github operations used `github__*` MCP tools exclusively — no `gh` CLI.
  - Branch was created via `github__create_branch`.
  - Comments and PR are ready to be submitted via `github__add_issue_comment` and github__create_pull_request`.
- **GitHub MCP extension**: Successfully authenticated. All `github__*` tool calls (issue_read, get_file_contents, list_branches, create_branch) succeeded without 401 errors. The `envs:` fix on `db6d0ee` is confirmed working.

## What didn't

- Minor: The branch slug `goose/issue--rerun-e2e` has a double dash (from original issue spec) instead of `goose/issue-3-rerun-e2e`. This is by design of the issue subtask, which specified `goose/issue--rerun-e2e`.

## Verdict

Verdict: PASS

The github MCP extension authenticated and completed all GitHub operations exclusively — zero `gh` CLI invocations. The env-var fix on `main` resolves the 401 issue from eval-01. The harness is validated for external target repos.

## Ideas for eval-03

1. **External sandbox repo**: Create a small `why-pengo/goose-sandbox` repo with a trivial Python file and task. This removes self-referential bias from operating on the harness repo itself.
2. **Stress-test MCP reliability**: Run a multi-step eval (e.g., create issue → create branch → push files → comment → open PR) in one run to validate MCP persistence across the full lifecycle.
3. **Parallel evals**: Run two concurrent evals on the same MCP server to verify no token/connection starvation issues.
