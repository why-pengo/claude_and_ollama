# eval-35c result

Run 3 of 3 for #101. Back-to-back after eval-35b; model stayed warm.

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Target: `why-pengo/health_track#51`
- Model: `qwen2.5-coder:32b` on `bazzite.local`
- Options: `num_ctx=98304`, `temperature=0.2`
- Branch: `runner/issue-51-20260627-081519`
- PR: [why-pengo/health_track#93](https://github.com/why-pengo/health_track/pull/93)

## What worked

- Clean PR-fired + comment-fired completion in **10 turns**, **102.7s** wall. Comment self-labeled `✅ done`.
- This run produced a more complete artifact than eval-35 / eval-35b: schema + service + router file + test file (the model executed 4 of the 5 subtasks; main.py registration was the only omission).
- `create_branch` succeeded first-try with the runner-generated timestamped slug. No 422 collision.
- `create_pull_request` succeeded first-try.
- All emissions prose-shaped and parsed by #84.

## What didn't

Nothing on the runner axis. Recipe-complete by bake-off criteria.

## Verdict

**Verdict: PASS**

## Notes

- `[session metrics: turns=10 | prompt=80244 tok @ 60650.4 t/s | gen=6315 tok @ 63.4 t/s | wall=102.7s]`
- The 2-turn / 10s difference from eval-35 and eval-35b corresponds to the extra `create_or_update_file` calls for the router and test file — the model elected to do more on this run, and the additional turns are doing real work, not loop-detect-relevant retries.
- Gen throughput holds at ~63 t/s across the run despite the warm-cache 4th-back-to-back invocation. No tg-curve degradation.
