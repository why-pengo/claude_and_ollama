# eval-31c result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`
- Model: `qwen2.5-coder:32b` on `bazzite.local`
- Options: `num_ctx=98304`, `temperature=0.2`
- Back-to-back after eval-31b; model stayed warm.

## What worked

- Tool-call channel discipline held — every model emission was prose-shaped and parseable; #84 rescued cleanly on every turn through turn ~10.
- Loop detection (#85) fired at turn 22 and prevented a 60-turn-cap waste.
- Salvage step found PR #83 already on the target branch and correctly skipped (no duplicate PR opened).

## What didn't

- Model picked the same branch slug (`runner/issue-51-hydration-daily-endpoint`) that eval-31b had already used to land PR #83. Every subsequent `create_pull_request` attempt returned 422 "PR already exists for this head branch", which the model interpreted as a generic validation error and kept retrying — the exact branch-collision-overshoot pattern previously seen in eval-27c and eval-30b.
- 4 nudges fired (3-empty-turn guard reset path) before loop-detect caught the repeating signature.

## Verdict

Verdict: PARTIAL

## Notes

- `[session metrics: turns=22 | prompt=298752 tok @ 97522.5 t/s | gen=9404 tok @ 60.7 t/s | wall=161.5s]`
- This is **not** a temperature-induced failure — same root cause as eval-27c (qwen3-coder) and eval-30b (qwen2.5-coder default temp): back-to-back runs against the same target task tend to converge on the same branch slug, and the second collision burns turns in a retry loop. The runner has no logic to mutate the slug between same-task runs.
- Crucially: no PR-less FAIL like eval-30c's 18,689-char prose blob — temp=0.2 avoided the giant-prose-blob failure mode that doomed eval-30c at default temp. The variance tightened on both ends (no FAIL, faster PASSes).
