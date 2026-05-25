## Goal
Re-run the same end-to-end workflow as eval-01, this time on top of the env-var fix landed in `main@db6d0ee`. Success means the github MCP extension is used **exclusively** for every GitHub operation (issue read, branch push, issue comment, PR open) — zero falls back to `gh` CLI via the shell extension. If we see that cleanly, the harness is validated and we can move to eval-03 against an external target repo.

## Context
- Direct follow-up to eval-01 (#1, PR #2). Treat eval-01's `result.md` as the canonical record of what eval-01 found.
- Fix being validated: commit `db6d0ee` on `main` — drops the `envs:` block from the github extension so the MCP stdio subprocess inherits `GITHUB_PERSONAL_ACCESS_TOKEN` from the parent process.
- Issue format spec: `prompts/issue-format.md`
- Goose system prompt: `prompts/goose-system.md`
- Recipe: `recipes/execute-issue.yaml` (unchanged since eval-01)
- Model + host: same as eval-01 — `qwen3.6:latest` at `http://bazzite.local:11434`
- Still self-referential. External target repos are eval-03's job.

## Prerequisites (human, before invoking Goose)
- Be on `main` at commit `db6d0ee` or later. Confirm `goose.yaml` has **no `envs:` block** under the `github` extension.
- ```
  export GOOSE_ADDITIONAL_CONFIG_FILES="$(pwd)/goose.yaml"
  export GITHUB_PERSONAL_ACCESS_TOKEN="$(gh auth token)"
  ```
- Optional sanity check: `goose info --check` — should show Provider/Model/Auth/Connection all `ok`.
- Invoke:
  ```
  ./scripts/new-eval.sh 02
  goose run --recipe recipes/execute-issue.yaml \
    --params issue_number=<this issue's number> \
    | tee evals/eval-02/goose-session.log
  ```

## Subtasks
- [ ] Read this issue end to end, plus the three files referenced in Context
- [ ] Create branch `goose/issue-<N>-rerun-e2e` from `main`
- [ ] Copy this issue's body **byte-for-byte verbatim** into `evals/eval-02/issue.md` — no reformatting, no added headers
- [ ] Drive every GitHub operation (issue read, branch push, comment, PR open) through the **github MCP extension**. If a github MCP call fails, comment on this issue with the error and STOP. Do NOT silently fall back to `gh` CLI via the shell extension.
- [ ] Write `evals/eval-02/result.md` containing: what ran, what worked, what didn't, a `Verdict: PASS | FAIL | PARTIAL` line, and 3 ideas for eval-03
- [ ] Commit the eval-02 artifacts with a conventional-commit message
- [ ] Comment on this issue with status (✅ / ⚠️ / ❌) and a link to the PR
- [ ] Open a PR titled `eval: capture eval-02 (verify MCP auth fix)` whose body includes `Closes #<this issue>`

## Acceptance criteria
- Branch `goose/issue-<N>-rerun-e2e` exists at `origin` with at least one commit
- `evals/eval-02/issue.md`, `result.md`, and `goose-session.log` all exist
- `result.md` contains a line beginning with `Verdict:` followed by `PASS`, `FAIL`, or `PARTIAL`
- **No `gh ` invocations in `evals/eval-02/goose-session.log`** — verifiable with `grep -c '^\s*command:.*\bgh\b' evals/eval-02/goose-session.log` returning 0
- **Every GitHub API call in the log is a `github__*` MCP tool call** (no shell-extension fallback for GitHub work)
- A PR exists with `Closes #<this issue>` in its body
- A comment from Goose appears on this issue with status + PR link

## Out of scope
- Trying any model other than `qwen3.6:latest`
- Moving to an external target repo (that's eval-03, requires a sandbox repo to exist first)
- Tightening the recipe's verbatim-copy step (separate harness work — see eval-01 `result.md` "Next time" item 3)
- Changing harness files outside `evals/eval-02/` during the run

