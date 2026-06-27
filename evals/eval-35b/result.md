# eval-35b result

Run 2 of 3 for #101. Back-to-back after eval-35; model stayed warm; no manual state reset (per #98).

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Target: `why-pengo/health_track#51`
- Model: `qwen2.5-coder:32b` on `bazzite.local`
- Options: `num_ctx=98304`, `temperature=0.2`
- Branch: `runner/issue-51-20260627-081227` (distinct from eval-35's `runner/issue-51-20260627-081006` — 2m21s later, runner-owned timestamps per #98)
- PR: [why-pengo/health_track#92](https://github.com/why-pengo/health_track/pull/92)

## What worked

- Clean PR-fired + comment-fired completion in **8 turns**, **95.3s** wall.
- Identical turn-count and wall-time profile to eval-35 (8 turns / 93.4s). Back-to-back determinism is much tighter than the bake-off's eval-30/30b/30c spread (9/28/11) at default temp.
- `create_branch` succeeded first-try with the runner-generated timestamped slug. **No 422 collision** — this is the direct evidence #98 produces in a back-to-back-against-the-same-task setup, which is exactly the scenario that drove eval-31c's PARTIAL.
- `create_pull_request` succeeded first-try.

## What didn't

- Nothing on the runner axis. Recipe-complete by bake-off criteria (PR fired + comment fired, no collisions, no loop-detect engagement).
- Quality nuance (out of scope for #101 but worth noting): the model self-labeled its issue comment `⚠️ partial` because it only committed the `HydrationDaily` schema + `get_hydration_daily` service function — it did not implement the router, register it in `main.py`, or write tests. This matches the artifact eval-35 produced (which the model labeled `✅ done` despite the same omissions). Same artifact, different self-assessment — that's model-sampling variance on the comment, not a runner-axis signal.

## Verdict

**Verdict: PASS**

By the bake-off methodology: recipe-complete (PR fired + comment fired), review-able artifact (PR landed without collisions or retry-spam), no loop-detect engagement, no nudge cascade. Artifact-quality review is a separate axis (#47 subtask 5 / explicitly out of scope for #101).

## Notes

- `[session metrics: turns=8 | prompt=65426 tok @ 24623.4 t/s | gen=5608 tok @ 61.6 t/s | wall=95.3s]`
- Two back-to-back 8-turn / ~95s PASSes is the strongest case yet that #98 + `temperature=0.2` produces a reproducible fast-PASS profile for qwen2.5-coder. Compare to qwen3.6's 24-turn average.
- The `⚠️ partial` self-label vs eval-35's `✅ done` is a comment-style sampling artefact, not a behavioural divergence in the artifact produced.
