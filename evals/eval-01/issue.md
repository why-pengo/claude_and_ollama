# Title
===== 
Eval #1 — Validate end-to-end Claude Code → Goose workflow

## Goal
Validate the end-to-end workflow on its very first execution: Claude Code authored this issue against `prompts/issue-format.md`; Goose (qwen3.6 on bazzite.local) should pick it up, execute the subtasks, comment with results, and open a PR. The verdict in `result.md` tells us whether the harness as drafted is usable, or which pieces need to change before we point it at a real target project.

## Context
- This repo was just scaffolded — first run of anything.
- Issue format spec: `prompts/issue-format.md`
- Goose system prompt: `prompts/goose-system.md`
- Recipe: `recipes/execute-issue.yaml`
- Ollama: `http://bazzite.local:11434`, model `qwen3.6:latest` (36B Q4_K_M)
- Goose docs: https://goose-docs.ai
- The recipe assumes `goose-task` labels exist; they were created at scaffold time.
- This eval is **self-referential**: Goose operates on the same repo the harness lives in. That's intentional shakedown — eval-02 will move to an external target.

## Prerequisites (human, before invoking Goose)
- Install Goose locally — it is NOT installed at scaffold time.
- Export `GITHUB_PERSONAL_ACCESS_TOKEN` for the github MCP extension.
- Confirm Ollama at `bazzite.local:11434` is reachable.
- Invoke Goose with:
  ```
  goose run --recipe recipes/execute-issue.yaml \
    --params issue_number=1 \
    | tee evals/eval-01/goose-session.log
  ```
  (The `tee` is what populates the session log — Goose itself doesn't need to write it.)

## Subtasks
- [ ] Read this issue end to end, plus the three files referenced in Context
- [ ] Create branch `goose/issue-1-validate-e2e` from `main`
- [ ] Copy this issue's body verbatim into `evals/eval-01/issue.md`
- [ ] Write `evals/eval-01/result.md` containing:
  - What ran (recipe + params + model)
  - What worked
  - What didn't
  - A verdict line of the form `Verdict: PASS` / `Verdict: FAIL` / `Verdict: PARTIAL`
  - 3 concrete ideas for eval-02
- [ ] Commit the eval-01 artifacts with a conventional-commit message
- [ ] Comment on this issue with status (✅ / ⚠️ / ❌) and a link to the PR
- [ ] Open a PR titled `eval: capture eval-01 (validate e2e workflow)` whose body includes `Closes #1`

## Acceptance criteria
- Branch `goose/issue-1-validate-e2e` exists with at least one commit
- `evals/eval-01/issue.md` matches this issue's body verbatim
- `evals/eval-01/result.md` contains a line beginning with `Verdict:` followed by `PASS`, `FAIL`, or `PARTIAL`
- `evals/eval-01/goose-session.log` is non-empty
- A PR exists in `why-pengo/claude_and_goose` whose body contains `Closes #1`
- A comment from Goose appears on this issue

## Out of scope
- Trying any model other than `qwen3.6:latest`
- Tuning the recipe, prompts, or `goose.yaml` based on what we observe — that's eval-02's job (capture findings under "Next time" in `result.md` instead)
- Wiring this repo against an external target project
- Changing harness files outside `evals/eval-01/` during this run

