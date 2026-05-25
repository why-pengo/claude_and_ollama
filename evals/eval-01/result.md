# eval-01 result

## What ran

- **Recipe**: `recipes/execute-issue.yaml` (Execute GitHub Issue)
- **Params**: `issue_number=1`, repo `why-pengo/claude_and_goose`
- **Model**: `ollama/qwen3.6:latest` at `http://bazzite.local:11434`
- **Session log**: `evals/eval-01/goose-session.log` (953 lines)
- **MCP extensions**: `developer` (builtin) + `github` (stdio/github-mcp-server 1.0.5)

Goose loaded the recipe, read issue #1's body, validated its format against `prompts/issue-format.md`, and worked through every subtask in order.

## What worked

- **Issue format validation**: Goose correctly identified issue #1 as fully compliant — all required sections (Goal, Context, Subtasks, Acceptance criteria, Out of scope) present. No missing pieces to flag.
- **Recipe parsing**: `recipes/execute-issue.yaml` loaded without errors; parameters resolved correctly. `GOOSE_ADDITIONAL_CONFIG_FILES` made `goose.yaml` visible to the run.
- **Context file reads**: `prompts/goose-system.md`, `prompts/issue-format.md`, and the recipe were all read before execution.
- **Branch creation + push**: `goose/issue-1-validate-e2e` created from `origin/main` and pushed (`dcd2079`).
- **End-to-end via fallback**: When the github MCP failed, Goose used the `developer` (shell) extension to drive `gh` CLI and `git` directly. It completed every remaining subtask: copied the issue body, wrote `result.md`, committed, pushed, commented on issue #1, and opened PR #2 with `Closes #1`. The fallback wasn't scripted by the recipe — Goose chose it.

## What didn't

**Critical: GitHub MCP extension returned `401 Bad credentials` on every API call.** Examples from the log:

- `github__issue_read` → 401
- `github__get_file_contents` → 401
- `github__get_me` → 401

This prevented the github MCP from creating the branch, commenting on the issue, or opening the PR. Goose worked around it by switching to the shell extension + `gh` CLI (which authenticates via the macOS keyring).

**Verified root cause (during eval-01 wrap-up):** Goose 1.35.0's extension `envs:` map takes **literal** values — no shell-style `${VAR}` expansion. The eval-01 config had:

```yaml
envs:
  GITHUB_PERSONAL_ACCESS_TOKEN: ${GITHUB_PERSONAL_ACCESS_TOKEN}
```

So `github-mcp-server` was launched with the literal string `"${GITHUB_PERSONAL_ACCESS_TOKEN}"` as its token, producing 401 on every call. Confirmed by re-running a minimal recipe (`/tmp/test-github-mcp.yaml`, calling only `get_me`) with the `envs:` block removed — `get_me` returned `why-pengo` cleanly. Fix committed on `main` as `db6d0ee`.

**Minor deviations from the issue spec:**

- `evals/eval-01/issue.md` is *almost* verbatim but Goose added a `# Title\n=====` header and dropped trailing whitespace — the subtask asked for "verbatim".
- The comment on issue #1 opens with `✅ done` then says `⚠️ partial` in the body — inconsistent emoji, but the verdict is unambiguous.
- The first commit Goose made (`dcd2079`) snapshotted the session log mid-run; the on-disk log grew another 132 lines before Goose finished. Captured in this PR by updating the file.

## Verdict

Verdict: PARTIAL

End-to-end completed only because Goose chose a fallback that wasn't in the recipe. The harness itself (recipe loading, format validation, subtask ordering, PR composition) worked as designed. The single bug — the `envs:` block in `goose.yaml` — is fixed on `main`.

## Next time (eval-02 targets)

1. **Confirm the fix in a fresh end-to-end run.** Pull the `db6d0ee` goose.yaml, file a new `goose-task` issue, and verify the github MCP path is now exclusive (no shell-extension fallback needed). Success criterion: zero `gh` CLI calls in the session log.
2. **Move to a non-self-referential target repo.** A small sandbox repo (e.g. `why-pengo/goose-sandbox` with one Python file and a trivial task) removes any chance that operating on the harness itself biased Goose's choices.
3. **Tighten the recipe's verbatim-copy step.** Either make it `cp` the issue body via shell (no LLM rewrite) or make the "verbatim" requirement non-optional in the prompt. The eval-01 deviation was small but indicates the model will lightly reformat unless explicitly stopped.
