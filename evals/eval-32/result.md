# eval-32 result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`
- Model: `qwen3-coder:30b-a3b-q4_K_M` on `bazzite.local`
- Options: `num_ctx=102400`, `temperature=0.2`
- Clean-slate re-run after batch 1 PR/branch cleanup (PRs #82 + #83 closed, runner branches deleted).

## What worked

- 15 turns to recipe complete — slightly faster than the default-temp baseline (eval-27 at 16 turns).
- Zero rescues (qwen3-coder uses native `tool_calls` end-to-end), zero nudges, zero loop-detect.
- Tool call distribution was minimal: 1 issue_read, 1 create_branch, 5 reads, 5 writes, 1 push_files, 1 PR, 1 comment. No retries.

## What didn't

- Nothing went wrong. Clean PASS.

## Verdict

Verdict: PASS

## Notes

- `[session metrics: turns=15 | prompt=208157 tok @ 75655.2 t/s | gen=9931 tok @ 231.7 t/s | wall=47.5s]`
- Gen rate 231.7 t/s confirms MoE active-params behavior (qwen3-coder = `30b-a3b` ≈ 3B active).
- First-of-three runs in a clean-state batch are reliably the cleanest; the convergence-on-same-branch-slug pattern only kicks in for the 2nd/3rd runs.
