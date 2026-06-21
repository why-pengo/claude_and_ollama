# eval-33 result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`
- Model: `qwen3.6:latest` on `bazzite.local`
- Options: `num_ctx=65536`, `temperature=0.2`
- Clean-slate re-run after batch 2 cleanup (PRs #84 + #85 closed, runner branches deleted).

## What worked

- Model created the branch, wrote 1 file (`backend/app/services/analytics.py`).
- Loop detection (#85) fired at turn 10 — clean abort.
- **Salvage step opened PR #86 from the 1 commit the model managed before looping.** Review-able artifact landed even though the model didn't reach recipe_done.

## What didn't

- After committing the first file, the model fell into a `get_file_contents` loop, fetching `backend/app/services/analytics.py` from `develop` four consecutive times (re-reading the file it had just written a change against on a different branch). Loop-detect caught it at turn 10.
- Model never reached `create_pull_request` itself; salvage opened PR #86 mechanically with only the 1 partial commit.
- Same failure mode as the discarded contaminated eval-33 (qwen3.6 at temp=0.2 doing self-referential file re-reads), but caught faster here by loop-detect because the repetition was uniform.

## Verdict

Verdict: PARTIAL

## Notes

- `[session metrics: turns=10 | prompt=204309 tok @ 38768.7 t/s | gen=3125 tok @ 235.2 t/s | wall=20.8s]`
- Gen rate 235 t/s confirms qwen3.6's MoE architecture in action (256 experts / top-8 active).
- This is a regression vs default temp — eval-28 (qwen3.6 default temp) was a clean 23-turn PASS on the same task. At temp=0.2 the model gets stuck in deterministic re-reading loops that default-temp's randomness would break out of (same hypothesis as batch 2's qwen3-coder iterate-and-refine).
- The salvage rescue here is exactly what the salvage step exists for; the runner is doing its job even when the model isn't.
