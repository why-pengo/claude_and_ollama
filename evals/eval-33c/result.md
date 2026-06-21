# eval-33c result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`
- Model: `qwen3.6:latest` on `bazzite.local`
- Options: `num_ctx=65536`, `temperature=0.2`
- Back-to-back after eval-33b. Model warm.

## What worked

- 19 turns to recipe complete. PR + comment both fired.
- **Zero nudges, zero rescues, zero loop-detect** — first qwen3.6 run in project history to reach `recipe_done` without a single nudge.
- Native `tool_calls` end-to-end. Clean, deterministic execution.

## What didn't

- Nothing went wrong. The cleanest qwen3.6 run captured to date.

## Verdict

Verdict: PASS

## Notes

- `[session metrics: turns=19 | prompt=515002 tok @ 85210.3 t/s | gen=20764 tok @ 226.9 t/s | wall=102.3s]`
- Wall time 102.3s is the fastest end-to-end qwen3.6 run in the project's eval set (default-temp best was eval-28c at 21 turns; this is 19 turns and substantially faster wall-clock).
- The "no nudges" outcome is the headline: at default temp, qwen3.6 *always* needs at least one nudge to advance from write to PR. At temp=0.2 on this particular run, the model self-advanced cleanly.
- Together with eval-33b (1 nudge, 19 turns), the third-run shape suggests low-temp qwen3.6 is *capable* of running the recipe nudge-free, but not reliably (the eval-33 PARTIAL is the cost).
