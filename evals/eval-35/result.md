# eval-35 result

Run 1 of 3 for #101: re-eval qwen2.5-coder@temperature=0.2 against `why-pengo/health_track#51` now that #98 has eliminated the within-batch branch-slug collision failure mode.

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Target: `why-pengo/health_track#51` (the hydration-daily-endpoint canonical task)
- Model: `qwen2.5-coder:32b` on `bazzite.local`
- Options: `num_ctx=98304`, `temperature=0.2`
- Branch: `runner/issue-51-20260627-081006` (runner-owned, generated at session start per #98)
- PR: [why-pengo/health_track#91](https://github.com/why-pengo/health_track/pull/91)

## What worked

- Clean PR-fired + comment-fired completion in **8 turns**, **93.4s** wall.
- All emissions prose-shaped; `#84` tool-call rescue worked on every turn that needed it.
- One non-tool prose turn (turn ~5, 18,947 chars) was caught by the empty-turn nudge and immediately produced the correct `create_pull_request` call on the next turn. Loop detection never engaged.
- `create_branch` succeeded first-try on `runner/issue-51-20260627-081006` (no 422 collision, vindicating #98 in production).
- `create_pull_request` succeeded first-try against the runner-owned head branch.

## What didn't

Nothing. Clean PASS.

## Verdict

Verdict: PASS

## Notes

- `[session metrics: turns=8 | prompt=65266 tok @ 20852.4 t/s | gen=5475 tok @ 61.7 t/s | wall=93.4s]`
- 8 turns is the fastest qwen2.5-coder PASS observed in any eval to date, beating eval-30's 9-turn PASS at default temp and eval-34's 10-turn shakedown PASS at this temp.
- The gen throughput (~61 t/s) is consistent with the qwen2.5-coder profile from eval-31c (60.7 t/s) and eval-34. No degradation from the long-context analytics.py read (4673 tok prompt expansion on turn 4).
