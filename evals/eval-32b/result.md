# eval-32b result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`
- Model: `qwen3-coder:30b-a3b-q4_K_M` on `bazzite.local`
- Options: `num_ctx=102400`, `temperature=0.2`
- Back-to-back after eval-32. Model warm.

## What worked

- Recipe complete at turn 55. PR and comment both fired — review-able artifact landed.
- Native `tool_calls` end-to-end (zero rescues).
- Loop-detect did not fire; runner reached recipe_done legitimately.

## What didn't

- Massive overshoot. The model issued 21 `create_or_update_file` calls, 4 `create_branch` calls, 4 `create_pull_request` calls (most returning 422 "PR already exists") and 5 nudges before finally completing. Default-temp eval-27b did the same task in 18 clean turns with 1 of each. This is significantly worse on speed and noise.
- The model iterated over the same files repeatedly, treating each `create_or_update_file` response as an invitation to refine rather than as committed state.

## Verdict

Verdict: PASS

## Notes

- `[session metrics: turns=55 | prompt=1680334 tok @ 301258.4 t/s | gen=22997 tok @ 195.0 t/s | wall=133.0s]`
- This is the surprise of #89's batch 2: lowering temperature did **not** improve qwen3-coder's reliability. The PASS rate held, but the *PASSing* run got dramatically noisier and slower (55 turns vs eval-27b's 18). Hypothesis: at low temp the model's deterministic exploration locks into iterate-and-refine patterns that default-temp's randomness would break out of.
- The "1 PR, 1 comment, done" pattern that qwen3-coder showed cleanly at default temp didn't reproduce here.
