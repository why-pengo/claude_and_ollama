# eval-31b result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`
- Model: `qwen2.5-coder:32b` on `bazzite.local`
- Options: `num_ctx=98304`, `temperature=0.2`
- Back-to-back after eval-31; model stayed warm (first turn `total_duration` = 1.1s, no cold-load).

## What worked

- 10 turns to recipe complete. Clean PASS, no nudges, no loop-detect.
- All 10 tool calls prose-rescued by #84.
- PR #83 landed on `health_track`; issue-51 comment fired.

## What didn't

- Nothing went wrong. The slight bump from eval-31's 8 turns to 10 turns reflects the model exploring slightly more before settling on the `push_files` call — still tightly under the 24-turn qwen3.6 average.

## Verdict

Verdict: PASS

## Notes

- `[session metrics: turns=10 | prompt=92747 tok @ 78866.3 t/s | gen=9549 tok @ 62.8 t/s | wall=154.8s]`
- Generation throughput steady ~62.8 t/s across the 10 turns — consistent with a 32B dense model at Q4 on the 5090.
- Comparison anchor: at default temp (eval-30b) qwen2.5-coder went into a 28-turn overshoot PARTIAL on the same task. temp=0.2 here landed cleanly in 10.
