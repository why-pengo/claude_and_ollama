![Claude and Ollama](assets/cnl.png)
# claude_and_ollama

An evaluation harness for a two-agent code workflow:

- **Claude Code** is the planner. It reads context, decomposes work,
  and files structured GitHub Issues.
- **The runner** (`runner/run_recipe.py`, calling a local Ollama
  model on `bazzite.local`) is the executor. It reads one issue at a
  time, executes its subtasks, comments with results, and opens a PR.
  If the model exits before the PR call, salvage opens a mechanical
  PR from the branch so work doesn't orphan.

This repo holds the recipes, prompts, the runner, and eval results.
It is *not* the target project — it is the rig.

> Originally project-named `claude_and_goose`, with Goose as the
> executor. Goose's session-loop choice (exit-0 on prose-only turns)
> turned out to be the structural reliability ceiling the harness
> was tripping over. The runner replaced Goose in PR #54 and made
> Goose strictly worse on the same target task (0/6 vs 6/12 model
> PASS + 6/6 review-able-since-salvage). Eval directories from before
> the runner reference Goose because that's what was running.

## Pieces

| Path                          | Purpose |
|-------------------------------|---------|
| `CLAUDE.md`                   | What Claude Code reads on every session |
| `runner/run_recipe.py`        | The executor — Ollama session loop + 7 `github__*` tool wrappers around `gh` |
| `runner/salvage.py`           | Mechanical PR-from-branch fallback when the model exits before `create_pull_request` |
| `runner/gh.py`                | Shared `gh` CLI subprocess helper |
| `recipes/execute-issue.yaml`  | Core recipe: read issue → execute subtasks → PR |
| `recipes/plan-epic.yaml`      | Stub for future runner-driven issue authoring |
| `prompts/system-prompt.md`    | System prompt the runner loads on every session |
| `prompts/issue-format.md`     | Canonical issue template for `runner-task` issues |
| `tests/`                      | Pytest suite for the pure-function surface of the runner |
| `Makefile`                    | `install-dev`, `check`, `test`, `ci`, etc. |
| `evals/`                      | One folder per eval run |
| `scripts/new-eval.sh`         | Scaffold a new `evals/eval-NN/` directory |
| `scripts/check-ollama.sh`     | List installed models on the Ollama host |
| `scripts/post-run-check.sh`   | Verify an eval run produced real artifacts (branches, commits, PR) |

## Execution environment

Ollama host (`bazzite.local`):

- AMD Ryzen 9 9900X (12C/24T)
- 96 GB DDR5
- NVIDIA RTX 5090, 32 GB VRAM
- Running `qwen3.6:latest` (36B params, Q4_K_M, ~24 GB)

The runner executes on the host (or any machine that can reach
`bazzite.local:11434`). The `gh` CLI must be authenticated.

## Running an eval

Prereqs:
- `make install-dev` once, to create `runner/.venv` with deps
- `gh auth status` shows you're logged in
- A `runner-task` issue exists, is `ready-for-execution`, and has no
  open dependencies

```
./scripts/new-eval.sh 24
runner/.venv/bin/python runner/run_recipe.py \
  --recipe recipes/execute-issue.yaml \
  --params issue_number=N \
  --params repo=why-pengo/target_repo \
  | tee evals/eval-24/session.log
```

Then verify and write up the result:
```
./scripts/post-run-check.sh N
# write evals/eval-24/result.md (template scaffolded by new-eval.sh)
```

## Status

The harness loop (Claude plans → runner executes → human reviews →
PR merged) is operational end-to-end on `bazzite.local + qwen3.6`.

Across the 4 most recent k-of-3 batches on the same target
(`health_track#51`):

| Series | Runtime | Salvage | Model PASS | Review-able artifacts |
|---|---|---|---|---|
| eval-17 | Goose + heavy harness | — | 0/3 | 0/3 |
| eval-19 | Goose + slim harness | — | 0/3 | 0/3 |
| eval-20 | Runner v1 | no | 1/3 | 1/3 |
| eval-21 | Runner v2 | no | 0/3 | 0/3 |
| eval-22 | Runner + salvage | yes (unused) | 3/3 | 3/3 |
| eval-23 | Runner + salvage | yes (fired 1×) | 2/3 | **3/3** |
| **Combined runner+salvage** | | | **5/6** | **6/6** |
| **Combined Goose** | | | **0/6** | **0/6** |

See `evals/eval-NN/result.md` for the full timeline and individual
writeups.

## Open follow-ups

- #15 — `push_files` doesn't expose a `mode` field on the underlying
  API, so executables can't be landed with the executable bit set.
  Blocked on upstream
  [github/github-mcp-server#2578](https://github.com/github/github-mcp-server/issues/2578).
- #47 — multi-model bake-off using bazzite headroom (reframed for
  the runner era; tracks whether a larger/code-tuned model improves
  the quality observations from eval-22 + eval-23)
- #57, #58, #59, #61, #66, #69 — runner-side refactors and a
  runner-era HW baseline
