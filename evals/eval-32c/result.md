# eval-32c result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`
- Model: `qwen3-coder:30b-a3b-q4_K_M` on `bazzite.local`
- Options: `num_ctx=102400`, `temperature=0.2`
- Back-to-back after eval-32b. Model warm.

## What worked

- Native `tool_calls` end-to-end (zero rescues).
- Loop-detect (#85) fired at turn 51 and prevented a 60-turn-cap waste.
- Salvage found PR #84 already on the target branch (opened by eval-32b) and correctly skipped.

## What didn't

- Same within-batch branch-slug collision pattern previously seen at default temp (eval-27c → #77's branch, eval-30b → its prior run's branch): eval-32c picked the same branch slug eval-32b had used to land PR #84, every `create_pull_request` returned 422 "PR already exists for this head branch", and the model fell into a retry loop. 4 nudges fired before loop-detect aborted.
- 20 `create_or_update_file` calls and 3 `create_branch` attempts — the same iterate-and-refine pattern eval-32b showed, plus the collision overhead.

## Verdict

Verdict: PARTIAL

## Notes

- `[session metrics: turns=51 | prompt=2079838 tok @ 190093.8 t/s | gen=48328 tok @ 176.4 t/s | wall=295.4s]`
- The PARTIAL is partly the recurring "back-to-back same-task runs converge on the same branch slug" failure (independent of temperature) and partly the qwen3-coder-at-low-temp tendency to over-iterate that eval-32b also demonstrated.
- Compared to default-temp eval-27c (PARTIAL at 28 turns, same root cause): low temp made the loop *longer* before loop-detect caught it (51 vs 28 turns). Suggests temp=0.2's added determinism slows the variation needed to make turn-signature drift across the loop-detect threshold.
