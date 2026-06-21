# eval-31 result

## What ran

- Recipe: `recipes/execute-issue.yaml`
- Params: `issue_number=51`, `repo=why-pengo/health_track`
- Model: `qwen2.5-coder:32b` on `bazzite.local`
- Options: `num_ctx=98304`, `temperature=0.2`
- Pre-warmed via `/api/chat` ping before kickoff; first turn prompt-eval was already cached (no cold-load penalty).

## What worked

- 8 turns to recipe complete — **the fastest end-to-end run in project history** (previous best: eval-30 at 9 turns, same model at default temp).
- Zero nudges, zero loop-detect fires.
- All 8 tool calls came through the prose channel and were rescued by #84.
- PR #82 landed on `health_track` and the issue-51 comment fired cleanly.

## What didn't

- Nothing went wrong. Clean PASS.

## Verdict

Verdict: PASS

## Notes

- `[session metrics: turns=8 | prompt=53332 tok @ 24484.3 t/s | gen=3634 tok @ 64.3 t/s | wall=59.6s]`
- Cold-load was already paid by the warming curl; first turn's `total_duration` was 1.4s.
- Channel discipline unchanged from default temp — qwen2.5-coder still emits 100% via the content channel. Lower temperature did not shift it onto native `tool_calls`. #84 stays load-bearing for this candidate.
