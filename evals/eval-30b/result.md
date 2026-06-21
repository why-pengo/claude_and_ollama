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
- **Second production fire of #85 loop detection** at turn 28 — saved the run from burning to max_turns.
- Salvage correctly recognised that a PR existed on the branch and opted out (no duplicate salvage attempt).

PR-number attribution: eval-30b's branch slug matched eval-30's, so PR #81 (which eval-30 opened cleanly) already existed on the branch by the time eval-30b's `create_pull_request` calls fired. The duplicate-attempt + comment-loop pattern is what drove this run into the overshoot; we can't conclude from the logs alone whether any of 30b's PR calls successfully landed a *new* PR — the salvage output just says "PR already exists." Either way, the artifact (PR #81 with the issue's required files) is review-able regardless of which run produced it.

## What didn't

- **Same overshoot pattern as eval-27c.** Got to a successful `create_pull_request` around turn 10, then kept going: more file reads, a duplicate `create_pull_request` attempt (rejected — PR exists), and a cluster of `add_issue_comment` calls that drove the loop-detect counter to threshold.
- Suspected root cause: the first `add_issue_comment` likely returned ERROR (malformed args — probably bad `issue_number` or missing `body`), so `add_issue_comment` never reached `succeeded`. Subsequent identical calls also failed and accumulated.

## Verdict

Verdict: PARTIAL

Artifact (PR #81 on the matching branch, with all the issue's required files) is review-able; `recipe_done` never fired because the comment tool kept ERRORing. From a "did we produce a review-able PR" perspective this run is PARTIAL on the review-able side; from a "did the recipe complete cleanly" perspective it's a partial on the cleanly side.

The overshoot pattern in 30b mirrors qwen3-coder's 27c — both code-tuned models show this tendency. See `docs/bakeoff-summary.md` finding #4.

## Next time

- Bake-off complete; no per-eval next-time items.
- The overshoot loop happens *after* the artifact is complete, so the work is preserved every time #85 catches it. That's a structural feature of the loop-detection design, not a bug.
