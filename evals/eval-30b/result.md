# eval-30b result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `qwen2.5-coder:32b`
- Options: `{'num_ctx': 98304}`
- Bazzite env: f16 KV, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_DEBUG=2`
- Pre-flight: 100% GPU resident at 98304
- Second of 3 qwen2.5-coder runs in the #47 bake-off (post-#84)

## What worked

- All 28 turns rescued from prose by #84 — same channel-discipline pattern as eval-30. Rescue is 100% reliable for this model.
- PR landed (#81 on health_track, opened by this run).
- **Second production fire of #85 loop detection** at turn 28 — saved the run from burning to max_turns.
- Salvage correctly recognised that PR #81 existed on the branch and opted out (no duplicate salvage attempt).

## What didn't

- **Same overshoot pattern as eval-27c.** Got to a successful `create_pull_request` around turn 10, then kept going: more file reads, a duplicate `create_pull_request` attempt (rejected — PR exists), and a cluster of `add_issue_comment` calls that drove the loop-detect counter to threshold.
- Suspected root cause: the first `add_issue_comment` likely returned ERROR (malformed args — probably bad `issue_number` or missing `body`), so `add_issue_comment` never reached `succeeded`. Subsequent identical calls also failed and accumulated.

## Verdict

Verdict: **PARTIAL**

Artifact landed (PR #81 with all the issue's required files) but `recipe_done` never fired because the comment tool kept ERRORing. From a "did we produce a review-able PR" perspective this is review-able; from a "did the recipe complete cleanly" perspective it's a partial.

The overshoot pattern in 30b mirrors qwen3-coder's 27c — both code-tuned models show this tendency. See `docs/bakeoff-summary.md` finding #4.

## Next time

- Bake-off complete; no per-eval next-time items.
- The overshoot loop happens *after* the artifact is complete, so the work is preserved every time #85 catches it. That's a structural feature of the loop-detection design, not a bug.
