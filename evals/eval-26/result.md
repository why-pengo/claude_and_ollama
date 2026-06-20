# eval-26 result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `llama3.3:70b-instruct-q3_K_M` on `bazzite.local`
- Options: `num_ctx=131072`, `num_gpu=30`
- Turn timeout: 3600s; max_turns=60

## What worked

- Initial `github__get_file_contents` (AGENTS.md) and `github__issue_read` (#51) both succeeded.
- After two false starts, branch `runner/issue-51-hydration-daily` was created from `develop` once the model included `from_branch`.
- The runner's nudge did eventually push the model past the "Failed to create branch" hallucination.

## What didn't

- **Hallucinated failure comments.** Model commented `"Failed to fetch issue #51; stopping"` immediately after a successful read, and `"Failed to create branch; stopping"` after a successful branch creation. The prior tool result was not informing the next assistant turn.
- **Wrong-direction PR attempt.** Tried `github__create_pull_request` with `head: develop` (develop→develop) and title `"Step 6: Comment on the issue"` — recipe step text leaked into the PR title.
- **Tool calls emitted as prose.** From turn ~10 onward the model produced well-formed tool-call JSON (`{"type": "function", "name": "github_create_or_update_file", ...}`) but in the content channel rather than as a structured `tool_calls` reply. The runner saw no tool call and nudged.
- **Sampling-collapse loop.** The same 1064-char prose blob targeting `backend/app/routers/hydration.py` repeated verbatim ~12 times. The runner nudged identically each time and never escalated.
- **No commits landed.** Salvage reports the branch has no commits ahead of `develop`. One real `create_or_update_file` for `routers/hydration.py` fired at turn ~25 but either failed server-side or never produced a commit.
- Hit `max_turns=60`; salvage had nothing to open a PR from.

## Verdict

Verdict: FAIL

## Next time

- Sanity-check that `/api/chat` + llama3.3 q3 actually surfaces `tool_calls` cleanly; the model knows the JSON shape but emits it as content, which suggests the chat template or tool-call adapter isn't catching it. Try qwen2.5-coder or llama3.1:8b-instruct for a known-good tool-call baseline before re-running.
- Add a prose-shaped-tool-call rescue in the runner: if a prose-only turn contains `"type": "function"` / `"name": "github_*"`, parse it as the intended tool call instead of nudging.
- Add loop-detection: if the same prose hash repeats N (e.g. 3) times in a row, abort the run instead of burning the remaining turn budget.
- Revisit `num_ctx=131072` + `num_gpu=30` on 70B q3 — likely CPU spillover (see commit 72c2b45 throughput-curve note); a smaller context window may improve both speed and turn-to-turn coherence.
