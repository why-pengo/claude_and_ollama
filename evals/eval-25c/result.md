# eval-25c result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, resolved `base_branch=develop`
- Model: `llama3.3:70b-instruct-q3_K_M`
- Options: `{'num_ctx': 131072, 'num_gpu': 30}`
- Turn timeout: `3600s` (eval-25b's regression fix from 9770fd2)
- Runner branch: `chore/issue-78-native-api-chat` (PR #80, commit a470c42)
- Bazzite env: `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` (via `start-with-kv-quant.sh`)

## What worked — the headline

**First end-to-end recipe completion in this project's eval history.** All prior runs (evals 14–24b) either stalled and required salvage, crashed, or didn't reach the PR step. Final log line:

```
=== Recipe complete: PR + issue comment both fired (turn 22) ===
```

No salvage intervention. The model itself called `github__create_pull_request` and `github__add_issue_comment` and both succeeded. Recipe completion detected by the runner.

## What landed on health_track

- **PR #75** — opened by the model. Branch `runner/issue-51-hydration-daily`, base `develop`. Body uses the recipe template (`Closes #51`, summary, verification disclaimer, subtasks checklist).
- **Comment on #51**: `✅ done: PR https://github.com/why-pengo/health_track/pull/75`.
- **One file**: `backend/app/schemas/hydration.py` (+10 lines, schema only). The other four subtasks from #51 (analytics service function, router, main.py registration, test file) were not implemented despite the PR title claiming "schema **and analytics service**".

## What was messy

22 turns is high for what should be ~8 turns of clean execution. Reading the tool-call timeline, the model made **three full attempts** before converging:

| Attempt | Lines | Branch tried | Outcome |
|---|---|---|---|
| 1 | 37–52 | `runner/issue-51-hydration-daily-endpoint` | failed (create_pull_request likely 422'd) |
| 2 | 95–110 | retry on same branch | also failed |
| 3 | 139–199 | switched to `runner/issue-51-hydration-daily`, switched to `create_or_update_file` instead of `push_files` | succeeded |

Other oddities:
- **One prose-only slip** near the end: the model emitted `{"name": "github__add_issue_comment", "parameters": {...}}` as plain-text content rather than as a structured tool call. The runner's step-aware nudge recovered it on the next turn.
- **PR title over-claims**: "feat: add hydration daily schema **and analytics service**" — but only the schema (10 lines, one file) landed. Same class of over-claim that qwen3.6 hit in eval-04 about executable bits. Known model failure mode, not a runner bug.

## Signal for #47 (multi-model bake-off)

This is the **first qualitative data point** that model scale matters for recipe completion under this harness:

| Model | Eval | Recipe completion | Tool calls before stall | Recovery posture |
|---|---|---|---|---|
| qwen3.6:latest | 24, 24b | ❌ never | ~5, ~5 | stalls → salvage required |
| llama3.3:70b-instruct-q3_K_M | 25c | ✅ end-to-end | 22 (3 attempts) | self-recovers via retry |

Qwen3.6's failure mode is "stall and stop trying"; llama3.3's is "stumble, recognize failure, retry differently." That's a qualitatively different posture, not just a quantitative speedup.

**Caveat: one data point.** Could be lucky variance. The bake-off should rerun llama3.3:70b at least 2–3 more times to see if completion reproduces. If yes, this seriously raises the "70B-class as production runner" question.

## Side observations

- KV quant on bazzite (`OLLAMA_KV_CACHE_TYPE=q8_0`) was load-bearing: without it, 131K context wouldn't fit, and the recipe's full prompt + tool-call history at 22 turns may not have fit in the smaller 65K window.
- `num_gpu=30` worked but left ~10 GiB VRAM unused (per `/api/ps` during the run). Bumping num_gpu to 40 or 45 would push more work to GPU and likely raise t/s — worth trying in a follow-up.
- Throughput stayed ~1.29 t/s as measured during eval-25b. 22 turns at this rate adds up to ~30–60 min wall-clock for a complete recipe.

## Verdict
Verdict: PASS

- ✅ Recipe completed end-to-end without salvage
- ✅ Options flowed through cleanly (`num_ctx=131072`, `num_gpu=30` honored)
- ✅ Turn timeout fix from eval-25b held — no httpx.ReadTimeout
- ✅ Closes #78 (all five acceptance criteria empirically validated, not just unit-tested)
- 🎯 First completion in eval history → strong signal for #47

## Next time

- Rerun llama3.3:70b on #51 (call it eval-26) to test whether completion reproduces. If it does, that's the bake-off green light for 70B-class as a serious candidate.
- Then run it on a different ready-for-execution issue (e.g. #50, HydrationGoals model — more files, includes a migration) to test recipe completion on a different shape of task.
- Consider tuning `num_gpu` up (40, 45) and rerunning to measure throughput gain. The bake-off should pick a near-optimal num_gpu per model rather than the conservative 30.
- PR #75 disposition: schema-only is incomplete; close-don't-merge per the salvaged-partial workflow established in eval-24b. Audit trail kept in this writeup + PR body.
- Address the over-claim failure mode in recipe scaffolding: a tighter PR-body template that forces the model to list ONLY files-actually-changed could prevent the title/body drift.
