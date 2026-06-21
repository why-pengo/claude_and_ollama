# eval-27c result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`, `base_branch=develop`
- Model: `qwen3-coder:30b-a3b-q4_K_M`
- Options: `{'num_ctx': 102400}`
- Bazzite env: f16 KV, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_DEBUG=2`
- Pre-flight: 100% GPU resident at 102400
- Third of 3 qwen3-coder runs in the #47 bake-off — see `docs/bakeoff-summary.md` for comparative analysis

## What worked

- All issue-mandated files written and pushed.
- PR #77 opened on health_track.
- **First production fire of the #85 loop detection guard.** Aborted at turn 28 instead of burning all 60. Artifact (PR #77) was preserved; salvage correctly recognised it and opted out.

## What didn't

- **Overshoot pattern after recipe artifact was complete.** Trajectory:
  - Turns 1–3: AGENTS read, issue read, create_branch (with one prose-only blip recovered after a step-aware nudge)
  - Turns 4–20: standard reads + writes + push_files + create_pull_request (PR #77 opened cleanly here)
  - Turns 21+: model kept going — additional reads + writes + a duplicate `create_pull_request` (rejected because PR exists) + 5 identical `add_issue_comment` calls in a row
  - Turn 28: loop-detect signature counter reached threshold on the repeated comment call; runner aborted
- `recipe_done` didn't fire because the first `add_issue_comment` likely returned ERROR (malformed args), so the comment tool never reached `succeeded`; subsequent identical calls also failed and drove the loop counter.
- One prose-only turn (324 chars) at turn 4 — recovered after a nudge.

## Verdict

Verdict: PARTIAL

PR #77 landed cleanly with all the issue's required files; the model's confusion came AFTER the artifact was complete. From a "did the runner produce a review-able PR" perspective this is a success. From a "did the recipe complete cleanly" perspective it's a partial. Loop detection (#85) saved the run from burning ~3× the turns it actually used.

## Next time

- Bake-off complete; no per-eval next-time items.
- The overshoot pattern is a recurring observation across code-tuned candidates — see `docs/bakeoff-summary.md` finding #4, and #89 for the temperature-tuning angle that might address it.
